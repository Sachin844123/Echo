"""M3 HTTP tests with explicitly synthetic TEST DATA; no relevance benchmarks."""

import time

import pytest
from sqlalchemy import select

from app.database.models import IndexingJob
from test_ingestion import wait_job


def import_note(client, auth):
    response = client.post("/api/v1/imports/notes", headers=auth, json={
        "title": "TEST DATA solar note", "text": "TEST DATA solar batteries and rooftop electricity."})
    assert response.status_code == 202
    result = response.json()
    assert wait_job(client, auth, result["job_id"])["status"] == "succeeded"
    return result["source_id"]


def test_keyword_available_without_model_and_index_job_error(client, auth, app):
    source = import_note(client, auth)
    with app.state.search.sessions() as session:
        indexing = session.scalar(select(IndexingJob.id).where(IndexingJob.source_id == source, IndexingJob.stage == "indexing"))
    job = wait_job(client, auth, indexing)
    assert job["stage"] == "indexing" and job["status"] == "failed"
    assert job["error"]["code"] == "model_unavailable"
    assert job["chunk_count"] > 0
    result = client.post("/api/v1/search", headers=auth, json={"query": "solar", "mode": "keyword"})
    assert result.status_code == 200, result.text
    assert result.json()["results"][0]["source_id"] == source
    assert result.json()["indexing_incomplete"]
    for mode in ("semantic", "hybrid"):
        response = client.post("/api/v1/search", headers=auth, json={"query": "TEST DATA PRIVATE QUERY", "mode": mode})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "model_unavailable"
        assert "PRIVATE" not in response.text
    status = client.get("/api/v1/index/status", headers=auth).json()
    assert not status["semantic_available"]
    assert client.post(f"/api/v1/indexing-jobs/{indexing}/retry", headers=auth).status_code == 202
    assert wait_job(client, auth, indexing)["attempts"] == 2


def test_source_collection_preview_rename_and_delete(client, auth, settings):
    source = import_note(client, auth)
    base = f"/api/v1/sources/{source}"
    assert client.get("/api/v1/sources", headers=auth).json()["total"] == 1
    detail = client.get(base, headers=auth).json()
    assert "file_path" not in detail and "content_hash" not in detail
    preview = client.get(base + "/document?length=9", headers=auth).json()
    assert preview["text"] == "TEST DATA" and preview["has_more"]
    assert client.get(base + "/chunks", headers=auth).json()["items"][0]["chunk_text"].startswith("TEST DATA")
    assert client.patch(base, headers=auth, json={"title": "TEST DATA renamed quasar"}).status_code == 200
    result = client.post("/api/v1/search", headers=auth, json={"query": "quasar", "mode": "keyword"}).json()
    assert result["results"][0]["source_id"] == source
    collection = client.post("/api/v1/collections", headers=auth, json={"name": "TEST DATA group"})
    assert collection.status_code == 201
    group = collection.json()["id"]
    assert client.post("/api/v1/collections", headers=auth, json={"name": "TEST DATA group"}).status_code == 409
    member = f"/api/v1/collections/{group}/sources/{source}"
    for _ in range(2):
        assert client.put(member, headers=auth).status_code == 200
    assert client.get("/api/v1/collections", headers=auth).json()["total"] == 1
    assert client.post("/api/v1/search", headers=auth, json={"query": "solar", "mode": "keyword", "collection_id": group}).json()["results"]
    assert client.delete(member, headers=auth).status_code == 200
    assert not client.post("/api/v1/search", headers=auth, json={"query": "solar", "mode": "keyword", "collection_id": group}).json()["results"]
    assert client.delete(f"/api/v1/collections/{group}", headers=auth).status_code == 200
    assert client.delete(base, headers=auth).status_code == 200
    assert client.get(base, headers=auth).status_code == 404
    assert client.get("/api/v1/indexing-jobs", headers=auth).json()["total"] == 0
    assert not list((settings.data_dir / "imports").iterdir())


@pytest.mark.parametrize("body", [
    {"query": " "}, {"query": "x", "mode": "rerank"}, {"query": "x", "limit": 0},
    {"query": "x", "captured_from": "2020-01-01"}, {"query": "x", "source_types": ["webpage"]},
    {"query": "x", "captured_from": "2021-01-01T00:00:00Z", "captured_to": "2020-01-01T00:00:00Z"},
    {"query": "x", "collection_id": -1}, {"query": "x", "unknown": "TEST DATA SECRET"},
])
def test_invalid_search_redacts_input(client, auth, body):
    response = client.post("/api/v1/search", headers=auth, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "SECRET" not in response.text


def test_search_body_limits_and_security(client, auth):
    assert client.post("/api/v1/search", headers=auth, content=b"TEST DATA").status_code == 415
    assert client.post("/api/v1/search", headers={**auth, "Content-Type": "application/json"}, content=b"x" * 16385).status_code == 413
    for method, path in (("post", "/search"), ("get", "/sources"), ("delete", "/sources/1"),
                         ("patch", "/sources/1"), ("post", "/collections"), ("get", "/index/status"),
                         ("put", "/collections/1/sources/1")):
        call = getattr(client, method)
        assert call("/api/v1" + path).status_code == 401
        assert call("/api/v1" + path, headers={**auth, "Origin": "https://evil.example"}).status_code == 403
