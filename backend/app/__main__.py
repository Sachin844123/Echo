"""Local ECHO commands and the browser launcher used by Run-ECHO.bat."""

import argparse
import logging
import secrets
import sys
import threading
import webbrowser

import uvicorn
from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings
from app.core.logging import configure_logging
from app.database.engine import create_sqlite_engine
from app.database.migrate import check_database, upgrade_database
from app.main import create_app
from app.storage.instance_lock import InstanceLock


def migrate(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    ownership = InstanceLock(settings.data_dir / "ingestion.lock")
    try:
        ownership.acquire()
        upgrade_database(engine)
        check_database(engine)
    finally:
        ownership.release()
        engine.dispose()
    logging.getLogger("echo.cli").info("migration_complete")


class BrowserServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            address = f"http://127.0.0.1:{self.config.port}/"
            print(f"ECHO is ready at {address}. Press Ctrl+C to stop.", flush=True)
            threading.Thread(target=open_dashboard, args=(address,), daemon=True).start()


def open_dashboard(address: str) -> None:
    try:
        if webbrowser.open(address):
            return
    except (OSError, webbrowser.Error):
        pass
    print(f"Open {address} in your browser.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="ECHO local research backend")
    parser.add_argument("command", choices=("token", "migrate", "serve", "launch", "rebuild-index"))
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
            migrate(settings)
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
            if args.command == "launch":
                if not (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
                    print("Build the ECHO dashboard with npm run build in frontend.", file=sys.stderr)
                    return 2
                migrate(settings)
            if not settings.database_path.is_file():
                print("Initialize the database first: python -m app migrate", file=sys.stderr)
                return 2
            # No host override, proxy trust, reload process or multi-worker model copies.
            config = uvicorn.Config(
                create_app(settings), host="127.0.0.1", port=settings.port,
                workers=1, proxy_headers=False, access_log=False, log_config=None,
                server_header=False, date_header=False, ws="none",
            )
            server_class = BrowserServer if args.command == "launch" else uvicorn.Server
            server = server_class(config)
            server.run()
            if not server.started:
                return 1
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
