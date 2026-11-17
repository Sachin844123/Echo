"""Explicit schema upgrades; API startup only verifies the revision."""

import sqlite3

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


def upgrade_database(engine: Engine) -> None:
    config = alembic_config()
    with engine.begin() as connection:
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
    # Real capability probe, separate in-memory DB: no production FTS table before M3.
    with sqlite3.connect(":memory:") as probe:
        probe.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(body)")
