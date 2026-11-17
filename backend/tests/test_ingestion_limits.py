"""Limits/cancellation tests use synthetic TEST DATA and controlled failures."""

import subprocess
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.requests import ClientDisconnect

from app.api.ingestion import import_file
from app.database.models import Source
from app.extraction.parsers import extract_to_spool
from app.ingestion.service import IngestionService
from app.main import create_app
from app.processing.chunking import iter_chunks, read_segments
from test_ingestion import pdf_bytes, wait_job
from test_jobs import enqueue


def test_streamed_upload_limit_even_with_false_or_absent_length(settings, engine):
    settings = settings.model_copy(update={"max_upload_bytes": 1024})
    auth = {"Authorization": f"Bearer {settings.session_token.get_secret_value()}"}
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        for content, headers in [(b"x" * 2048, {}), (b"x" * 2048, {"Content-Length": "1"}),
                                 (iter([b"x" * 800, b"y" * 800]), {})]:
            response = client.post("/api/v1/imports/files?filename=TEST.txt", content=content, headers={**auth, **headers})
            assert response.status_code == 413
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 0
    assert not list((settings.data_dir / "staging").iterdir())


@pytest.mark.parametrize("limits,content,filename,code", [
    ({"max_extracted_chars": 100}, b"TEST DATA " * 50, "test.txt", "text_limit"),
    ({"max_pdf_pages": 1}, None, "test.pdf", "page_limit"),
])
def test_parser_limits_are_reported(settings, engine, limits, content, filename, code):
    settings = settings.model_copy(update=limits)
    auth = {"Authorization": f"Bearer {settings.session_token.get_secret_value()}"}
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        response = client.post("/api/v1/imports/files", params={"filename": filename}, content=content or pdf_bytes(), headers=auth)
        assert response.status_code == 202
        result = wait_job(client, auth, response.json()["job_id"])
        assert result["error"]["code"] == code
        assert result["chunk_count"] == 0


def test_disconnect_removes_partial_upload(settings, engine):
    import anyio

    async def exercise():
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            messages = iter([{"type": "http.request", "body": b"TEST DATA", "more_body": True},
                             {"type": "http.disconnect"}])

            async def receive():
                return next(messages)

            request = Request({"type": "http", "method": "POST", "path": "/api/v1/imports/files",
                               "headers": [], "app": app}, receive)
            with pytest.raises(ClientDisconnect):
                await import_file(request, "test.txt")
            assert not list(app.state.ingestion.store.staging.iterdir())

    anyio.run(exercise)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 0


def test_timeout_kills_parser_and_persists_safe_error(settings, engine, monkeypatch):
    service = IngestionService(engine, settings)
    service.store.prepare()
    imported = enqueue(service)

    class HungParser:
        killed = False
        returncode = None

        def communicate(self, input=None, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("TEST parser", timeout)
            return "", None

        def kill(self):
            self.killed = True

    parser = HungParser()
    monkeypatch.setenv("ECHO_SESSION_TOKEN", "TEST_SECRET_MUST_NOT_REACH_PARSER")

    def spawn(*args, **kwargs):
        assert "ECHO_SESSION_TOKEN" not in kwargs["env"]
        return parser

    monkeypatch.setattr("app.ingestion.service.subprocess.Popen", spawn)
    service._execute(*service._claim())
    assert parser.killed
    result = service.job(imported["job_id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "extraction_timeout"
    assert service.process is None


def test_shutdown_terminates_active_parser_and_requeues(settings, engine, monkeypatch):
    service = IngestionService(engine, settings)
    entered, terminated = threading.Event(), threading.Event()

    class WaitingParser:
        returncode = None

        def communicate(self, input=None, timeout=None):
            entered.set()
            assert terminated.wait(timeout=5), "shutdown did not terminate parser"
            self.returncode = -1
            return "", None

        def poll(self):
            return self.returncode

        def terminate(self):
            terminated.set()

    monkeypatch.setattr("app.ingestion.service.subprocess.Popen", lambda *a, **k: WaitingParser())
    service.start()
    imported = enqueue(service)
    assert entered.wait(timeout=5)
    service.stop()
    assert terminated.is_set()
    assert not service.thread.is_alive()
    assert service.job(imported["job_id"])["status"] == "pending"
    assert service.job(imported["job_id"])["attempts"] == 1


def test_long_line_preserves_words_and_incremental_chunk_offsets(tmp_path, settings):
    value = "TESTDATA" * 10000 + " end\n" + "fixture " * 10000
    path, output = tmp_path / "long.txt", tmp_path / "result.jsonl"
    path.write_text(value, encoding="utf-8")
    extract_to_spool(path, "txt", output, settings)
    segments = list(read_segments(output))
    text = "\n\n".join(segment.text for segment in segments)
    assert "TESTDATA" * 10000 in text
    chunks = list(iter_chunks(segments))
    assert chunks[-1]["end_offset"] == len(text)
    assert all(text[chunk["start_offset"]:chunk["end_offset"]] == chunk["chunk_text"] for chunk in chunks)
    assert all(0 < chunk["token_count"] <= 350 for chunk in chunks)


def test_markdown_fenced_code_does_not_create_headings(tmp_path, settings):
    path, output = tmp_path / "test.md", tmp_path / "result.jsonl"
    path.write_text("# TEST DATA heading\n```python\n# code comment\n```\n## Next heading\n~~~\n# more code\n~~~\n", encoding="utf-8")
    extract_to_spool(path, "markdown", output, settings)
    assert {segment.heading for segment in read_segments(output)} == {"TEST DATA heading", "Next heading"}


def test_restart_process_reads_pending_job_from_existing_database(settings, engine):
    import os
    import sys
    from app.core.config import REPO_ROOT

    service = IngestionService(engine, settings)
    service.store.prepare()
    imported = enqueue(service)
    # A genuinely new interpreter observes a pending record without an in-memory queue.
    program = """
from app.core.config import Settings
from app.database.engine import create_sqlite_engine
from app.ingestion.service import IngestionService
config = Settings.from_env()
engine = create_sqlite_engine(config.database_path)
worker = IngestionService(engine, config)
worker.instance_lock.acquire()
try:
    worker.recover()
    worker._execute(*worker._claim())
finally:
    worker.instance_lock.release()
    engine.dispose()
"""
    result = subprocess.run([sys.executable, "-c", program], cwd=REPO_ROOT / "backend",
                            env={**os.environ, "ECHO_DATA_DIR": str(settings.data_dir)},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert service.job(imported["job_id"])["status"] == "succeeded"
