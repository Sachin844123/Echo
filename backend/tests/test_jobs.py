"""Durability/race tests with synthetic TEST DATA and real local parser processes."""

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.database.models import Chunk, Document, IndexingJob, Source
from app.ingestion.errors import ImportFailure
from app.ingestion.service import IngestionService
from app.storage.instance_lock import InstanceLock


@pytest.fixture
def service(engine, settings):
    service = IngestionService(engine, settings)
    service.store.prepare()
    return service


def enqueue(service, content=b"TEST DATA persistent job", name="test.txt"):
    staged = service.store.new_stage()
    staged.write_bytes(content)
    return service.enqueue(staged, name, hashlib.sha256(content).hexdigest())


def test_concurrent_duplicate_imports(service, engine):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: enqueue(service), range(8)))
    assert sum(not result["duplicate"] for result in results) == 1
    assert len({result["source_id"] for result in results}) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IndexingJob)) == 1
    assert len(list(service.store.imports.iterdir())) == 1
    assert not list(service.store.staging.iterdir())


def test_running_job_and_orphan_files_recovered(service, engine):
    imported = enqueue(service)
    claimed = service._claim()
    assert claimed == (imported["job_id"], imported["source_id"])
    orphan = service.store.imports / ("f" * 32 + ".txt")
    orphan.write_text("TEST DATA orphan", encoding="utf-8")
    unrelated = service.store.imports / "user-file.txt"
    unrelated.write_text("TEST DATA unrelated", encoding="utf-8")
    service.store.new_stage().write_text("TEST DATA interrupted upload", encoding="utf-8")
    recovered = IngestionService(engine, service.settings)
    recovered.store.prepare()
    recovered.recover()
    assert not orphan.exists()
    assert unrelated.exists()
    assert not list(service.store.staging.iterdir())
    assert recovered.job(imported["job_id"])["status"] == "pending"
    assert recovered.job(imported["job_id"])["attempts"] == 1
    recovered._execute(*recovered._claim())
    result = recovered.job(imported["job_id"])
    assert result["status"] == "succeeded"
    assert result["attempts"] == 2
    assert result["chunk_count"] > 0


def test_exhausted_interrupted_job_is_not_retried_forever(service, engine):
    imported = enqueue(service)
    with Session(engine) as session:
        job = session.get(IndexingJob, imported["job_id"])
        job.status, job.attempts = "running", service.settings.max_job_attempts
        session.commit()
    service.recover()
    result = service.job(imported["job_id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "interrupted"
    assert not result["retryable"]
    with pytest.raises(ImportFailure, match="retry_conflict"):
        service.retry(imported["job_id"])


def test_instance_lock_released_and_excludes_second_owner(tmp_path):
    first, second = InstanceLock(tmp_path / "test.lock"), InstanceLock(tmp_path / "test.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="another ECHO"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


@pytest.mark.parametrize("kind,code", [("missing", "missing_file"), ("changed", "input_changed"), ("traversal", "missing_file")])
def test_stored_input_integrity(service, engine, tmp_path, kind, code):
    imported = enqueue(service)
    with Session(engine) as session:
        source = session.get(Source, imported["source_id"])
        path = service.store.resolve(source.file_path)
        if kind == "missing":
            path.unlink()
        elif kind == "changed":
            path.write_bytes(b"TEST DATA altered")
        else:
            source.file_path = "../outside.txt"
            session.commit()
    service._execute(*service._claim())
    assert service.job(imported["job_id"])["error"]["code"] == code


def test_publication_rollback_and_retry(service, engine, monkeypatch):
    imported = enqueue(service, b"TEST DATA " * 1000)
    from app.ingestion import service as module
    actual = module.iter_chunks

    def fail_mid_insert(*args):
        for index in range(101):
            yield {"chunk_index": index, "chunk_text": "TEST", "token_count": 1,
                   "start_offset": 0, "end_offset": 4, "page_number": None, "heading": None}
        raise RuntimeError("PRIVATE TEST DATA parser failure")

    monkeypatch.setattr(module, "iter_chunks", fail_mid_insert)
    service._execute(*service._claim())
    assert service.job(imported["job_id"])["status"] == "failed"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Chunk)) == 0
        assert session.scalar(select(Document.extracted_text)) == ""
    monkeypatch.setattr(module, "iter_chunks", actual)
    service.retry(imported["job_id"])
    service._execute(*service._claim())
    result = service.job(imported["job_id"])
    assert result["status"] == "succeeded"
    assert result["attempts"] == 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Document)) == 1
    with pytest.raises(ImportFailure, match="retry_conflict"):
        service.retry(imported["job_id"])


def test_queue_limit_and_duplicate_when_full(engine, settings):
    limited = IngestionService(engine, settings.model_copy(update={"max_pending_jobs": 1}))
    limited.store.prepare()
    enqueue(limited)
    assert enqueue(limited)["duplicate"] is True
    with pytest.raises(ImportFailure, match="queue_full"):
        enqueue(limited, b"TEST DATA different")
    assert len(list(limited.store.imports.iterdir())) == 1
    assert not list(limited.store.staging.iterdir())


def test_retry_respects_queue_capacity(engine, settings):
    limited = IngestionService(engine, settings.model_copy(update={"max_pending_jobs": 1}))
    limited.store.prepare()
    first = enqueue(limited)
    with Session(engine) as session:
        job = session.get(IndexingJob, first["job_id"])
        job.status, job.attempts, job.error = "failed", 1, "extraction_failed"
        session.commit()
    enqueue(limited, b"TEST DATA second job")
    with pytest.raises(ImportFailure, match="queue_full"):
        limited.retry(first["job_id"])
    assert limited.job(first["job_id"])["status"] == "failed"


def test_inspection_script_requires_explicit_text_output(service):
    imported = enqueue(service)
    service._execute(*service._claim())
    command = [sys.executable, str(REPO_ROOT / "scripts" / "inspect_chunks.py"), "--source-id", str(imported["source_id"])]
    env = {**os.environ, "ECHO_DATA_DIR": str(service.settings.data_dir)}
    metadata = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
    assert metadata.returncode == 0, metadata.stderr
    assert "TEST DATA" not in metadata.stdout + metadata.stderr
    shown = subprocess.run(command + ["--show-text"], env=env, capture_output=True, text=True, timeout=20)
    assert shown.returncode == 0
    assert "TEST DATA" in json.loads(shown.stdout.splitlines()[0])["text"]
