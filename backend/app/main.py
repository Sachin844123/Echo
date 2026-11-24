"""Application factory with no database mutation at import time."""

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from app import __version__
from app.api.health import router
from app.api.ingestion import router as ingestion_router, import_failure_handler
from app.core.config import REPO_ROOT, Settings
from app.database.engine import create_session_factory, create_sqlite_engine
from app.database.migrate import check_database
from app.security.middleware import LocalSecurityMiddleware
from app.ingestion.errors import ImportFailure
from app.ingestion.service import IngestionService
from app.api.search import router as search_router, retrieval_failure_handler
from app.api.sources import router as sources_router
from app.retrieval.engine import SearchEngine
from app.retrieval.errors import RetrievalFailure
from app.api.dashboard import router as dashboard_router, session_router
from app.api.storage import router as storage_router
from app.storage.indexing import LocalIndexing


logger = logging.getLogger("echo.app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    dashboard_session = SecretStr(secrets.token_urlsafe(32))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_sqlite_engine(settings.database_path)
        ingestion = None
        local_indexing = None
        try:
            if not settings.database_path.is_file():
                raise RuntimeError("database is missing; run python -m app migrate")
            await run_in_threadpool(check_database, engine)
            app.state.engine = engine
            app.state.session_factory = create_session_factory(engine)
            ingestion = IngestionService(engine, settings)
            app.state.search = SearchEngine(engine, settings, ingestion.mutation_lock, ingestion.store)
            ingestion.indexer = app.state.search
            await run_in_threadpool(ingestion.start)
            app.state.ingestion = ingestion
            local_indexing = LocalIndexing(ingestion)
            await run_in_threadpool(local_indexing.start)
            app.state.local_indexing = local_indexing
            logger.info("startup_complete")
            yield
        except Exception:
            logger.exception("startup_failed")
            raise
        finally:
            if local_indexing is not None:
                await run_in_threadpool(local_indexing.stop)
            if ingestion is not None:
                await run_in_threadpool(ingestion.stop)
            await run_in_threadpool(engine.dispose)
            logger.info("shutdown_complete")

    app = FastAPI(
        title="ECHO", version=__version__, lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None, debug=False,
    )
    app.state.dashboard_session = dashboard_session
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False, expose_headers=["X-Request-ID"], max_age=600,
    )
    app.add_middleware(LocalSecurityMiddleware, settings=settings, dashboard_session=dashboard_session)
    app.include_router(router)
    app.include_router(ingestion_router)
    app.include_router(search_router)
    app.include_router(sources_router)
    app.include_router(dashboard_router)
    app.include_router(session_router)
    app.include_router(storage_router)
    app.add_exception_handler(ImportFailure, import_failure_handler)
    app.add_exception_handler(RetrievalFailure, retrieval_failure_handler)

    async def invalid_request(request, error):
        # FastAPI's default validation response echoes untrusted parameter input.
        return JSONResponse({"error": {"code": "invalid_request", "message": "Check the request parameters."}}, status_code=422)

    app.add_exception_handler(RequestValidationError, invalid_request)
    dashboard = REPO_ROOT / "frontend" / "dist"

    @app.api_route("/", methods=["GET", "HEAD"])
    def shell():
        if not (dashboard / "index.html").is_file():
            return JSONResponse({"detail": "Build the local dashboard with npm run build in frontend."}, status_code=503)
        return FileResponse(dashboard / "index.html")

    @app.api_route("/favicon.svg", methods=["GET", "HEAD"])
    def favicon():
        if not (dashboard / "favicon.svg").is_file():
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(dashboard / "favicon.svg", media_type="image/svg+xml")

    app.mount("/assets", StaticFiles(directory=dashboard / "assets", check_dir=False), name="assets")
    return app
