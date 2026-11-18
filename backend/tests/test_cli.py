"""Exercise the supported CLI and a real loopback HTTP server on Windows."""

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time

import httpx

from app.core.config import REPO_ROOT


def run_cli(command, env):
    return subprocess.run(
        [sys.executable, "-m", "app", command], cwd=REPO_ROOT / "backend",
        env=env, capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def test_token_generation_is_random_and_not_persisted(tmp_path):
    env = {**os.environ, "ECHO_DATA_DIR": str(tmp_path / "unused")}
    first = run_cli("token", env)
    second = run_cli("token", env)
    assert first.returncode == second.returncode == 0
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}\n", first.stdout)
    assert first.stdout != second.stdout
    assert first.stderr == second.stderr == ""
    assert not (tmp_path / "unused").exists()


def test_cli_missing_token_and_invalid_configuration(tmp_path):
    env = {**os.environ, "ECHO_DATA_DIR": str(tmp_path)}
    result = run_cli("serve", env)
    assert result.returncode == 2
    assert "ECHO_SESSION_TOKEN" in result.stderr
    secret = "PRIVATE malformed token"
    result = run_cli("serve", {**env, "ECHO_SESSION_TOKEN": secret})
    assert result.returncode == 2
    assert secret not in result.stdout + result.stderr
    result = run_cli("serve", {**env, "ECHO_HOST": "0.0.0.0"})
    assert result.returncode == 2


def test_real_server_migration_and_security(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    token = secrets.token_urlsafe(32)
    env = {
        **os.environ, "ECHO_DATA_DIR": str(tmp_path / "data with spaces and %"),
        "ECHO_EMBEDDING_MODEL_DIR": str(tmp_path / "missing-model"),
        "ECHO_SESSION_TOKEN": token, "ECHO_PORT": str(port),
    }
    migrated = run_cli("migrate", env)
    assert migrated.returncode == 0, migrated.stderr
    assert '"event": "migration_complete"' in migrated.stderr
    # A PIPE left unread while polling fills on Windows and blocks server logging.
    log_path = tmp_path / "server.jsonl"
    with log_path.open("w", encoding="utf-8") as log_stream:
        process = subprocess.Popen(
            [sys.executable, "-m", "app", "serve"], cwd=REPO_ROOT / "backend", env=env,
            stdout=subprocess.PIPE, stderr=log_stream, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1, trust_env=False) as client:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert process.poll() is None, "Server exited before readiness"
                try:
                    response = client.get("/api/v1/health")
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    time.sleep(0.05)
            else:
                raise AssertionError("Local server did not become ready")
            assert response.status_code == 401
            auth = {"Authorization": f"Bearer {token}"}
            response = client.get("/api/v1/health?private=TEST_SECRET_QUERY", headers=auth)
            assert response.status_code == 200
            assert response.json()["database"] == "ok"
            assert "server" not in response.headers
            assert client.get("/api/v1/health", headers={**auth, "Origin": "https://evil.example"}).status_code == 403
            assert client.get("/api/v1/health", headers={**auth, "Host": "evil.example"}).status_code == 400
            imported = client.post(
                "/api/v1/imports/files?filename=TEST-DATA.txt",
                headers={**auth, "Content-Type": "application/octet-stream"},
                content=b"TEST_SECRET_DOCUMENT: explicitly synthetic ingestion fixture.",
            )
            assert imported.status_code == 202, imported.text
            job_id = imported.json()["job_id"]
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/indexing-jobs/{job_id}", headers=auth).json()
                if job["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.05)
            assert job["status"] == "succeeded", job
            assert job["chunk_count"] > 0
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
    stderr = log_path.read_text(encoding="utf-8")
    assert token not in stdout + stderr
    assert "TEST_SECRET_QUERY" not in stdout + stderr
    assert "TEST_SECRET_DOCUMENT" not in stdout + stderr
    logs = [json.loads(line) for line in stderr.splitlines()]
    assert any(entry["event"] == "startup_complete" for entry in logs)
    assert any(entry.get("status_code") == 200 for entry in logs)
