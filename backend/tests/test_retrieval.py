"""Tiny synthetic TEST DATA and deterministic unit vectors; not research evidence."""

import json
import threading
from datetime import datetime, timezone

import numpy as np
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.search import SearchInput
from app.database.fts import reconcile_fts
from app.database.models import Chunk, Collection, CollectionItem, Document, EmbeddingRecord, IndexingJob, Source
from app.embeddings.local import ModelIdentity
from app.retrieval.engine import SearchEngine, reciprocal_rank_fusion
from app.retrieval.errors import RetrievalFailure
from app.retrieval.vectors import VectorStore
from app.storage.files import FileStore


class UnitEncoder:
    """Only for deterministic fault/ordering tests. Production always uses LocalEncoder."""
    identity = ModelIdentity("TEST MODEL", "TEST VERSION", 3)

    def encode(self, texts):
        rows = []
        for value in texts:
            vector = np.array([1 + value.lower().count("solar"), 1 + value.lower().count("ocean"), 1], dtype="float32")
            rows.append(vector / np.linalg.norm(vector))
        return np.array(rows)


@pytest.fixture
def searcher(engine, settings):
    files = FileStore(settings.data_dir)
    files.prepare()
    search = SearchEngine(engine, settings, threading.RLock(), files, UnitEncoder())
    search.reconcile()
    return search


def add_source(engine, number, texts=None, **changes):
    texts = texts or [f"TEST DATA solar fixture {number}"]
    with Session(engine) as session:
        source = Source(source_type="note", title=f"TEST DATA title {number}", mime_type="text/plain",
                        content_hash=f"{number:064x}", **changes)
        session.add(source)
        session.flush()
        document = Document(source_id=source.id, extracted_text="\n\n".join(texts), content_length=len("\n\n".join(texts)),
                            extraction_status="complete", extraction_method="TEST DATA")
        session.add(document)
        session.flush()
        offset = 0
        for i, value in enumerate(texts):
            session.add(Chunk(document_id=document.id, chunk_index=i, chunk_text=value, token_count=len(value.split()),
                              start_offset=offset, end_offset=offset + len(value)))
            offset += len(value) + 2
        job = IndexingJob(source_id=source.id, stage="indexing", status="running", attempts=1)
        session.add(job)
        session.commit()
        return source.id, job.id


def indexed(searcher, number, texts=None, **changes):
    source, job = add_source(searcher.engine, number, texts, **changes)
    searcher.index_source(job, source, threading.Event())
    with searcher.sessions() as session:
        assert session.get(IndexingJob, job).status == "succeeded"
    return source


def test_rrf_uses_ranks_not_raw_scores():
    actual = reciprocal_rank_fusion([(1, -99999), (2, -0.0001)], [(2, 0.99), (3, -0.9)])
    assert actual[0] == (2, 1 / 62 + 1 / 61)
    assert dict(actual)[1] == 1 / 61
    assert reciprocal_rank_fusion([(1, -1)], [(2, 1)]) == [(1, 1 / 61), (2, 1 / 61)]


def test_vectors_persist_delete_unicode_paths_ties_and_checksum(tmp_path):
    store = VectorStore(tmp_path / "TEST DATA हिन्दी")
    store.reset(UnitEncoder.identity)
    store.add([3, 1, 2], np.array([[1, 0, 0]] * 3, dtype="float32"))
    store.save()
    loaded = VectorStore(store.root)
    loaded.load()
    assert loaded.identity == UnitEncoder.identity
    assert loaded.search(np.array([[1, 0, 0]], dtype="float32"), {1, 2, 3}, 2) == [(1, 1.0), (2, 1.0)]
    loaded.remove({1})
    loaded.save()
    loaded.load()
    assert loaded.ids == {2, 3}
    assert len(list(store.root.glob("*.faiss"))) == 1
    manifest = json.loads((store.root / "manifest.json").read_text())
    (store.root / manifest["file"]).write_bytes(b"TEST DATA corrupted index")
    loaded.load()
    assert loaded.corrupt and loaded.index is None


