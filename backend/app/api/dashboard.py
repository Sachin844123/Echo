"""Safe dashboard configuration and recoverable, explicitly confirmed library reset."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select, update
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app import __version__
from app.api.search import read_input
from app.database.models import AppSetting, Collection, Source
from app.extraction.ocr import ocr_status

router = APIRouter(prefix="/api/v1")


class DeleteLibraryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    confirmation: Literal["DELETE ALL"]


@router.post("/session/check")
async def check_session():
    """Check authentication and browser Origin without accepting document content.

    POST makes browsers send Origin, including through the development proxy.
    The security middleware performs both checks before this handler runs.
    """
    return {"status": "ok"}


@router.get("/settings")
def settings(request: Request):
    config = request.app.state.search.settings
    return {"version": __version__, "search_history_enabled": False,
            "max_upload_bytes": config.max_upload_bytes,
            "supported_types": ["pdf", "txt", "markdown", "docx", "note", "image"],
            "ocr": ocr_status(config),
            "retrieval": {name: getattr(config, name) for name in (
                "chunk_tokens", "chunk_overlap", "candidate_pool", "result_limit", "rrf_k",
                "embedding_model_name", "embedding_batch_size", "retrieval_profile", "spelling_correction", "candidate_scan_limit")},
            "rerank_weights": config.rerank_weights.model_dump()}


@router.delete("/library")
async def delete_library(request: Request):
    await read_input(request, DeleteLibraryInput)
    service, search = request.app.state.ingestion, request.app.state.search

    def reset():
        with service.mutation_lock:
            # Reject uploads that began before reset but have not yet published.
            service.import_generation += 1
            with search.sessions.begin() as session:
                session.execute(update(Source).values(is_deleted=True))
                session.execute(delete(Collection))
                session.execute(delete(AppSetting))
            # Durable tombstones use the same crash-recovery path as single deletion.
            search.finish_deletions()
            with search.sessions() as session:
                pending = session.scalar(select(func.count()).select_from(Source))
            service.wake.set()
            return pending

    pending = await run_in_threadpool(reset)
    return JSONResponse({"status": "deletion_pending" if pending else "deleted", "deletions_pending": pending},
                        status_code=202 if pending else 200)
