"""Actual parser/HTTP integration using small, explicitly synthetic TEST DATA."""

import io
import time

import pymupdf
import pytest
from docx import Document as WordDocument
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import Chunk, Document, IndexingJob, Source


def pdf_bytes(*, blank=False, encrypted=False):
    with pymupdf.open() as document:
        for number in range(2):
            page = document.new_page()
            if not blank:
                page.insert_text((72, 72), f"TEST DATA page {number + 1}: solar panel research fixture.")
        return document.tobytes(**({"encryption": pymupdf.PDF_ENCRYPT_AES_256,
                                   "owner_pw": "TEST OWNER", "user_pw": "TEST PASSWORD"} if encrypted else {}))


def word_bytes():
    document = WordDocument()
    document.add_heading("TEST DATA heading", level=1)
    document.add_paragraph("A synthetic research paragraph for ingestion tests.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "TEST DATA cell alpha"
    table.cell(0, 1).text = "TEST DATA cell beta"
    nested = table.cell(0, 1).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "TEST DATA nested cell"
    document.add_heading("TEST DATA next", level=1)
    document.add_paragraph("Final synthetic paragraph.")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def wait_job(client, auth, job_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/indexing-jobs/{job_id}", headers=auth)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not reach a terminal state")


@pytest.mark.parametrize("kind", ["txt", "md", "docx", "pdf", "note", "utf16"])
def test_real_imports_clean_and_chunk(client, auth, engine, kind):
    if kind == "note":
        response = client.post("/api/v1/imports/notes", headers=auth, json={"title": "TEST DATA note", "text": "TEST DATA note\n\nA manually captured synthetic memory."})
    else:
        contents = {
            "txt": b"TEST DATA\r\n\r\n" + b"synthetic words " * 400,
            "md": b"# TEST DATA heading\n\nFirst synthetic section.\n\n## TEST DATA next\nSecond section.",
            "docx": word_bytes, "pdf": pdf_bytes,
            "utf16": "TEST DATA café हिन्दी".encode("utf-16"),
        }
        content = contents[kind]() if callable(contents[kind]) else contents[kind]
        extension = "txt" if kind == "utf16" else kind
        response = client.post("/api/v1/imports/files", params={"filename": f"TEST DATA.{extension}"}, content=content,
                               headers={**auth, "Content-Type": "application/octet-stream"})
    assert response.status_code == 202, response.text
    imported = response.json()
    result = wait_job(client, auth, imported["job_id"])
    assert result["status"] == "succeeded", result
    assert result["attempts"] == 1
    assert result["chunk_count"] > 0
    assert result["ready_for_indexing"] is True
    with Session(engine) as session:
        source = session.get(Source, imported["source_id"])
        document = session.scalar(select(Document).where(Document.source_id == source.id))
        chunks = session.scalars(select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)).all()
        assert document.extraction_status == "complete"
        assert document.content_length == len(document.extracted_text)
        assert source.indexed_at is None
        # Extraction succeeds independently of the subsequent offline-model index job.
        assert source.processing_status in {"pending", "processing", "failed"}
        assert source.captured_at is not None
        assert source.file_path.startswith("imports/") and "TEST" not in source.file_path
        assert document.language is None
        for chunk in chunks:
            assert document.extracted_text[chunk.start_offset:chunk.end_offset] == chunk.chunk_text
            assert 0 < chunk.token_count <= 350
        if kind == "pdf":
            assert {chunk.page_number for chunk in chunks} == {1, 2}
            assert document.extraction_method == "pymupdf_text"
        elif kind == "docx":
            assert "TEST DATA nested cell" in document.extracted_text
            assert "TEST DATA cell alpha" in document.extracted_text
            assert {chunk.heading for chunk in chunks} == {"TEST DATA heading", "TEST DATA next"}
        elif kind == "md":
            assert {chunk.heading for chunk in chunks} == {"TEST DATA heading", "TEST DATA next"}
        elif kind == "utf16":
            assert "café हिन्दी" in document.extracted_text


