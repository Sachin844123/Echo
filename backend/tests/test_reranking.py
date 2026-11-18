"""Contextual retrieval correctness on tiny synthetic TEST DATA, not research evidence."""

import json
import time

import pytest
from pydantic import ValidationError

from app.api.search import SearchInput
from app.core.config import RerankWeights, Settings
from app.database.models import Collection, CollectionItem
from app.retrieval.reranking import Candidate, coverage, rerank, terms
from evaluation.dataset import Dataset, EvaluationError, RunConfig, fingerprint
from evaluation.run_eval import evaluate_weight_sweep, main, run_evaluation
from evaluation.sweep import WeightSweep, load_sweep
from test_evaluation import manifest
from test_retrieval import UnitEncoder, indexed, searcher


def weights(**changes):
    return RerankWeights(**{key: changes.get(key, 0) for key in RerankWeights.model_fields})


@pytest.mark.parametrize("value", [-1, 101, float("nan"), float("inf")])
def test_weights_reject_nonfinite_negative_or_excessive(value):
    with pytest.raises(ValidationError):
        RerankWeights(rrf=value)


def test_weights_require_a_positive_value_and_are_configured_from_environment(monkeypatch):
    with pytest.raises(ValidationError):
        weights()
    with pytest.raises(ValidationError):
        RerankWeights(unknown=1)
    monkeypatch.setenv("ECHO_RERANK_WEIGHTS", json.dumps(weights(rrf=1).model_dump()))
    assert Settings.from_env().rerank_weights == weights(rrf=1)


def test_normalized_formula_unicode_exact_overlap_and_empty_terms():
    candidate = Candidate(1, 2 / 61, "Solar", "Power", "solar solar other", "pdf", True)
    result = rerank([candidate], "solar power", ["pdf"], weights(rrf=1, title_heading=1, keyword_overlap=2, source_type=1, collection=1), 60)[0]
    assert result.signals == {"rrf": 1, "title_heading": 0.5, "keyword_overlap": 0.5, "source_type": 1, "collection": 1}
    assert result.score == pytest.approx(0.75)
    assert terms("ＳＯＬＡＲ solar SOLAR") == {"solar"}
    assert coverage(terms("café"), "CAFE\u0301") == 1
    assert coverage(terms("solar"), "solarized") == 0
    assert coverage(set(), "TEST DATA") == 0
    empty = rerank([candidate], "!!!", [], weights(rrf=1), 60)[0]
    assert empty.signals["title_heading"] == empty.signals["keyword_overlap"] == 0


@pytest.mark.parametrize("signal", ["title_heading", "keyword_overlap", "source_type", "collection"])
def test_each_context_signal_can_change_order_independently(signal):
    first = Candidate(1, 1 / 61, "lunar", None, "lunar", "note", False)
    second = Candidate(2, 1 / 62, "unrelated", "solar", "solar", "pdf", True)
    hits = rerank([first, second], "solar", ["pdf"], weights(**{signal: 1}), 60)
    assert [hit.chunk_id for hit in hits] == [2, 1]
    assert all(0 <= hit.score <= 1 and all(0 <= value <= 1 for value in hit.signals.values()) for hit in hits)


def test_rrf_only_and_ties_preserve_original_ranking():
    candidates = [Candidate(key, score, "TEST DATA", None, "TEST DATA", "note")
                  for key, score in [(3, 1 / 62), (2, 1 / 61), (1, 1 / 61)]]
    assert [hit.chunk_id for hit in rerank(candidates, "solar", [], weights(rrf=1), 60)] == [1, 2, 3]
    # Missing optional context has zero signal; original RRF is the tie-breaker.
    assert [hit.chunk_id for hit in rerank(candidates, "solar", [], weights(collection=1), 60)] == [1, 2, 3]
    a = rerank(candidates, "solar", [], weights(rrf=1, keyword_overlap=1), 60)
    b = rerank(candidates, "solar", [], weights(rrf=2, keyword_overlap=2), 60)
    assert [hit.score for hit in a] == [hit.score for hit in b]


