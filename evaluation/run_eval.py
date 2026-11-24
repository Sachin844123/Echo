"""Compare A=keyword, B=semantic, C=hybrid and D=contextual hybrid on an isolated corpus.

Run from the repository root: python evaluation/run_eval.py --help
No network, fabricated data, implicit retries, model fallback or test-split tuning.
"""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import random
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import psutil
from sqlalchemy import select

from app import __version__
from app.api.search import SearchInput
from app.core.config import Settings
from app.core.logging import configure_logging
from app.database.engine import create_sqlite_engine
from app.database.migrate import upgrade_database
from app.database.models import Chunk, Collection, CollectionItem, EmbeddingRecord, Source
from app.ingestion.errors import ImportFailure
from app.ingestion.service import IngestionService
from app.retrieval.engine import SearchEngine
from app.retrieval.errors import RetrievalFailure
from app.retrieval.reranking import RERANK_VERSION
from evaluation.dataset import EvaluationError, RunConfig, fingerprint, load_config, load_dataset, resolve_document
from evaluation.metrics import latency_summary, macro_average, ranking_metrics
from evaluation.resources import MemorySampler
from evaluation.sweep import WeightSweep, load_sweep

METHODS = ("keyword", "semantic", "hybrid", "hybrid_contextual")
METHOD_IDS = {"keyword": "A", "semantic": "B", "hybrid": "C", "hybrid_contextual": "D"}


def check_files(dataset, root, maximum):
    files, seen = {}, set()
    for document in dataset.documents:
        path = resolve_document(root, document.path)
        if not 0 < path.stat().st_size <= maximum:
            raise EvaluationError("document_size_invalid")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest in seen:
            raise EvaluationError("duplicate_document_content")
        seen.add(digest)
        files[document.id] = (path, digest)
    return files


def import_document(service, document, path, expected_digest, collection_ids, timeout):
    started = time.perf_counter()
    staged = service.store.new_stage()
    try:
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as source, staged.open("xb") as target:
            while block := source.read(1024 * 1024):
                size += len(block)
                if size > service.settings.max_upload_bytes:
                    raise EvaluationError("document_size_invalid")
                target.write(block)
                digest.update(block)
            target.flush()
            os.fsync(target.fileno())
        if digest.hexdigest() != expected_digest:
            raise EvaluationError("document_changed_during_run")
        with service.mutation_lock:
            result = service.enqueue(staged, path.name, expected_digest,
                                     document.title if document.source_type == "note" else None)
            if result["duplicate"]:
                raise EvaluationError("unexpected_duplicate_import")
            with service.sessions.begin() as session:
                imported = session.get(Source, result["source_id"])
                if imported.source_type != document.source_type:
                    raise EvaluationError("declared_source_type_mismatch")
                imported.title, imported.captured_at = document.title, document.captured_at
                for name in set(document.collections):
                    session.add(CollectionItem(collection_id=collection_ids[name], source_id=imported.id))
        while time.perf_counter() - started <= timeout:
            with service.sessions() as session:
                status = session.get(Source, result["source_id"]).processing_status
            if status == "failed":
                raise EvaluationError("document_processing_failed")
            if status == "indexed":
                return result["source_id"], time.perf_counter() - started
            if service.thread is None or not service.thread.is_alive():
                raise EvaluationError("indexing_worker_stopped")
            time.sleep(0.02)
        raise EvaluationError("indexing_deadline_exceeded")
    finally:
        staged.unlink(missing_ok=True)


def ensure_complete(search, expected_sources):
    with search.lock, search.sessions() as session:
        actual = set(session.scalars(select(Source.id)))
        chunks = set(session.scalars(select(Chunk.id)))
        embeddings = set(session.scalars(select(EmbeddingRecord.chunk_id)))
        fts = set(session.connection().exec_driver_sql("SELECT rowid FROM chunk_fts").scalars())
        if (actual != expected_sources or not chunks or chunks != embeddings or chunks != fts
                or chunks != search.vectors.ids or search.status()["indexing_incomplete"]):
            raise EvaluationError("incomplete_or_inconsistent_index")
        return {"sources": len(actual), "chunks": len(chunks), "vectors": len(embeddings)}


