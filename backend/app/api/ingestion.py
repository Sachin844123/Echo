"""Authenticated streaming imports and durable-job observation/retry."""

import hashlib
import os

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from app.ingestion.errors import ERRORS, ImportFailure
from app.security.file_validation import safe_filename

router = APIRouter(prefix="/api/v1")
MAX_NOTE_BYTES = 1_000_000


class NoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000)

    @field_validator("title", "text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("nonblank text required")
        return value


async def import_failure_handler(request: Request, error: ImportFailure):
    return JSONResponse({"error": {"code": error.code, "message": ERRORS[error.code]}}, status_code=error.status)


async def body_blocks(request: Request, limit: int):
    lengths = request.headers.getlist("content-length")
    if lengths:
        try:
            if len(lengths) != 1 or int(lengths[0]) < 0:
                raise ValueError
            if int(lengths[0]) > limit:
                raise ImportFailure("file_too_large", 413)
        except ValueError:
            raise ImportFailure("file_too_large", 413) from None
    total = 0
    async for block in request.stream():
        total += len(block)
        if total > limit:
            raise ImportFailure("file_too_large", 413)
        yield block


def flush_file(stream):
    stream.flush()
    os.fsync(stream.fileno())


@router.post("/imports/files")
async def import_file(request: Request, filename: str = Query(min_length=1, max_length=240)):
    name = safe_filename(filename)
    service = request.app.state.ingestion
    staged = service.store.new_stage()
    digest = hashlib.sha256()
    try:
        with staged.open("xb") as stream:
            async for block in body_blocks(request, service.settings.max_upload_bytes):
                # Each network block is processed before reading the next one.
                await run_in_threadpool(stream.write, block)
                digest.update(block)
            await run_in_threadpool(flush_file, stream)
        result = await run_in_threadpool(service.enqueue, staged, name, digest.hexdigest())
        return JSONResponse(result, status_code=200 if result["duplicate"] else 202)
    except OSError:
        raise ImportFailure("storage_error", 503) from None
    finally:
        staged.unlink(missing_ok=True)


@router.post("/imports/notes")
async def import_note(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ImportFailure("invalid_note", 415)
    data = bytearray()
    async for block in body_blocks(request, MAX_NOTE_BYTES):
        data.extend(block)
    try:
        note = NoteInput.model_validate_json(data)
        content = note.text.encode("utf-8")
    except (ValidationError, ValueError, UnicodeError):
        raise ImportFailure("invalid_note") from None
    service = request.app.state.ingestion
    staged = service.store.new_stage()
    try:
        def save():
            with staged.open("xb") as stream:
                stream.write(content)
                flush_file(stream)
        await run_in_threadpool(save)
        result = await run_in_threadpool(service.enqueue, staged, "note.txt", hashlib.sha256(content).hexdigest(), note.title.strip())
        return JSONResponse(result, status_code=200 if result["duplicate"] else 202)
    except OSError:
        raise ImportFailure("storage_error", 503) from None
    finally:
        staged.unlink(missing_ok=True)


@router.get("/indexing-jobs")
def jobs(request: Request, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return request.app.state.ingestion.jobs(limit, offset)


@router.get("/indexing-jobs/{job_id}")
def job(request: Request, job_id: int):
    return request.app.state.ingestion.job(job_id)


@router.post("/indexing-jobs/{job_id}/retry", status_code=202)
def retry(request: Request, job_id: int):
    return request.app.state.ingestion.retry(job_id)