def test_engine_reranks_same_candidates_before_grouping_and_keeps_hard_filters(searcher):
    first = indexed(searcher, 1, ["TEST DATA solar solar", "TEST DATA solar other excerpt"])
    second = indexed(searcher, 2, ["TEST DATA solar note"])
    with searcher.sessions.begin() as session:
        collection = Collection(name="TEST DATA context group")
        session.add(collection)
        session.flush()
        group = collection.id
        session.add(CollectionItem(collection_id=group, source_id=second))
    base = searcher.search(SearchInput(query="solar", mode="hybrid"))
    searcher.settings = searcher.settings.model_copy(update={"rerank_weights": weights(rrf=1)})
    contextual = searcher.search(SearchInput(query="solar", mode="hybrid_contextual"))
    assert [(r["source_id"], r["chunk_id"]) for r in contextual["results"]] == [(r["source_id"], r["chunk_id"]) for r in base["results"]]
    searcher.settings = searcher.settings.model_copy(update={"rerank_weights": weights(collection=1)})
    hinted = SearchInput(query="solar", mode="hybrid_contextual", context={"collection_id": group})
    result = searcher.search(hinted)
    assert result["candidate_counts"] == base["candidate_counts"]
    assert [row["source_id"] for row in result["results"]] == [second, first]
    assert result["results"][0]["rerank_signals"]["collection"] == 1
    assert result["results"][1]["rerank_signals"]["collection"] == 0
    assert result["reranking"]["weights"] == weights(collection=1).model_dump()
    for mode in ("keyword", "semantic", "hybrid"):
        unhinted = searcher.search(SearchInput(query="solar", mode=mode))
        hinted_base = searcher.search(SearchInput(query="solar", mode=mode, context={"collection_id": group}))
        assert unhinted == hinted_base
    assert searcher.search(hinted.model_copy(update={"source_types": ["pdf"]}))["results"] == []
    # An unmatched soft collection does not filter out the underlying candidates.
    missing = searcher.search(SearchInput(query="solar", mode="hybrid_contextual", context={"collection_id": 999}))
    assert len(missing["results"]) == 2


def test_http_contextual_search_is_authenticated_bounded_and_explainable(client, app, auth):
    app.state.search.encoder = UnitEncoder()
    app.state.search.reconcile()
    imported = client.post("/api/v1/imports/notes", headers=auth, json={"title": "TEST DATA solar", "text": "TEST DATA solar battery"}).json()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        source = client.get(f'/api/v1/sources/{imported["source_id"]}', headers=auth).json()
        if source["processing_status"] == "indexed":
            break
        time.sleep(0.05)
    assert source["processing_status"] == "indexed"
    body = {"query": "solar", "mode": "hybrid_contextual", "context": {"source_types": ["note"]}}
    assert client.post("/api/v1/search", json=body).status_code == 401
    response = client.post("/api/v1/search", headers=auth, json=body)
    assert response.status_code == 200
    hit = response.json()["results"][0]
    assert hit["source_id"] == imported["source_id"]
    assert hit["rerank_signals"]["source_type"] == 1
    assert "rrf_score" in hit and "start_offset" in hit
    bad = client.post("/api/v1/search", headers=auth, json={**body, "context": {"source_types": ["PRIVATE INVALID"]}})
    assert bad.status_code == 422 and "PRIVATE" not in bad.text


def grid():
    return WeightSweep.model_validate({"settings": [
        {"id": "rrf_only", "weights": weights(rrf=1).model_dump()},
        {"id": "context_only", "weights": weights(collection=1).model_dump()}]})