def test_duplicate_bytes_do_not_create_another_source_job_or_file(client, auth, engine, settings):
    first = client.post("/api/v1/imports/notes", headers=auth, json={"title": "TEST DATA original", "text": "TEST DATA duplicate"})
    second = client.post("/api/v1/imports/files", headers=auth, params={"filename": "different.txt"}, content=b"TEST DATA duplicate")
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["source_id"] == first.json()["source_id"]
    wait_job(client, auth, first.json()["job_id"])
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 1
        assert session.scalar(select(func.count()).select_from(IndexingJob)) == 2
    assert len(list((settings.data_dir / "imports").iterdir())) == 1
    assert not list((settings.data_dir / "staging").iterdir())


@pytest.mark.parametrize("filename,content,status", [
    ("../escape.txt", b"TEST DATA", 400), ("test.exe", b"MZTEST DATA", 415),
    ("fake.pdf", b"TEST DATA", 415), ("binary.txt", b"\x00\x01\x02", 415),
    ("empty.txt", b"", 422),
])
def test_rejected_imports_leave_no_rows_or_files(client, auth, engine, settings, filename, content, status):
    response = client.post("/api/v1/imports/files", params={"filename": filename}, content=content, headers=auth)
    assert response.status_code == status, response.text
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 0
    assert not list((settings.data_dir / "imports").iterdir())
    assert not list((settings.data_dir / "staging").iterdir())


@pytest.mark.parametrize("body", [{"title": "", "text": "x"}, {"title": "TEST DATA", "text": " "},
                                   {"title": "TEST DATA", "text": "x", "file_path": "outside"},
                                   {"title": "TEST DATA", "text": "x" * 100001}])
def test_invalid_notes_are_redacted(client, auth, body):
    response = client.post("/api/v1/imports/notes", headers=auth, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_note"
    assert "TEST DATA" not in response.text


@pytest.mark.parametrize("kind,code", [("blank", "no_extractable_text"), ("encrypted", "encrypted_pdf"), ("corrupt", "invalid_pdf")])
def test_pdf_failures_are_visible_and_leave_no_chunks(client, auth, engine, kind, code):
    content = b"%PDF-1.7\nTEST DATA corrupted file" if kind == "corrupt" else pdf_bytes(blank=kind == "blank", encrypted=kind == "encrypted")
    response = client.post("/api/v1/imports/files", params={"filename": "TEST DATA.pdf"}, content=content, headers=auth)
    assert response.status_code == 202
    result = wait_job(client, auth, response.json()["job_id"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == code
    assert result["retryable"] is True
    assert result["chunk_count"] == 0
    with Session(engine) as session:
        document = session.scalar(select(Document).where(Document.source_id == result["source_id"]))
        assert document.extraction_status == "failed"
        assert document.extracted_text == ""


def test_retry_attempt_limits_and_status_pagination(client, auth):
    response = client.post("/api/v1/imports/files", params={"filename": "TEST DATA.pdf"}, content=b"%PDF-1.7\nBAD TEST DATA", headers=auth)
    job_id = response.json()["job_id"]
    for attempt in (1, 2, 3):
        result = wait_job(client, auth, job_id)
        assert result["status"] == "failed"
        assert result["attempts"] == attempt
        retried = client.post(f"/api/v1/indexing-jobs/{job_id}/retry", headers=auth)
        assert retried.status_code == (202 if attempt < 3 else 409)
    assert result["retryable"] is False
    listing = client.get("/api/v1/indexing-jobs?limit=1&offset=0", headers=auth).json()
    assert listing["total"] == 1
    assert listing["worker_alive"] is True
    assert listing["items"][0]["id"] == job_id
    assert client.get("/api/v1/indexing-jobs?offset=1", headers=auth).json()["items"] == []
    assert client.get("/api/v1/indexing-jobs/99999", headers=auth).status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/imports/files?filename=test.txt", "/api/v1/imports/notes", "/api/v1/indexing-jobs/1/retry"])
def test_mutation_endpoints_require_auth_and_origin(client, auth, path):
    assert client.post(path, content=b"TEST DATA").status_code == 401
    assert client.post(path, content=b"TEST DATA", headers={**auth, "Origin": "https://evil.example"}).status_code == 403


def test_jobs_require_auth_and_import_cors(client):
    assert client.get("/api/v1/indexing-jobs").status_code == 401
    response = client.options("/api/v1/imports/files", headers={
        "Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
