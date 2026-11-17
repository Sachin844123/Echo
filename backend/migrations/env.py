"""Alembic uses the same validated settings and engine as the API."""

from alembic import context

from app.core.config import Settings
from app.database.engine import create_sqlite_engine
from app.database.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("offline SQL generation is unsupported; migrate the local SQLite database")
elif context.config.attributes.get("connection") is not None:
    run(context.config.attributes["connection"])
else:
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    try:
        with engine.begin() as connection:
            run(connection)
    finally:
        engine.dispose()