def test_fts_triggers_changes_cascades_and_repair(engine):
    source, _ = add_source(engine, 1)
    with engine.begin() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH 'solar'").scalar() == 1
        connection.exec_driver_sql("UPDATE sources SET title='TEST DATA quasar'")
        assert connection.exec_driver_sql("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH 'quasar'").scalar() == 1
        connection.exec_driver_sql("UPDATE chunks SET heading='TEST DATA orbit', chunk_text='TEST DATA comet'")
        assert connection.exec_driver_sql("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH 'orbit'").scalar() == 1
        assert connection.exec_driver_sql("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH 'solar'").scalar() == 0
        connection.exec_driver_sql("DROP TRIGGER chunks_fts_ai")
        connection.exec_driver_sql("DELETE FROM chunk_fts")
        assert reconcile_fts(connection)
        assert not reconcile_fts(connection)
        assert connection.exec_driver_sql("SELECT count(*) FROM chunk_fts WHERE chunk_fts MATCH 'comet'").scalar() == 1
        connection.execute(delete(Source).where(Source.id == source))
        assert connection.exec_driver_sql("SELECT count(*) FROM chunk_fts").scalar() == 0


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
def test_modes_group_sources_excerpts_and_filters(searcher, mode):
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    solar = indexed(searcher, 1, ["TEST DATA solar solar solar", "TEST DATA solar second excerpt"], captured_at=old)
    indexed(searcher, 2, ["TEST DATA ocean ocean"])
    response = searcher.search(SearchInput(query="solar", mode=mode))
    assert response["results"][0]["source_id"] == solar
    assert len({r["source_id"] for r in response["results"]}) == len(response["results"])
    assert response["results"][0]["excerpt"].startswith("TEST DATA solar")
    assert not response["indexing_incomplete"]
    assert searcher.search(SearchInput(query="solar", mode=mode, source_types=["pdf"]))["results"] == []
    only = searcher.search(SearchInput(query="solar", mode=mode, captured_to=old))["results"]
    assert [r["source_id"] for r in only] == [solar]
    with searcher.sessions.begin() as session:
        collection = Collection(name="TEST DATA collection")
        session.add(collection)
        session.flush()
        collection_id = collection.id
        session.add(CollectionItem(collection_id=collection_id, source_id=solar))
    only = searcher.search(SearchInput(query="solar", mode=mode, collection_id=collection_id))["results"]
    assert [r["source_id"] for r in only] == [solar]


def test_filter_before_candidate_cutoff(searcher):
    ids = []
    for number in range(1, 13):
        ids.append(indexed(searcher, number))
    with searcher.sessions.begin() as session:
        collection = Collection(name="TEST DATA selective filter")
        session.add(collection)
        session.flush()
        collection_id = collection.id
        session.add(CollectionItem(collection_id=collection_id, source_id=ids[-1]))
    searcher.settings = searcher.settings.model_copy(update={"candidate_pool": 10})
    for mode in ("keyword", "semantic", "hybrid"):
        results = searcher.search(SearchInput(query="solar", mode=mode, collection_id=collection_id))["results"]
        assert [row["source_id"] for row in results] == [ids[-1]]


def test_keyword_syntax_is_literal_and_mismatch_refuses_semantics(searcher):
    indexed(searcher, 1)
    for value in ('" OR * - : NEAR(', "'; DROP TABLE sources;--", "💡"):
        searcher.search(SearchInput(query=value, mode="keyword"))
    searcher.encoder.identity = ModelIdentity("DIFFERENT TEST MODEL", "v2", 3)
    for mode in ("semantic", "hybrid"):
        with pytest.raises(RetrievalFailure, match="model_mismatch"):
            searcher.search(SearchInput(query="solar", mode=mode))
    assert searcher.search(SearchInput(query="solar", mode="keyword"))["results"]


def test_index_failure_retains_extraction_and_reports_failure(searcher, monkeypatch):
    source, job = add_source(searcher.engine, 1)

    def fail(texts):
        raise OSError("TEST DATA private error")
    monkeypatch.setattr(searcher.encoder, "encode", fail)
    searcher.index_source(job, source, threading.Event())
    with searcher.sessions() as session:
        assert session.get(IndexingJob, job).error == "indexing_failed"
        assert session.scalar(select(func.count()).select_from(Chunk)) == 1
        assert session.scalar(select(func.count()).select_from(EmbeddingRecord)) == 0
    assert searcher.search(SearchInput(query="solar", mode="keyword"))["results"]


def test_reconciliation_removes_orphans_and_requeues_drift(searcher):
    source = indexed(searcher, 1)
    searcher.vectors.add([9999], np.array([[1, 0, 0]], dtype="float32"))
    searcher.vectors.save()
    with searcher.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE chunks SET chunk_text='TEST DATA changed ocean'")
        connection.exec_driver_sql("DELETE FROM chunk_fts")
    searcher.reconcile()
    assert not searcher.vectors.ids
    with searcher.sessions() as session:
        jobs = session.scalars(select(IndexingJob).where(IndexingJob.status == "pending")).all()
        assert len(jobs) == 1 and jobs[0].source_id == source
        job = jobs[0].id
    searcher.index_source(job, source, threading.Event())
    searcher.reconcile()
    assert len(searcher.vectors.ids) == 1
    assert searcher.search(SearchInput(query="ocean", mode="hybrid"))["results"]