def evaluate_queries(search, queries, collections, source_to_document, config, memory, methods=METHODS):
    requests = {query.id: SearchInput(query=query.text, limit=10,
        source_types=query.filters.source_types, captured_from=query.filters.captured_from,
        captured_to=query.filters.captured_to,
        collection_id=collections.get(query.filters.collection),
        context={"source_types": query.context.source_types, "collection_id": collections.get(query.context.collection)}) for query in queries}
    rng = random.Random(config.seed)
    latencies = {mode: [] for mode in methods}
    observations = {mode: {} for mode in methods}

    def search_once(query, mode):
        request = requests[query.id].model_copy(update={"mode": mode})
        before = time.perf_counter()
        response = search.search(request)
        elapsed = time.perf_counter() - before
        if response["indexing_incomplete"]:
            raise EvaluationError("index_changed_during_queries")
        ids = [source_to_document[result["source_id"]] for result in response["results"]]
        if len(set(ids)) != len(ids):
            raise EvaluationError("duplicate_result_source")
        return ids, elapsed

    memory.mark("warmup")
    warmup_start = time.perf_counter()
    for _ in range(config.warmups):
        for query in queries:
            for mode in methods:
                search_once(query, mode)
    warmup_seconds = time.perf_counter() - warmup_start

    for repeat in range(config.repeats):
        order = list(queries)
        rng.shuffle(order)
        for number, query in enumerate(order):
            # Rotate the first method, balancing systematic cache/thermal order effects.
            offset = (repeat + number) % len(methods)
            for mode in methods[offset:] + methods[:offset]:
                memory.mark(mode)
                ids, elapsed = search_once(query, mode)
                latencies[mode].append(elapsed)
                prior = observations[mode].get(query.id)
                if prior is not None and prior["document_ids"] != ids:
                    raise EvaluationError("ranking_changed_between_repeats")
                if prior is None:
                    observations[mode][query.id] = {"query_id": query.id, "document_ids": ids,
                        "metrics": ranking_metrics(ids, query.relevance), "latency_ms": []}
                observations[mode][query.id]["latency_ms"].append(elapsed * 1000)
                memory.sample()
    results = {}
    for mode in methods:
        rows = [observations[mode][query.id] for query in queries]
        results[mode] = {"method_id": METHOD_IDS[mode], "metrics": macro_average([row["metrics"] for row in rows]),
                         "latency": latency_summary(latencies[mode]), "queries": rows}
    return results, warmup_seconds


def evaluate_weight_sweep(search, dataset, collections, source_to_document, config, memory, sweep, *, split):
    if split != "tuning":
        raise EvaluationError("weight_sweep_requires_tuning_split")
    original = search.settings
    reports = []
    settings = list(sweep.settings)
    random.Random(config.seed).shuffle(settings)
    try:
        for setting in settings:
            search.settings = original.model_copy(update={"rerank_weights": setting.weights})
            effective = config.model_copy(update={"rerank_weights": setting.weights})
            result, warmup = evaluate_queries(search, dataset.queries.tuning, collections, source_to_document,
                                             effective, memory, methods=("hybrid_contextual",))
            reports.append({"id": setting.id, "weights": setting.weights.model_dump(),
                "config": effective.model_dump(), "config_sha256": fingerprint(effective.model_dump()),
                "warmup_seconds": warmup, "result": result["hybrid_contextual"]})
    finally:
        search.settings = original
    return {"split": "tuning", "grid_sha256": fingerprint(sweep.model_dump()),
            "execution_order": [setting.id for setting in settings], "selection": "none; choose using tuning evidence only",
            "settings": reports}


