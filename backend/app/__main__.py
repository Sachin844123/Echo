"""Supported local launcher: python -m app {token,migrate,serve}."""

import argparse
import logging
import secrets
import sys

import uvicorn
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import configure_logging
from app.database.engine import create_sqlite_engine
from app.database.migrate import check_database, upgrade_database
from app.main import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="ECHO local research backend")
    parser.add_argument("command", choices=("token", "migrate", "serve", "rebuild-index"))
    args = parser.parse_args()
    if args.command == "token":
        # Intentional CLI output for capture in a shell variable; never a log record.
        print(secrets.token_urlsafe(32))
        return 0

    configure_logging()
    try:
        settings = Settings.from_env()
        configure_logging(settings.log_level)
        if args.command == "migrate":
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            engine = create_sqlite_engine(settings.database_path)
            try:
                upgrade_database(engine)
                check_database(engine)
            finally:
                engine.dispose()
            logging.getLogger("echo.cli").info("migration_complete")
        elif args.command == "rebuild-index":
            from app.ingestion.service import IngestionService
            from app.retrieval.engine import SearchEngine
            engine = create_sqlite_engine(settings.database_path)
            owner = IngestionService(engine, settings)
            try:
                owner.instance_lock.acquire()
                check_database(engine)
                owner.store.prepare()
                search = SearchEngine(engine, settings, owner.mutation_lock, owner.store)
                search.rebuild()
            finally:
                owner.instance_lock.release()
                engine.dispose()
            print("Vector index reset; start the server to process queued indexing jobs.")
        else:
            if settings.session_token is None:
                print("Set ECHO_SESSION_TOKEN using: python -m app token", file=sys.stderr)
                return 2
            if not settings.database_path.is_file():
                print("Initialize the database first: python -m app migrate", file=sys.stderr)
                return 2
            # No host override, proxy trust, reload process or multi-worker model copies.
            uvicorn.run(
                create_app(settings), host="127.0.0.1", port=settings.port,
                workers=1, proxy_headers=False, access_log=False, log_config=None,
                server_header=False, date_header=False, ws="none",
            )
        return 0
    except (ValidationError, ValueError):
        logging.getLogger("echo.cli").exception("command_failed")
        print("Invalid ECHO configuration; check the environment variables documented in README.md.", file=sys.stderr)
        return 2
    except Exception:
        logging.getLogger("echo.cli").exception("command_failed")
        print("ECHO could not start or migrate. Check local storage access and the database revision.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
