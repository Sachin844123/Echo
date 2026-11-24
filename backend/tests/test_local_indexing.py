"""Only tiny synthetic TEST DATA. Never grant a real drive in these tests."""

import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import REPO_ROOT
from app.database.models import LocalFile, Source
from app.main import create_app
from app.storage import indexing
from test_retrieval import UnitEncoder


def eventually(check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    pytest.fail("The synthetic storage operation did not finish in time")


@pytest.fixture
def folders(app):
    with tempfile.TemporaryDirectory(prefix="TEST-DATA-storage-", dir=REPO_ROOT) as directory:
        root = Path(directory).resolve()
        assert root.parent == REPO_ROOT and root.name.startswith("TEST-DATA-storage-")
        approved, outside = root / "approved", root / "outside"
        approved.mkdir()
        outside.mkdir()
        # The test directory lives in the checkout only to avoid Windows AppData.
        app.state.local_indexing.system_exclusions = (app.state.ingestion.settings.data_dir,)
        yield approved, outside


def grant(client, auth, path, **options):
    return client.put('/api/v1/storage/permission', headers=auth, json={
        'mode': 'selected', 'folders': [str(path)], 'confirm': True, **options,
    })


def list_files(client, auth):
    return client.get('/api/v1/storage/files', headers=auth).json()['items']


def search(client, auth, text):
    return client.post('/api/v1/search', headers=auth, json={'query': text, 'mode': 'keyword', 'correct_spelling': False}).json()['results']


def test_storage_api_and_scope_reject_unauthorized_or_unsafe_requests(client, auth, app, folders):
    approved, outside = folders
    path = '/api/v1/storage/permission'
    assert client.get('/api/v1/storage').status_code == 401
    assert client.get('/api/v1/storage/options').status_code == 401
    assert client.get('/api/v1/storage/files').status_code == 401
    assert grant(client, {}, approved).status_code == 401
    assert grant(client, {**auth, 'Origin': 'https://untrusted.example'}, approved).status_code == 403
    assert client.put(path, headers=auth, json={'mode': 'all'}).status_code == 422
    for bad in ('relative', r'\\server\share', str(approved / '..' / 'outside'), str(approved / 'missing')):
        assert grant(client, auth, bad).status_code == 422
    assert grant(client, auth, approved, exclusions=[str(outside)]).status_code == 422
    assert grant(client, auth, approved, extensions=['.pem']).status_code == 422
    for protected in (app.state.ingestion.settings.data_dir, approved / 'AppData', approved / '.ssh'):
        protected.mkdir(exist_ok=True)
        assert grant(client, auth, protected).status_code == 422
    assert client.get('/api/v1/storage', headers=auth).json()['mode'] is None
    assert list_files(client, auth) == []


def test_discovery_filters_protected_files_and_links_duplicate_content(client, auth, app, folders):
    approved, outside = folders
    text = 'TEST DATA lupine approved content'
    for name in ('nested/allowed.txt', 'duplicate.txt', 'exclude/hidden.txt', 'AppData/profile.txt', '.ssh/key.txt', 'passwords.txt', 'skip.md'):
        path = approved / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    (outside / 'outside.txt').write_text('TEST DATA outside limit', encoding='utf-8')
    (approved / 'renamed.txt').write_text('TEST DATA\n-----BEGIN PRIVATE KEY-----\nnot-a-real-key', encoding='utf-8')
    junction = approved / 'junction'
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(outside)],
                                capture_output=True, check=False, timeout=10)
        assert result.returncode == 0
    else:
        junction.symlink_to(outside, target_is_directory=True)
    assert list_files(client, auth) == []
    try:
        response = grant(client, auth, approved, exclusions=[str(approved / 'exclude')], extensions=['.txt'])
        assert response.status_code == 200
        def scan_status():
            status = client.get('/api/v1/storage', headers=auth).json()
            return status if status['progress'].get('completed_scans') or status['errors'] else None
        status = eventually(scan_status)
        assert not any(item['code'] == 'service_error' for item in status['errors']), status['errors']
        eventually(lambda: client.get('/api/v1/storage', headers=auth).json()['progress'].get('completed_scans'))
        assert len(list_files(client, auth)) == 2, (status['progress'], status['errors'])
        eventually(lambda: search(client, auth, 'lupine'))
        rows = list_files(client, auth)
        assert {Path(row['path']).name for row in rows} == {'allowed.txt', 'duplicate.txt'}
        assert len({row['source_id'] for row in rows}) == 1
        status = client.get('/api/v1/storage', headers=auth).json()
        assert status['stored_bytes'] == len(text)
        assert search(client, auth, 'outside') == []
        assert eventually(lambda: any(item['code'] == 'protected_content' for item in client.get('/api/v1/storage', headers=auth).json()['errors']))
    finally:
        if os.name == 'nt':
            junction.rmdir()
        else:
            junction.unlink()