@pytest.mark.parametrize("change", [
    lambda data: data["settings"][0].update(id="../escape"),
    lambda data: data["settings"][0].update(weights={"rrf": 1}),
    lambda data: data["settings"][1].update(id="RRF_ONLY"),
    lambda data: data["settings"][1].update(weights=data["settings"][0]["weights"]),
    lambda data: data["settings"][0]["weights"].update(rrf=float("nan")),
    lambda data: data.update(settings=[]),
])
def test_sweep_contract_rejects_ambiguous_or_invalid_settings(change):
    data = grid().model_dump()
    change(data)
    with pytest.raises(ValidationError):
        WeightSweep.model_validate(data)


def test_soft_context_is_independent_of_positive_label_eligibility(manifest):
    _, data = manifest
    data["queries"]["tuning"][0]["context"] = {"source_types": ["pdf"], "collection": "coast"}
    assert Dataset.model_validate(data).queries.tuning[0].relevance == {"d1": 3}
    data["queries"]["tuning"][0]["context"]["collection"] = "missing"
    with pytest.raises(ValidationError):
        Dataset.model_validate(data)


def test_sweeps_reject_test_split_before_reading_inputs(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    output = tmp_path / "must-not-exist"
    with pytest.raises(EvaluationError, match="weight_sweep_requires_tuning_split"):
        run_evaluation(missing, output, RunConfig(), "test", tmp_path, grid())
    assert main(["--dataset", str(missing), "--split", "test", "--weight-sweep", str(missing), "--output", str(output)]) == 2
    assert "weight_sweep_requires_tuning_split" in capsys.readouterr().err
    assert not output.exists()


def test_load_sweep_redacts_bad_payload(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"settings":[{"id":"bad","weights":{"PRIVATE":1}}]}')
    with pytest.raises(EvaluationError, match="invalid_weight_sweep") as error:
        load_sweep(path)
    assert "PRIVATE" not in str(error.value)


def test_tuning_sweep_reports_every_setting_and_exports_frozen_configs(manifest, tmp_path, monkeypatch):
    from evaluation import run_eval
    real_search = run_eval.SearchEngine
    monkeypatch.setattr(run_eval, "SearchEngine", lambda *args: real_search(*args, encoder=UnitEncoder()))
    path, data = manifest
    data["queries"]["tuning"][0]["context"] = {"source_types": ["txt"], "collection": "energy"}
    path.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "TEST DATA sweep"
    report = run_evaluation(path, output, RunConfig(repeats=1), "tuning", tmp_path / "unit", grid())
    assert set(report["methods"]) == {"keyword", "semantic", "hybrid", "hybrid_contextual"}
    assert report["methods"]["hybrid_contextual"]["method_id"] == "D"
    sweep = report["weight_sweep"]
    assert sweep["split"] == "tuning"
    assert {setting["id"] for setting in sweep["settings"]} == {"rrf_only", "context_only"}
    for setting in sweep["settings"]:
        assert [row["query_id"] for row in setting["result"]["queries"]] == ["q_tune"]
        assert setting["result"]["latency"]["samples"] == 1
        frozen = json.loads((output / "configs" / f'weights-{setting["id"]}.json').read_text())
        assert fingerprint(frozen) == setting["config_sha256"]
        assert RunConfig.model_validate(frozen).rerank_weights.model_dump() == setting["weights"]
    exported = (output / "report.json").read_text(encoding="utf-8") + (output / "weight-sweep.csv").read_text()
    assert "q_test" not in exported and "PRIVATE" not in exported


def test_sweep_restores_search_weights_if_evaluation_fails(manifest, searcher, monkeypatch):
    from evaluation import run_eval
    dataset = Dataset.model_validate(manifest[1])
    original = searcher.settings

    def fail(*args, **kwargs):
        raise EvaluationError("TEST DATA deliberate failure")
    monkeypatch.setattr(run_eval, "evaluate_queries", fail)
    with pytest.raises(EvaluationError):
        evaluate_weight_sweep(searcher, dataset, {}, {}, RunConfig(), None, grid(), split="tuning")
    assert searcher.settings is original
