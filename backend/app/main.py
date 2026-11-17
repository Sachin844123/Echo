"""Application factory with no database mutation at import time."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from app import __version__
from app.api.health import router
from app.api.ingestion import router as ingestion_router, import_failure_handler
from app.core.config import Settings
from app.database.engine import create_session_factory, create_sqlite_engine
from app.database.migrate import check_database
from app.security.middleware import LocalSecurityMiddleware
from app.ingestion.errors import ImportFailure
from app.ingestion.service import IngestionService


logger = logging.getLogger("echo.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.session_token is None:
        raise ValueError("ECHO_SESSION_TOKEN is required; generate it with python -m app token")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_sqlite_engine(settings.database_path)
        ingestion = None
        try:
            if not settings.database_path.is_file():
                raise RuntimeError("database is missing; run python -m app migrate")
            await run_in_threadpool(check_database, engine)
            app.state.engine = engine
            app.state.session_factory = create_session_factory(engine)
            ingestion = IngestionService(engine, settings)
            await run_in_threadpool(ingestion.start)
            app.state.ingestion = ingestion
            logger.info("startup_complete")
            yield
        except Exception:
            logger.exception("startup_failed")
            raise
        finally:
            if ingestion is not None:
                await run_in_threadpool(ingestion.stop)
            await run_in_threadpool(engine.dispose)
            logger.info("shutdown_complete")

    app = FastAPI(
        title="ECHO", version=__version__, lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None, debug=False,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False, expose_headers=["X-Request-ID"], max_age=600,
    )
    app.add_middleware(LocalSecurityMiddleware, settings=settings)
    app.include_router(router)
    app.include_router(ingestion_router)
    app.add_exception_handler(ImportFailure, import_failure_handler)
    return app
