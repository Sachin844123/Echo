"""Explicit schema upgrades; API startup only verifies the revision."""

import sqlite3
from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from app.core.config import REPO_ROOT


def alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    # Escape ConfigParser interpolation; paths containing '%' are valid on Windows.
    config.set_main_option("script_location", str(REPO_ROOT / "backend" / "migrations").replace("%", "%%"))
    return config


@contextmanager
def migration_connection(engine: Engine):
    """Rebuild SQLite parent tables atomically without triggering child cascades.

    Disable FK actions on this connection before BEGIN, check all relationships
    before COMMIT, and restore enforcement even when a migration rolls back.
    The supported CLI also holds the library's exclusive instance lock.
    """
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        raw.execute("PRAGMA foreign_keys=OFF")
        try:
            with connection.begin():
                yield connection
                if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                    raise RuntimeError("migration foreign key validation failed")
        finally:
            raw.execute("PRAGMA foreign_keys=ON")


def upgrade_database(engine: Engine) -> None:
    config = alembic_config()
    with migration_connection(engine) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        heads = MigrationContext.configure(connection).get_current_heads()
        expected = tuple(ScriptDirectory.from_config(alembic_config()).get_heads())
        if set(heads) != set(expected):
            raise RuntimeError("database schema is not current; run python -m app migrate")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
            raise RuntimeError("SQLite foreign key enforcement is required")
    # Verify the linked SQLite library supports the persistent M3 FTS5 schema.
    with sqlite3.connect(":memory:") as probe:
        probe.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(body)")