@pytest.mark.skipif(os.name != 'nt', reason='Windows watchdog integration')
def test_live_updates_pause_resume_cancel_and_revocation_preserve_originals(client, auth, app, folders):
    approved, _ = folders
    app.state.search.encoder = UnitEncoder()
    app.state.search.reconcile()
    assert grant(client, auth, approved, extensions=['.txt']).status_code == 200
    eventually(lambda: client.get('/api/v1/storage', headers=auth).json()['progress'].get('completed_scans'))

    def action(name):
        response = client.post('/api/v1/storage/control', headers=auth, json={'action': name})
        assert response.status_code == 200
        return response.json()['state']

    first = approved / 'live.txt'
    first.write_text('TEST DATA primrose', encoding='utf-8')
    old = eventually(lambda: search(client, auth, 'primrose'))[0]['source_id']
    assert action('rescan') == 'active'
    eventually(lambda: client.get('/api/v1/storage', headers=auth).json()['progress'].get('unchanged'))
    assert list_files(client, auth)[0]['source_id'] == old
    first.write_text('TEST DATA rosemary', encoding='utf-8')
    new = eventually(lambda: search(client, auth, 'rosemary'))[0]['source_id']
    assert new != old
    assert search(client, auth, 'primrose') == []
    first.unlink()
    eventually(lambda: not search(client, auth, 'rosemary'))
    assert action('pause') == 'paused'
    shared = approved / 'keep.txt'
    shared.write_text('TEST DATA heather', encoding='utf-8')
    unique = approved / 'remove.txt'
    unique.write_text('TEST DATA echinacea', encoding='utf-8')
    time.sleep(0.7)
    assert list_files(client, auth) == []
    assert action('resume') == 'active'
    eventually(lambda: search(client, auth, 'heather'))
    eventually(lambda: search(client, auth, 'echinacea'))
    upload = client.post('/api/v1/imports/files?filename=manual.txt', headers=auth, content=shared.read_bytes())
    assert upload.status_code == 200 and upload.json()['duplicate']
    assert action('cancel') == 'cancelled'
    done = client.put('/api/v1/storage/permission', headers=auth, json={'mode': 'deny', 'confirm': True})
    assert done.status_code == 200 and done.json()['mode'] == 'deny'
    assert list_files(client, auth) == []
    assert search(client, auth, 'echinacea') == []
    assert search(client, auth, 'heather')
    assert shared.read_text() == 'TEST DATA heather'
    assert unique.read_text() == 'TEST DATA echinacea'
    eventually(lambda: client.get('/api/v1/storage', headers=auth).json()['purging_sources'] == 0)
    with app.state.ingestion.sessions() as session:
        assert list(session.scalars(select(Source.manual_capture))) == [True]
        assert not list(session.scalars(select(LocalFile.path)))


def test_consent_and_cancelled_state_survive_restart(settings, engine, auth):
    app = create_app(settings)
    options = dict(base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50000))
    with TestClient(app, **options) as client:
        with tempfile.TemporaryDirectory(prefix='TEST-DATA-storage-', dir=REPO_ROOT) as folder:
            app.state.local_indexing.system_exclusions = (settings.data_dir,)
            assert grant(client, auth, Path(folder), extensions=['.txt']).status_code == 200
            response = client.post('/api/v1/storage/control', headers=auth, json={'action': 'cancel'})
            assert response.json()['state'] == 'cancelled'
    with TestClient(create_app(settings), **options) as client:
        status = client.get('/api/v1/storage', headers=auth).json()
        assert status['mode'] == 'selected' and status['state'] == 'cancelled'
        assert status['roots'] == [str(Path(folder))]


def test_personal_and_all_modes_save_snapshot_and_delete_all_revokes(client, auth, folders, monkeypatch):
    approved, outside = folders
    monkeypatch.setattr(indexing, 'fixed_drives', lambda: (approved, outside))
    monkeypatch.setattr(indexing, 'personal_folders', lambda: (approved,))
    for mode, roots in [('personal', {str(approved)}), ('all', {str(approved), str(outside)})]:
        response = client.put('/api/v1/storage/permission', headers=auth, json={'mode': mode, 'confirm': True})
        assert response.status_code == 200
        assert set(response.json()['roots']) == roots
    monkeypatch.setattr(indexing, 'fixed_drives', lambda: ())
    assert set(client.get('/api/v1/storage', headers=auth).json()['roots']) == {str(approved), str(outside)}
    response = client.request('DELETE', '/api/v1/library', headers=auth, json={'confirmation': 'DELETE ALL'})
    assert response.status_code == 200
    assert client.get('/api/v1/storage', headers=auth).json()['mode'] == 'deny'


def test_revoke_prevents_a_read_already_in_flight_from_publishing(client, auth, app, folders, monkeypatch):
    approved, _ = folders
    original = approved / 'inflight.txt'
    original.write_text('TEST DATA chrysanthemum', encoding='utf-8')
    reading, release, departed = Event(), Event(), Event()
    approved_open = indexing.open_approved

    @contextmanager
    def blocked_open(path, policy):
        with approved_open(path, policy) as opened:
            reading.set()
            try:
                assert release.wait(15)
                yield opened
            finally:
                departed.set()

    monkeypatch.setattr(indexing, 'open_approved', blocked_open)
    assert grant(client, auth, approved, extensions=['.txt']).status_code == 200
    try:
        assert reading.wait(10)
        response = client.put('/api/v1/storage/permission', headers=auth, json={'mode': 'deny', 'confirm': True})
        assert response.status_code == 200
    finally:
        release.set()
    assert departed.wait(10)
    eventually(lambda: not list(app.state.ingestion.store.staging.iterdir()))
    assert list_files(client, auth) == []
    assert search(client, auth, 'chrysanthemum') == []
    assert original.read_text() == 'TEST DATA chrysanthemum'
