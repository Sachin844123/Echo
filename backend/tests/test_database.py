"""Schema tests use tiny synthetic TEST DATA, not an evaluation corpus."""

from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.database.engine import create_sqlite_engine
from app.database.migrate import alembic_config, check_database, upgrade_database
from app.database.models import AppSetting, Base, Chunk, Collection, CollectionItem, Document, EmbeddingRecord, IndexingJob, Source


def source(**overrides):
    return Source(**{
        "source_type": "note", "title": "TEST DATA note", "mime_type": "text/plain",
        "content_hash": "a" * 64, **overrides,
    })


def populated_graph(session):
    item = source()
    collection = Collection(name="TEST DATA collection")
    session.add_all([item, collection])
    session.flush()
    document = Document(source_id=item.id, extracted_text="TEST DATA", extraction_method="manual", content_length=9)
    session.add(document)
    session.flush()
    chunk = Chunk(document_id=document.id, chunk_index=0, chunk_text="TEST DATA", token_count=2, start_offset=0, end_offset=9)
    session.add(chunk)
    session.flush()
    session.add_all([
        EmbeddingRecord(chunk_id=chunk.id, vector_index_id=chunk.id, model_name="TEST MODEL", model_version="TEST VERSION", dimension=3),
        CollectionItem(source_id=item.id, collection_id=collection.id),
        IndexingJob(source_id=item.id),
    ])
    session.commit()
    return item.id, collection.id, chunk.id


def test_migration_matches_models_and_is_idempotent(engine):
    check_database(engine)
    upgrade_database(engine)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    tables = set(inspect(engine).get_table_names())
    assert tables == set(Base.metadata.tables) | {"alembic_version"}


def test_migration_downgrade_upgrade(engine):
    with Session(engine) as session:
        populated_graph(session)
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    upgrade_database(engine)
    check_database(engine)


def test_no_schema_creation_on_engine_import_or_construction(tmp_path):
    database = tmp_path / "new.sqlite3"
    engine = create_sqlite_engine(database)
    assert not database.exists()
    engine.dispose()


def test_reject_outdated_database(engine):
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'old_revision'"))
    with pytest.raises(RuntimeError, match="schema is not current"):
        check_database(engine)


def test_cascade_source_deletion(engine):
    with Session(engine) as session:
        source_id, _, _ = populated_graph(session)
        session.execute(delete(Source).where(Source.id == source_id))
        session.commit()
        for model in (Source, Document, Chunk, EmbeddingRecord, CollectionItem, IndexingJob):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.scalar(select(func.count()).select_from(Collection)) == 1


def test_collection_delete_keeps_source_and_chunks(engine):
    with Session(engine) as session:
        _, collection_id, _ = populated_graph(session)
        session.execute(delete(Collection).where(Collection.id == collection_id))
        session.commit()
        assert session.scalar(select(func.count()).select_from(CollectionItem)) == 0
        assert session.scalar(select(func.count()).select_from(Source)) == 1
        assert session.scalar(select(func.count()).select_from(Chunk)) == 1


def test_foreign_keys_on_every_connection(engine):
    with engine.connect() as first, engine.connect() as second:
        for connection in (first, second):
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql("INSERT INTO indexing_jobs (source_id) VALUES (999)")
            connection.rollback()


@pytest.mark.parametrize("changes", [
    {"source_type": "webpage"}, {"processing_status": "made_up"}, {"title": " "},
    {"content_hash": "invalid"}, {"content_hash": "G" * 64},
])
def test_invalid_sources_rejected_by_database(engine, changes):
    with Session(engine) as session:
        session.add(source(**changes))
        with pytest.raises(IntegrityError):
            session.commit()


def test_content_hash_uniqueness(engine):
    with Session(engine) as session:
        session.add_all([source(), source(title="Different TEST DATA title")])
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("sql", [
    "UPDATE chunks SET token_count=0", "UPDATE chunks SET chunk_index=-1",
    "UPDATE chunks SET page_number=0", "UPDATE chunks SET start_offset=-1",
    "UPDATE chunks SET end_offset=start_offset", "UPDATE chunks SET chunk_text=' '",
    "UPDATE embedding_records SET dimension=0", "UPDATE embedding_records SET vector_index_id=999",
    "UPDATE indexing_jobs SET attempts=-1", "UPDATE indexing_jobs SET status='invalid'",
    "UPDATE documents SET content_length=-1", "UPDATE documents SET extraction_status='invalid'",
    "UPDATE sources SET is_deleted=2", "UPDATE collections SET name=' '",
])
def test_database_invariants_on_raw_sql(engine, sql):
    with Session(engine) as session:
        populated_graph(session)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(sql)


def test_unique_document_chunk_and_membership(engine):
    with Session(engine) as session:
        source_id, collection_id, chunk_id = populated_graph(session)
        document_id = session.get(Chunk, chunk_id).document_id
        duplicates = [
            Document(source_id=source_id, extracted_text="TEST DATA", extraction_method="manual", content_length=9),
            Chunk(document_id=document_id, chunk_index=0, chunk_text="TEST DATA", token_count=2, start_offset=0, end_offset=9),
            CollectionItem(source_id=source_id, collection_id=collection_id),
        ]
        for duplicate in duplicates:
            session.add(duplicate)
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()


def test_ids_are_not_reused_after_deletion(engine):
    with Session(engine) as session:
        old_source, _, old_chunk = populated_graph(session)
        session.execute(delete(Source))
        session.execute(delete(Collection))
        session.commit()
        new_source, _, new_chunk = populated_graph(session)
        assert new_source > old_source
        assert new_chunk > old_chunk


def test_utc_timestamps_and_naive_rejection(engine):
    captured = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    with Session(engine) as session:
        item = source(captured_at=captured)
        session.add(item)
        session.commit()
        session.refresh(item)
        assert item.captured_at == captured.astimezone(timezone.utc)
        assert item.created_at.tzinfo == timezone.utc
        assert item.updated_at.tzinfo == timezone.utc
        session.add(source(content_hash="b" * 64, captured_at=datetime(2026, 1, 1)))
        with pytest.raises(StatementError, match="timezone-aware"):
            session.flush()


def test_updated_at_maintained_for_raw_sql(engine):
    with Session(engine) as session:
        populated_graph(session)
        session.add(AppSetting(key="search_history_enabled", value="false"))
        session.commit()
    for table, change in [
        ("sources", "title='Updated TEST DATA'"), ("collections", "name='Updated TEST DATA'"),
        ("indexing_jobs", "attempts=attempts+1"), ("app_settings", "value='false'"),
    ]:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"UPDATE {table} SET updated_at='2000-01-01 00:00:00'")
            connection.exec_driver_sql(f"UPDATE {table} SET {change}")
            assert connection.exec_driver_sql(f"SELECT updated_at FROM {table}").scalar_one() > "2000-01-01"


def test_foreign_key_columns_have_leading_indexes(engine):
    inspector = inspect(engine)
    for table in Base.metadata.tables:
        keys = inspector.get_foreign_keys(table)
        indexes = inspector.get_indexes(table) + inspector.get_unique_constraints(table)
        prefixes = {tuple(index["column_names"][:1]) for index in indexes}
        prefixes.add(tuple(inspector.get_pk_constraint(table)["constrained_columns"][:1]))
        for key in keys:
            assert tuple(key["constrained_columns"][:1]) in prefixes, (table, key)
