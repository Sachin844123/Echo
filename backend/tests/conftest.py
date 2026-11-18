"""All inserted content is tiny synthetic TEST DATA, never research evidence."""

import os
import secrets
import socket

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.database.engine import create_sqlite_engine
from app.database.migrate import upgrade_database
from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("ECHO_"):
            monkeypatch.delenv(key)
    real_connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("Tests must not contact external networks")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, embedding_model_dir=tmp_path / "missing-model", session_token=secrets.token_urlsafe(32))


@pytest.fixture
def engine(settings):
    engine = create_sqlite_engine(settings.database_path)
    upgrade_database(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def app(settings, engine):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        yield client


@pytest.fixture
def auth(settings):
    return {"Authorization": f"Bearer {settings.session_token.get_secret_value()}"}
