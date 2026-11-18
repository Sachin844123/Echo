"""Actual offline MiniLM integration on tiny synthetic TEST DATA, not an evaluation."""

import json
import socket
import time

import numpy as np
import pytest

from app.core.config import REPO_ROOT, Settings
from app.embeddings.local import LocalEncoder, MODEL_FILES
from app.retrieval.errors import RetrievalFailure


@pytest.fixture(scope="module")
def real_encoder():
    settings = Settings(embedding_model_dir=REPO_ROOT / ".local" / "models" / "all-MiniLM-L6-v2")
    if not (settings.embedding_model_dir / "echo-model.json").is_file():
        pytest.skip("Offline model prerequisite: run scripts/prepare_model.py before real-model integration tests")
    return LocalEncoder(settings)


def test_real_encoder_offline_normalized_deterministic_and_not_truncated(real_encoder, monkeypatch):
    def offline(*args, **kwargs):
        raise AssertionError("Embedding runtime attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", offline)
    a = "TEST DATA solar panels convert sunlight to electricity."
    b = "TEST DATA ocean waves break on the beach."
    values = real_encoder.encode([a, b])
    assert values.shape == (2, 384)
    np.testing.assert_allclose(np.linalg.norm(values, axis=1), [1, 1], atol=1e-5)
    model = real_encoder._model
    np.testing.assert_allclose(real_encoder.encode([a])[0], values[0], atol=1e-5)
    assert real_encoder._model is model
    prefix = "TEST DATA engineering " * 170
    extended = real_encoder.encode([prefix + a * 20, prefix + b * 20])
    assert not np.allclose(extended[0], extended[1], atol=1e-4)


def test_real_semantic_worker_api_and_deletion(client, app, auth, real_encoder):
    # Production encoder; shared by these tests so the model is loaded once.
    app.state.search.encoder = real_encoder
    app.state.search.reconcile()
    response = client.post("/api/v1/imports/notes", headers=auth, json={
        "title": "TEST DATA renewable energy", "text": "TEST DATA solar panels turn sunlight into electrical power."})
    assert response.status_code == 202
    source = response.json()["source_id"]
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/sources/{source}", headers=auth).json()
        if status["processing_status"] in {"indexed", "failed"}:
            break
        time.sleep(0.05)
    assert status["processing_status"] == "indexed"
    for mode in ("keyword", "semantic", "hybrid", "hybrid_contextual"):
        result = client.post("/api/v1/search", headers=auth, json={"query": "solar electricity", "mode": mode})
        assert result.status_code == 200, result.text
        assert result.json()["results"][0]["source_id"] == source
        assert not result.json()["indexing_incomplete"]
    app.state.search.reconcile()
    assert len(app.state.search.vectors.ids) > 0
    assert client.delete(f"/api/v1/sources/{source}", headers=auth).status_code == 200
    assert client.post("/api/v1/search", headers=auth, json={"query": "solar electricity", "mode": "semantic"}).json()["results"] == []
    assert not app.state.search.vectors.ids


def test_missing_and_modified_model_files_fail_closed(settings, tmp_path):
    encoder = LocalEncoder(settings)
    with pytest.raises(RetrievalFailure, match="model_unavailable"):
        _ = encoder.identity
    settings.embedding_model_dir.mkdir()
    (settings.embedding_model_dir / "echo-model.json").write_text(json.dumps({
        "name": settings.embedding_model_name, "files": {name: "0" * 64 for name in MODEL_FILES}}))
    with pytest.raises(RetrievalFailure, match="model_invalid"):
        _ = encoder.identity
