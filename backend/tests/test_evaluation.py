"""M4 uses tiny synthetic TEST DATA only; no research corpus or results."""

import copy
import json
import math
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import REPO_ROOT
from evaluation.dataset import Dataset, EvaluationError, RunConfig, load_dataset, resolve_document
from evaluation.metrics import latency_summary, macro_average, ranking_metrics
from evaluation.resources import MemorySampler
from evaluation.run_eval import check_files, evaluate_queries, main, run_evaluation


@pytest.fixture
def manifest(tmp_path):
    corpus = tmp_path / "TEST DATA input"
    corpus.mkdir()
    (corpus / "solar.txt").write_text("TEST DATA PRIVATE SOLAR CONTENT: solar panels produce electricity from sunlight.", encoding="utf-8")
    (corpus / "ocean.txt").write_text("TEST DATA PRIVATE OCEAN CONTENT: ocean tides and waves affect coastal beaches.", encoding="utf-8")
    data = {"schema_version": 1, "id": "test_fixture", "kind": "test_fixture", "documents": [
        {"id": "d1", "path": "solar.txt", "title": "TEST DATA PRIVATE TITLE", "source_type": "txt",
         "captured_at": "2020-01-01T00:00:00Z", "collections": ["energy"]},
        {"id": "d2", "path": "ocean.txt", "title": "TEST DATA coastal notes", "source_type": "note",
         "captured_at": "2021-01-01T00:00:00Z", "collections": ["coast"]}],
        "queries": {"tuning": [{"id": "q_tune", "text": "TEST DATA PRIVATE QUERY solar electricity",
            "filters": {"collection": "energy", "captured_to": "2020-12-31T23:59:59Z", "source_types": ["txt"]}, "relevance": {"d1": 3}}],
            "test": [{"id": "q_test", "text": "TEST DATA PRIVATE HELDOUT QUERY ocean beaches", "relevance": {"d2": 2}}]}}
    path = corpus / "dataset.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def test_metrics_known_graded_order_and_fixed_precision_denominator():
    rows = ranking_metrics(["b", "x", "a"], {"a": 3, "b": 1, "c": 2})
    assert rows["Precision@5"] == 2 / 5
    assert rows["Recall@5"] == 2 / 3
    assert rows["MRR"] == 1
    assert rows["NDCG@10"] == pytest.approx((1 + 7 / 2) / (7 + 3 / math.log2(3) + 1 / 2))
    assert ranking_metrics(["a"], {"a": 1})["Precision@5"] == 0.2
    assert ranking_metrics(["x", "a"], {"a": 1})["MRR"] == 0.5
    assert ranking_metrics([str(n) for n in range(10)] + ["a"], {"a": 3})["MRR"] == 0
    assert ranking_metrics([], {"a": 3}) == {"Precision@5": 0, "Recall@5": 0, "MRR": 0, "NDCG@10": 0}
    assert ranking_metrics(["a"], {"a": 0})["Recall@5"] == 0


def test_metrics_reject_duplicate_results_bad_grades_and_empty_summaries():
    for result, labels in [(["a", "a"], {"a": 1}), (["a"], {"a": True}), (["a"], {"a": 4})]:
        with pytest.raises(ValueError):
            ranking_metrics(result, labels)
    with pytest.raises(ValueError):
        macro_average([])
    first, second = ranking_metrics(["a"], {"a": 1}), ranking_metrics([], {"a": 1})
    assert macro_average([first, second])["Recall@5"] == 0.5


def test_latency_nearest_rank_small_samples_and_nonfinite():
    assert latency_summary([0.1]) == {"samples": 1, "median_ms": 100, "p95_ms": 100}
    summary = latency_summary([number / 1000 for number in range(1, 21)])
    assert summary["samples"] == 20
    assert summary["median_ms"] == pytest.approx(10.5)
    assert summary["p95_ms"] == pytest.approx(19)
    for samples in ([], [-1], [float("nan")], [float("inf")]):
        with pytest.raises(ValueError):
            latency_summary(samples)