def test_corrupt_index_rebuilds_from_durable_chunks(searcher):
    indexed(searcher, 1)
    (searcher.vectors.root / "manifest.json").write_text("TEST DATA corrupt")
    searcher.reconcile()
    assert not searcher.vectors.ids
    with searcher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EmbeddingRecord)) == 0
        assert session.scalar(select(func.count()).select_from(IndexingJob).where(IndexingJob.status == "pending")) == 1


def test_deletion_tombstone_survives_file_failure_and_restart(searcher, monkeypatch):
    source = indexed(searcher, 1)
    staged = searcher.files.new_stage()
    staged.write_text("TEST DATA stored file")
    relative = searcher.files.adopt(staged, "note")
    with searcher.sessions.begin() as session:
        session.get(Source, source).file_path = relative
    real_remove = searcher.files.remove

    def locked(path):
        raise PermissionError("TEST DATA locked file")
    monkeypatch.setattr(searcher.files, "remove", locked)
    assert not searcher.delete_source(source)
    assert not searcher.search(SearchInput(query="solar", mode="keyword"))["results"]
    assert searcher.status()["deletions_pending"] == 1
    monkeypatch.setattr(searcher.files, "remove", real_remove)
    searcher.reconcile()
    assert not searcher.files.resolve(relative).exists()
    assert not searcher.vectors.ids
    with searcher.sessions() as session:
        for model in (Source, Document, Chunk, IndexingJob, EmbeddingRecord):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with searcher.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM chunk_fts").scalar() == 0


def test_rebuild_explicitly_accepts_new_model(searcher):
    indexed(searcher, 1)
    searcher.encoder.identity = ModelIdentity("TEST MODEL", "NEW TEST VERSION", 3)
    searcher.reconcile()
    assert searcher.status()["error"] == "model_mismatch"
    searcher.rebuild()
    assert searcher.vectors.identity.version == "NEW TEST VERSION"
    with searcher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(IndexingJob).where(IndexingJob.status == "pending")) == 1


def test_snapshot_failure_rolls_back_metadata_and_explicit_retry_succeeds(searcher, monkeypatch):
    source, job = add_source(searcher.engine, 1)
    real_save = searcher.vectors.save

    def fail():
        raise OSError("TEST DATA disk full")
    monkeypatch.setattr(searcher.vectors, "save", fail)
    searcher.index_source(job, source, threading.Event())
    with searcher.sessions() as session:
        assert session.get(IndexingJob, job).status == "failed"
        assert session.scalar(select(func.count()).select_from(EmbeddingRecord)) == 0
    assert not searcher.vectors.ids
    monkeypatch.setattr(searcher.vectors, "save", real_save)
    searcher.reconcile()
    with searcher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(IndexingJob)) == 1  # no unbounded retry loop
    searcher.index_source(job, source, threading.Event())
    assert searcher.vectors.ids


def test_crash_between_snapshot_and_metadata_requeues_and_prunes(searcher):
    source = indexed(searcher, 1)
    with searcher.sessions.begin() as session:
        session.execute(delete(EmbeddingRecord))
    # Emulate persisted FAISS bytes whose SQLite transaction never committed.
    searcher.reconcile()
    assert not searcher.vectors.ids
    with searcher.sessions() as session:
        assert session.scalar(select(IndexingJob.source_id).where(IndexingJob.status == "pending")) == source


def test_corrupt_snapshot_deletion_needs_no_model(searcher):
    source = indexed(searcher, 1)
    (searcher.vectors.root / "manifest.json").write_text("TEST DATA corrupted")
    searcher.vectors.load()
    from app.embeddings.local import LocalEncoder
    searcher.encoder = LocalEncoder(searcher.settings)
    assert searcher.delete_source(source)
    assert not list(searcher.vectors.root.glob("*.faiss"))


def test_deleted_source_cannot_be_republished(searcher):
    from app.ingestion.service import IngestionService
    source, job = add_source(searcher.engine, 1)
    owner = IngestionService(searcher.engine, searcher.settings)
    owner.store.prepare()
    spool = owner.store.new_stage("jsonl")
    spool.write_text(json.dumps({"text": "TEST DATA late parser output", "page_number": None, "heading": None}) + "\n")
    assert searcher.delete_source(source)
    owner._publish(job, source, spool, "TEST DATA")
    owner._failed(job, source, "extraction_failed")
    with searcher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 0
        assert session.scalar(select(func.count()).select_from(Chunk)) == 0