def environment():
    versions = {name: importlib.metadata.version(name) for name in (
        "faiss-cpu", "sentence-transformers", "torch", "transformers", "numpy", "psutil",
        "SQLAlchemy", "pydantic", "PyMuPDF", "python-docx")}
    revision, dirty = None, None
    try:
        options = {"cwd": ROOT, "capture_output": True, "text": True, "timeout": 10,
                   "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0}
        result = subprocess.run(["git", "rev-parse", "HEAD"], **options)
        if result.returncode == 0:
            revision = result.stdout.strip()
            status = subprocess.run(["git", "status", "--porcelain"], **options)
            dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        pass  # Explicit null provenance is preferable to inventing a Git revision.
    code = hashlib.sha256()
    for directory in (ROOT / "backend" / "app", ROOT / "evaluation"):
        for path in sorted(directory.rglob("*.py")):
            if "datasets" in path.relative_to(directory).parts:
                continue
            code.update(path.relative_to(ROOT).as_posix().encode())
            code.update(path.read_bytes())
    return {"echo_version": __version__, "python": platform.python_version(), "os": platform.system(),
            "os_release": platform.release(), "architecture": platform.machine(), "logical_cpu_count": os.cpu_count(),
            "physical_cpu_count": psutil.cpu_count(logical=False), "system_memory_bytes": psutil.virtual_memory().total,
            "sqlite": sqlite3.sqlite_version, "packages": versions, "git_revision": revision,
            "git_dirty": dirty, "code_sha256": code.hexdigest()}


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def run_evaluation(dataset_path: Path, output: Path, config: RunConfig, split: str, model_dir: Path, sweep: WeightSweep | None = None):
    if sweep is not None and split != "tuning":
        raise EvaluationError("weight_sweep_requires_tuning_split")
    if split not in {"tuning", "test"}:
        raise EvaluationError("invalid_split")
    dataset_path, output, model_dir = dataset_path.resolve(), output.resolve(), model_dir.resolve()
    dataset = load_dataset(dataset_path)
    settings = Settings(data_dir=output / "corpus", embedding_model_dir=model_dir, visual_indexing_enabled=False,
                        **{key: value for key, value in config.model_dump().items() if key in Settings.model_fields})
    files = check_files(dataset, dataset_path.parent, settings.max_upload_bytes)
    if output.is_relative_to(model_dir):
        raise EvaluationError("output_overlaps_model")
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise EvaluationError("output_must_be_new") from None
    engine, service = None, None
    try:
        with MemorySampler(config.memory_sample_ms / 1000) as memory:
            settings.data_dir.mkdir()
            engine = create_sqlite_engine(settings.database_path)
            upgrade_database(engine)
            service = IngestionService(engine, settings)
            search = SearchEngine(engine, settings, service.mutation_lock, service.store)
            service.indexer = search
            service.start()
            # Reject model absence/mismatch before importing any documents.
            identity = search.encoder.identity
            if not search.status()["semantic_available"]:
                raise EvaluationError("semantic_index_unavailable")
            memory.mark("indexing")
            indexing_start = time.perf_counter()
            collections, source_to_document, indexing_rows = {}, {}, []
            with service.mutation_lock, service.sessions.begin() as session:
                for name in sorted({name for doc in dataset.documents for name in doc.collections}):
                    collection = Collection(name=name)
                    session.add(collection)
                    session.flush()
                    collections[name] = collection.id
            for document in dataset.documents:
                path, digest = files[document.id]
                source_id, seconds = import_document(service, document, path, digest, collections, config.job_timeout_seconds)
                source_to_document[source_id] = document.id
                indexing_rows.append({"document_id": document.id, "seconds": seconds})
            indexing_seconds = time.perf_counter() - indexing_start
            counts = ensure_complete(search, set(source_to_document))
            queries = getattr(dataset.queries, split)
            methods, warmup_seconds = evaluate_queries(search, queries, collections, source_to_document, config, memory)
            sweep_report = None
            if sweep is not None:
                sweep_report = evaluate_weight_sweep(search, dataset, collections, source_to_document, config, memory, sweep, split=split)
            ensure_complete(search, set(source_to_document))
            memory.mark("shutdown")
            service.stop()
            service = None
            engine.dispose()
            engine = None
        selected = [query.model_dump(mode="json") for query in queries]
        report = {"report_version": 2, "status": "complete", "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset": {"id": dataset.id, "kind": dataset.kind,
                "evidence": "TEST DATA ONLY — NOT RESEARCH EVIDENCE" if dataset.kind == "test_fixture" else "user_supplied_labels",
                "manifest_sha256": fingerprint(dataset.model_dump(mode="json")),
                "corpus_sha256": fingerprint([{**doc.model_dump(mode="json"), "sha256": files[doc.id][1]} for doc in dataset.documents]),
                "split": split, "selected_queries_sha256": fingerprint(selected), "query_count": len(queries), **counts},
            "config": config.model_dump(), "config_sha256": fingerprint(config.model_dump()),
            "backend_limits": {name: getattr(settings, name) for name in ("max_upload_bytes", "max_extracted_chars",
                "max_pdf_pages", "max_docx_expanded_bytes", "extraction_timeout_seconds")},
            "model": {"name": identity.name, "version": identity.version, "dimension": identity.dimension},
            "environment": environment(),
            "protocol": {"retrieved_depth": 10, "MRR_cutoff": 10, "relevance_unit": "source",
                "reranker_version": RERANK_VERSION,
                "context_usage": "Only method D uses explicit soft context hints; all methods share query text and hard filters.",
                "unjudged": "nonrelevant", "aggregation": "macro query average",
                "ndcg_gain": "2**grade-1", "latency_percentile": "nearest-rank p95",
                "latency_scope": "warm in-process search including query embedding and grouping; excludes HTTP and JSON serialization",
                "indexing_scope": "staging, validation, extraction, chunks, FTS, first model load, embeddings, FAISS persistence and completion polling",
                "indexing_excludes": "manifest/file preflight, database setup and model-file fingerprint validation",
                "warmups_per_query_method": config.warmups, "warmup_seconds": warmup_seconds,
                "repeats_per_query_method": config.repeats, "order": "seeded query shuffle and rotated method order"},
            "indexing": {"seconds": indexing_seconds, "documents": indexing_rows},
            "memory": memory.report(), "methods": methods, "weight_sweep": sweep_report}
        if sweep_report is not None:
            config_directory = output / "configs"
            config_directory.mkdir()
            with (output / "weight-sweep.csv").open("x", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["dataset_kind", "split", "setting", *config.rerank_weights.model_dump(),
                    "Precision@5", "Recall@5", "MRR@10", "NDCG@10", "median_ms", "p95_ms", "latency_samples"])
                for setting in sweep_report["settings"]:
                    # Prefix prevents Windows device names such as CON.json.
                    write_json(config_directory / f'weights-{setting["id"]}.json', setting["config"])
                    result = setting["result"]
                    writer.writerow([dataset.kind, "tuning", setting["id"], *setting["weights"].values(),
                        *result["metrics"].values(), result["latency"]["median_ms"], result["latency"]["p95_ms"], result["latency"]["samples"]])
        # Summary first; report.json is the completion marker published last.
        with (output / "summary.csv").open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["dataset_kind", "split", "method", "Precision@5", "Recall@5", "MRR@10", "NDCG@10", "median_ms", "p95_ms", "latency_samples"])
            for mode in METHODS:
                result = methods[mode]
                writer.writerow([dataset.kind, split, mode, *result["metrics"].values(), result["latency"]["median_ms"],
                                 result["latency"]["p95_ms"], result["latency"]["samples"]])
        write_json(output / "report.json", report)
        return report
    except BaseException as error:
        code = str(error) if isinstance(error, EvaluationError) else error.code if isinstance(error, (RetrievalFailure, ImportFailure)) else "evaluation_failed"
        try:
            write_json(output / "failure.json", {"status": "failed", "code": code})
        except OSError:
            # Disk/permission failures must not replace the original failure code.
            logging.getLogger(__name__).error("failure_artifact_write_failed")
        raise
    finally:
        if service is not None:
            service.stop()
        if engine is not None:
            engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Local labelled dataset JSON")
    parser.add_argument("--split", choices=("tuning", "test"), default="tuning")
    parser.add_argument("--config", type=Path, help="Frozen run configuration; required for final test split")
    parser.add_argument("--weight-sweep", type=Path, help="Explicit weight settings; allowed only on the tuning split")
    parser.add_argument("--model-dir", type=Path, default=Settings().embedding_model_dir)
    parser.add_argument("--output", type=Path, help="New private run directory; defaults under .local/evaluation")
    args = parser.parse_args(argv)
    configure_logging("ERROR")
    if args.weight_sweep is not None and args.split != "tuning":
        print('{"status":"failed","code":"weight_sweep_requires_tuning_split"}', file=sys.stderr)
        return 2
    if args.split == "test" and args.config is None:
        print('{"status":"failed","code":"test_split_requires_frozen_config"}', file=sys.stderr)
        return 2
    output = args.output or ROOT / ".local" / "evaluation" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    try:
        report = run_evaluation(args.dataset, output, load_config(args.config), args.split, args.model_dir, load_sweep(args.weight_sweep))
        print(json.dumps({"status": "complete", "kind": report["dataset"]["kind"], "split": args.split,
                          "queries": report["dataset"]["query_count"], "methods": list(METHODS)}))
        return 0
    except (EvaluationError, RetrievalFailure, ImportFailure) as error:
        code = str(error) if isinstance(error, EvaluationError) else error.code
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        return 2
    except Exception:
        print('{"status":"failed","code":"evaluation_failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