@pytest.mark.parametrize("mutation", [
    lambda d: d["documents"].append(copy.deepcopy(d["documents"][0])),
    lambda d: d["queries"]["test"][0].update(id="q_tune"),
    lambda d: d["queries"]["test"][0].update(text="  test data private QUERY solar   electricity  "),
    lambda d: d["queries"]["tuning"][0].update(relevance={"missing": 2}),
    lambda d: d["queries"]["tuning"][0].update(relevance={"d1": True}),
    lambda d: d["queries"]["tuning"][0].update(relevance={"d1": 4}),
    lambda d: d["queries"]["tuning"][0].update(relevance={"d1": 0}),
    lambda d: d["queries"]["tuning"][0].update(relevance={"d2": 1}),
    lambda d: d["queries"]["tuning"][0].update(filters={"collection": "unknown"}),
    lambda d: d["queries"]["tuning"][0].update(filters={"captured_from": "2020-01-01"}),
    lambda d: d["queries"].update(test=[]),
    lambda d: d["documents"][0].update(captured_at="2020-01-01"),
    lambda d: d.update(secret_unknown_field="PRIVATE"),
    lambda d: d.update(schema_version=True),
])
def test_dataset_rejects_leakage_invalid_labels_filters_and_contract(manifest, mutation):
    path, data = manifest
    mutation(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(EvaluationError, match="invalid_dataset_contract"):
        load_dataset(path)


@pytest.mark.parametrize("path", ["../escape.txt", "folder/../../x.txt", "C:/private.txt", "\\\\host\\share\\x.txt", "/absolute.txt", "file.txt:stream", "missing.txt"])
def test_dataset_paths_cannot_escape_or_reference_missing_files(tmp_path, path):
    with pytest.raises(EvaluationError):
        resolve_document(tmp_path, path)


def test_content_duplicates_and_json_duplicate_keys_are_rejected(manifest):
    path, data = manifest
    (path.parent / "ocean.txt").write_bytes((path.parent / "solar.txt").read_bytes())
    with pytest.raises(EvaluationError, match="duplicate_document_content"):
        check_files(load_dataset(path), path.parent, 20000)
    path.write_text('{"id":"a","id":"b"}')
    with pytest.raises(EvaluationError, match="duplicate_json_key"):
        load_dataset(path)


def test_config_validation_and_test_split_requires_explicit_config(manifest, capsys):
    with pytest.raises(ValidationError):
        RunConfig(chunk_tokens=10, chunk_overlap=10)
    assert main(["--dataset", str(manifest[0]), "--split", "test"]) == 2
    assert "test_split_requires_frozen_config" in capsys.readouterr().err


def test_no_output_overwrite_and_missing_model_fails_without_report(manifest, tmp_path):
    path, _ = manifest
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("TEST DATA preserve")
    with pytest.raises(EvaluationError, match="output_must_be_new"):
        run_evaluation(path, output, RunConfig(), "tuning", tmp_path / "missing")
    assert sentinel.read_text() == "TEST DATA preserve"
    output = tmp_path / "failed"
    from app.retrieval.errors import RetrievalFailure
    with pytest.raises(RetrievalFailure, match="model_unavailable"):
        run_evaluation(path, output, RunConfig(), "tuning", tmp_path / "missing")
    assert json.loads((output / "failure.json").read_text())["code"] == "model_unavailable"
    assert not (output / "report.json").exists()


def test_actual_memory_sampler_and_child_rss(tmp_path):
    ready = tmp_path / "ready"
    code = "from pathlib import Path; import sys,time; data=bytearray(16*1024*1024); Path(sys.argv[1]).write_text('ready'); time.sleep(20)"
    child = subprocess.Popen([sys.executable, "-c", code, str(ready)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        with MemorySampler(0.02) as sampler:
            sampler.mark("TEST DATA")
            sampler.sample()
        report = sampler.report()
        assert report["baseline_parent_rss_bytes"] > 0
        assert report["peak_process_tree_rss_bytes"] > report["peak_parent_rss_bytes"]
        assert report["phases"]["TEST DATA"]["samples"] >= 2
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_memory_sample_keeps_phase_at_start(monkeypatch):
    sampler = MemorySampler(1)
    reading, release = threading.Event(), threading.Event()

    def delayed_read():
        reading.set()
        assert release.wait(5)
        return SimpleNamespace(rss=100)

    monkeypatch.setattr(sampler.process, "memory_info", delayed_read)
    monkeypatch.setattr(sampler.process, "children", lambda **kwargs: [])
    worker = threading.Thread(target=sampler.sample)
    worker.start()
    try:
        assert reading.wait(5)
        with sampler.lock:
            sampler.phase = "indexing"
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert sampler.phases["setup"]["samples"] == 1
    assert "indexing" not in sampler.phases


@pytest.mark.parametrize("primary_failure", [False, True])
def test_final_memory_read_failure_does_not_mask_primary_error(monkeypatch, primary_failure):
    def unreadable():
        raise OSError("TEST DATA PRIVATE process details")

    expected = "document_processing_failed" if primary_failure else "memory_sampling_failed"
    with pytest.raises(EvaluationError, match=expected) as caught:
        with MemorySampler(60) as sampler:
            monkeypatch.setattr(sampler.process, "memory_info", unreadable)
            if primary_failure:
                raise EvaluationError("document_processing_failed")
    if primary_failure:
        assert "memory_sampling_failed" in caught.value.__notes__
    assert not sampler.thread.is_alive()


def test_failure_artifact_write_keeps_original_error(manifest, tmp_path, monkeypatch, caplog):
    from evaluation import run_eval

    def fail_setup(*args):
        raise EvaluationError("document_processing_failed")

    def fail_artifact(*args):
        raise OSError("TEST DATA PRIVATE storage details")

    monkeypatch.setattr(run_eval, "create_sqlite_engine", fail_setup)
    monkeypatch.setattr(run_eval, "write_json", fail_artifact)
    output = tmp_path / "failed-storage"
    with pytest.raises(EvaluationError, match="document_processing_failed"):
        run_evaluation(manifest[0], output, RunConfig(), "tuning", tmp_path / "unit-model")
    assert "failure_artifact_write_failed" in caplog.text
    assert "PRIVATE" not in caplog.text
    assert not (output / "report.json").exists()


def test_query_comparison_does_not_run_heldout_or_average_metrics_per_repeat(manifest):
    dataset = load_dataset(manifest[0])
    calls = []

    class UnitSearch:
        """Deterministic protocol test double, never used by CLI or production."""
        def search(self, request):
            calls.append((request.mode, request.query, request.collection_id))
            return {"indexing_incomplete": False, "results": [{"source_id": 1}]}

    with MemorySampler(0.05) as memory:
        results, _ = evaluate_queries(UnitSearch(), dataset.queries.tuning, {"energy": 7}, {1: "d1"}, RunConfig(repeats=2), memory)
    assert len(calls) == 12
    assert {text for _, text, _ in calls} == {dataset.queries.tuning[0].text}
    assert {collection for _, _, collection in calls} == {7}
    for mode in results:
        assert len(results[mode]["queries"]) == 1
        assert results[mode]["latency"]["samples"] == 2
        assert results[mode]["metrics"]["Precision@5"] == 0.2


def test_real_evaluation_cli_on_tiny_fixture(manifest, tmp_path):
    model = REPO_ROOT / ".local" / "models" / "all-MiniLM-L6-v2"
    if not (model / "echo-model.json").is_file():
        pytest.skip("Provision the offline MiniLM model before the real evaluation integration test")
    output = tmp_path / "TEST DATA report"
    config = tmp_path / "config.json"
    config.write_text(json.dumps(RunConfig(repeats=2).model_dump()), encoding="utf-8")
    # Fresh interpreter gives the indexing measurement a genuinely unloaded model.
    result = subprocess.run([sys.executable, str(REPO_ROOT / "evaluation" / "run_eval.py"),
        "--dataset", str(manifest[0]), "--output", str(output), "--config", str(config), "--model-dir", str(model),
        "--weight-sweep", str(REPO_ROOT / "evaluation" / "weights.example.json")],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=180,
        env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["dataset"]["kind"] == "test_fixture"
    assert "NOT RESEARCH EVIDENCE" in report["dataset"]["evidence"]
    assert report["dataset"]["sources"] == 2
    assert report["dataset"]["chunks"] == report["dataset"]["vectors"] > 0
    assert report["indexing"]["seconds"] > 0
    assert report["memory"]["peak_parent_rss_bytes"] > 0
    assert report["model"]["dimension"] == 384
    assert report["environment"]["code_sha256"]
    assert report["weight_sweep"]["split"] == "tuning"
    assert len(report["weight_sweep"]["settings"]) == 3
    assert len(list((output / "configs").glob("weights-*.json"))) == 3
    for mode in ("keyword", "semantic", "hybrid", "hybrid_contextual"):
        method = report["methods"][mode]
        assert method["queries"][0]["query_id"] == "q_tune"
        assert method["queries"][0]["document_ids"] == ["d1"]
        assert method["latency"]["samples"] == 2
        assert method["latency"]["median_ms"] >= 0
    exported = (output / "report.json").read_text(encoding="utf-8") + (output / "summary.csv").read_text(encoding="utf-8")
    assert "PRIVATE" not in exported + result.stdout + result.stderr
    assert "q_test" not in exported
    assert str(manifest[0]) not in exported + result.stdout + result.stderr


def test_test_split_uses_only_heldout_queries_and_keeps_config_hash(manifest, tmp_path, monkeypatch):
    from evaluation import run_eval
    from test_retrieval import UnitEncoder
    real_search = run_eval.SearchEngine
    monkeypatch.setattr(run_eval, "SearchEngine", lambda *args: real_search(*args, encoder=UnitEncoder()))
    config = RunConfig(repeats=1)
    report = run_evaluation(manifest[0], tmp_path / "heldout", config, "test", tmp_path / "unit-model")
    assert report["dataset"]["split"] == "test"
    from evaluation.dataset import fingerprint
    assert report["config_sha256"] == fingerprint(config.model_dump())
    assert all(row["query_id"] == "q_test" for method in report["methods"].values() for row in method["queries"])


def test_failed_document_aborts_comparison_without_success_report(manifest, tmp_path, monkeypatch):
    from evaluation import run_eval
    from test_retrieval import UnitEncoder
    real_search = run_eval.SearchEngine
    monkeypatch.setattr(run_eval, "SearchEngine", lambda *args: real_search(*args, encoder=UnitEncoder()))
    path, data = manifest
    (path.parent / "broken.pdf").write_bytes(b"%PDF-1.7\nTEST DATA corrupt document")
    data["documents"][1].update(path="broken.pdf", source_type="pdf")
    path.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "failed-import"
    with pytest.raises(EvaluationError, match="document_processing_failed"):
        run_evaluation(path, output, RunConfig(repeats=1), "tuning", tmp_path / "unit-model")
    assert not (output / "report.json").exists()
    assert not (output / "summary.csv").exists()
    assert json.loads((output / "failure.json").read_text())["code"] == "document_processing_failed"


def test_inconsistent_or_changing_results_are_rejected(manifest):
    query = load_dataset(manifest[0]).queries.tuning

    class UnitSearch:
        count = 0

        def search(self, request):
            self.count += 1
            return {"indexing_incomplete": False, "results": [{"source_id": 1 if self.count <= 6 else 2}]}

    with MemorySampler(0.05) as memory, pytest.raises(EvaluationError, match="ranking_changed_between_repeats"):
        evaluate_queries(UnitSearch(), query, {"energy": 7}, {1: "d1", 2: "d2"}, RunConfig(repeats=2), memory)
