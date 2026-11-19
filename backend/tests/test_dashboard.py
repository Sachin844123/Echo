"""M6 security and library workflows using tiny, explicitly synthetic TEST DATA."""

import hashlib

import pytest
from sqlalchemy import func, select

from app.database.models import Chunk, Collection, Document, EmbeddingRecord, IndexingJob, Source
from app.ingestion.errors import ImportFailure
from test_search_api import import_note


def test_public_shell_keeps_every_api_authenticated(client, auth):
    response = client.get('/')
    assert response.status_code in {200, 503}  # Build is optional for backend-only installs.
    assert 'frame-ancestors \'none\'' in response.headers['content-security-policy']
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert response.headers['x-frame-options'] == 'DENY'
    assert response.headers['cache-control'] == 'no-store'
    assert 'unsafe-inline' not in response.headers['content-security-policy']
    assert client.post('/').status_code == 401
    assert client.post('/assets/example.js').status_code == 401
    for path in ('/api/v1/settings', '/api/v1/library', '/api/v1/sources', '/api/v1/collections'):
        assert client.get(path).status_code == 401
    assert client.request('DELETE', '/api/v1/library', json={'confirmation': 'DELETE ALL'}).status_code == 401
    assert client.get('/', headers={'Host': 'evil.example'}).status_code == 400
    assert client.get('/', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/v1/settings', headers=auth).status_code == 200


@pytest.mark.parametrize('path', [
    '/api/v1/sources/PRIVATE-TEST-DATA', '/api/v1/sources?limit=PRIVATE-TEST-DATA',
    '/api/v1/sources?source_type=PRIVATE-TEST-DATA', '/api/v1/collections?offset=PRIVATE-TEST-DATA',
    '/api/v1/indexing-jobs/PRIVATE-TEST-DATA',
])
def test_parameter_validation_never_echoes_input(client, auth, path):
    response = client.get(path, headers=auth)
    assert response.status_code == 422
    assert 'PRIVATE' not in response.text
    assert response.json()['error']['code'] == 'invalid_request'


def test_settings_expose_no_paths_or_secrets(client, auth, settings):
    response = client.get('/api/v1/settings', headers=auth)
    assert response.status_code == 200
    assert not response.json()['search_history_enabled']
    assert response.json()['max_upload_bytes'] == settings.max_upload_bytes
    assert settings.session_token.get_secret_value() not in response.text
    assert str(settings.data_dir) not in response.text
    assert 'data_dir' not in response.text and 'session_token' not in response.text


def test_collection_browsing_counts_and_source_memberships(client, auth):
    source = import_note(client, auth)
    group = client.post('/api/v1/collections', headers=auth, json={'name': 'TEST DATA collection'}).json()['id']
    client.put(f'/api/v1/collections/{group}/sources/{source}', headers=auth)
    assert client.get(f'/api/v1/sources?collection_id={group}', headers=auth).json()['total'] == 1
    assert client.get(f'/api/v1/sources?collection_id={group}&source_type=pdf', headers=auth).json()['total'] == 0
    assert client.get('/api/v1/sources?source_type=note', headers=auth).json()['total'] == 1
    assert client.get(f'/api/v1/sources/{source}', headers=auth).json()['collection_ids'] == [group]
    assert client.get('/api/v1/collections', headers=auth).json()['items'][0]['source_count'] == 1
    client.delete(f'/api/v1/sources/{source}', headers=auth)
    assert client.get('/api/v1/collections', headers=auth).json()['items'][0]['source_count'] == 0


@pytest.mark.parametrize('body', [{}, {'confirmation': 'yes'}, {'confirmation': 'DELETE ALL', 'extra': 'PRIVATE TEST DATA'}])
def test_delete_library_requires_explicit_exact_confirmation(client, auth, body):
    source = import_note(client, auth)
    response = client.request('DELETE', '/api/v1/library', headers=auth, json=body)
    assert response.status_code == 422
    assert 'PRIVATE' not in response.text
    assert client.get(f'/api/v1/sources/{source}', headers=auth).status_code == 200


def test_delete_library_removes_content_and_prevents_old_upload_publish(client, auth, app, settings):
    import_note(client, auth)
    client.post('/api/v1/collections', headers=auth, json={'name': 'TEST DATA collection'})
    owner = app.state.ingestion
    generation = owner.import_generation
    staged = owner.store.new_stage()
    payload = b'TEST DATA in-flight document before reset'
    staged.write_bytes(payload)
    response = client.request('DELETE', '/api/v1/library', headers=auth, json={'confirmation': 'DELETE ALL'})
    assert response.status_code == 200
    with app.state.search.sessions() as session:
        for model in (Source, Document, Chunk, EmbeddingRecord, Collection, IndexingJob):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.connection().exec_driver_sql('SELECT count(*) FROM chunk_fts').scalar() == 0
    assert not app.state.search.vectors.ids
    assert not list((settings.data_dir / 'imports').iterdir())
    with pytest.raises(ImportFailure, match='library_reset'):
        owner.enqueue(staged, 'test.txt', hashlib.sha256(payload).hexdigest(), expected_generation=generation)
    assert not staged.exists()
    assert client.get('/api/v1/sources', headers=auth).json()['total'] == 0
    # Reset is idempotent; a genuinely new import is still supported.
    assert client.request('DELETE', '/api/v1/library', headers=auth, json={'confirmation': 'DELETE ALL'}).status_code == 200
    assert import_note(client, auth) > 0


def test_delete_library_retains_tombstones_until_storage_recovers(client, auth, app, monkeypatch):
    import_note(client, auth)
    files = app.state.search.files
    remove = files.remove

    def unavailable(*args):
        raise OSError('TEST DATA PRIVATE path')

    monkeypatch.setattr(files, 'remove', unavailable)
    response = client.request('DELETE', '/api/v1/library', headers=auth, json={'confirmation': 'DELETE ALL'})
    assert response.status_code == 202
    assert response.json()['deletions_pending'] == 1
    assert client.get('/api/v1/sources', headers=auth).json()['total'] == 0
    assert client.post('/api/v1/search', headers=auth, json={'query': 'solar', 'mode': 'keyword'}).json()['results'] == []
    monkeypatch.setattr(files, 'remove', remove)
    app.state.search.finish_deletions()
    assert client.get('/api/v1/index/status', headers=auth).json()['deletions_pending'] == 0
