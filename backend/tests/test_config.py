import json
import secrets
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("values", [
    {"host": "0.0.0.0"}, {"host": "localhost"}, {"port": 0}, {"port": 65536},
    {"session_token": "short"}, {"session_token": "x" * 42 + "!"},
    {"allowed_origins": ["*"]}, {"allowed_origins": ["null"]},
    {"allowed_origins": ["https://example.com:8000"]},
    {"allowed_origins": ["http://127.0.0.1:8000/"]},
    {"allowed_origins": ["http://localhost.evil:8000"]},
    {"allowed_origins": ["http://user@localhost:8000"]},
    {"allowed_origins": ["http://localhost:8000?x=1"]},
    {"allowed_origins": ["http://localhost"]},
    {"allowed_origins": ["http://localhost:invalid"]},
    {"unknown_setting": True},
])
def test_reject_unsafe_settings(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_environment_and_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ECHO_DATA_DIR", "data with spaces and %")
    monkeypatch.setenv("ECHO_PORT", "8123")
    monkeypatch.setenv("ECHO_ALLOWED_ORIGINS", json.dumps(["http://localhost:8123"]))
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("ECHO_SESSION_TOKEN", token)
    config = Settings.from_env()
    assert config.database_path == tmp_path / "data with spaces and %" / "echo.sqlite3"
    assert config.allowed_origins == ("http://localhost:8123",)
    assert config.allowed_hosts == {"127.0.0.1:8123", "localhost:8123"}
    assert config.session_token.get_secret_value() == token
    assert token not in repr(config)
    assert not config.data_dir.exists()  # Reading settings has no I/O side effects.


def test_default_origin_follows_port():
    assert Settings(port=9000).allowed_origins == ("http://127.0.0.1:9000",)
    assert isinstance(Settings().database_path, Path)


def test_bad_secret_is_not_in_validation_error():
    secret = "PRIVATE invalid token"
    with pytest.raises(ValidationError) as error:
        Settings(session_token=SecretStr(secret))
    assert secret not in str(error.value)
