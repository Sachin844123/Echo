"""One small SQLite pool; pragmas applied to every connection."""

from pathlib import Path

from sqlalchemy import Engine, URL, create_engine, event
from sqlalchemy.orm import sessionmaker


def create_sqlite_engine(database_path: Path) -> Engine:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        connect_args={"check_same_thread": False, "timeout": 5},
        pool_size=2, max_overflow=0, pool_pre_ping=True, hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(connection, _record):
        # Explicit BEGIN gives Python 3.11/3.12 consistent transactional DDL.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    return engine


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
