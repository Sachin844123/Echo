import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.main import create_app


def test_health_hits_local_database(client, auth):
    response = client.get("/api/v1/health", headers=auth)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.6.0", "database": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert len(response.headers["x-request-id"]) == 32


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic wrong", "Bearer ", "Bearer " + "x" * 1000, "Bearer \xff"])
def test_authentication_failures(client, header):
    headers = [] if header is None else [(b"authorization", header.encode("latin-1"))]
    response = client.get("/api/v1/health", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_duplicate_authorization_is_rejected(client, auth):
    response = client.get("/api/v1/health", headers=[("Authorization", auth["Authorization"])] * 2)
    assert response.status_code == 401


@pytest.mark.parametrize("origin", ["null", "https://evil.example", "http://localhost:5173", "http://127.0.0.1:8000/", "http://127.0.0.1:8000.evil"])
def test_bad_origins_fail_even_with_token(client, auth, origin):
    response = client.get("/api/v1/health", headers={**auth, "Origin": origin})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_same_origin_and_cors_on_auth_error(client, auth):
    origin = {"Origin": "http://127.0.0.1:8000"}
    for headers, status in [(origin, 401), ({**origin, **auth}, 200)]:
        response = client.get("/api/v1/health", headers=headers)
        assert response.status_code == status
        assert response.headers["access-control-allow-origin"] == origin["Origin"]
        assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil:8000", "127.0.0.1:9999", "localhost", "127.0.0.1:8000@evil.example"])
def test_host_validation(client, auth, host):
    assert client.get("/api/v1/health", headers={**auth, "Host": host}).status_code == 400


def test_duplicate_origin_and_host(client, auth):
    base = list(auth.items())
    response = client.get("/api/v1/health", headers=base + [("Origin", "http://127.0.0.1:8000")] * 2)
    assert response.status_code == 403
    response = client.get("/api/v1/health", headers=base + [("Host", "127.0.0.1:8000")] * 2)
    assert response.status_code == 400


def test_preflight_only_exposes_transport_policy(client):
    headers = {"Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    response = client.options("/api/v1/health", headers=headers)
    assert response.status_code == 200
    assert response.text == "OK"
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    assert client.options("/api/v1/health").status_code == 401
    assert client.options("/api/v1/health", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    assert client.options("/api/v1/health", headers={**headers, "Access-Control-Request-Method": "TRACE"}).status_code == 400
    assert client.options("/api/v1/health", headers={**headers, "Access-Control-Request-Headers": "x-unapproved"}).status_code == 400


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/unknown"])
def test_no_unguarded_routes_or_documentation(client, auth, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth).status_code == 404


def test_remote_client_cannot_spoof_loopback(app, auth):
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("198.51.100.10", 50000)) as client:
        response = client.get("/api/v1/health", headers={**auth, "X-Forwarded-For": "127.0.0.1"})
    assert response.status_code == 403


def test_database_failure_is_503_and_redacted(client, app, auth, monkeypatch):
    def fail():
        raise OperationalError("SELECT private_content", {}, RuntimeError("PRIVATE test data"))

    monkeypatch.setattr(app.state.engine, "connect", fail)
    response = client.get("/api/v1/health", headers=auth)
    assert response.status_code == 503
    assert "PRIVATE" not in response.text
    assert response.json()["database"] == "unavailable"


def test_uncaught_failure_is_redacted(client, app, auth, monkeypatch):
    def fail():
        raise RuntimeError("PRIVATE test data")

    monkeypatch.setattr(app.state.engine, "connect", fail)
    response = client.get("/api/v1/health", headers=auth)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_startup_requires_token(tmp_path):
    with pytest.raises(ValueError, match="ECHO_SESSION_TOKEN"):
        create_app(Settings(data_dir=tmp_path))


def test_startup_requires_migration(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, session_token=secrets.token_urlsafe(32)))
    with pytest.raises(RuntimeError, match="migrate"):
        with TestClient(app):
            pass
    assert not (tmp_path / "echo.sqlite3").exists()
