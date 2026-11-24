"""Authenticated control plane for explicit local indexing consent."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.api.search import read_input
from app.database.models import LocalFile, Source
from app.storage.access import SUPPORTED_EXTENSIONS

router = APIRouter(prefix="/api/v1/storage")
Folder = Annotated[str, Field(min_length=1, max_length=1024)]
MESSAGES = {
    "invalid_path": "Use absolute paths to local folders, without parent traversal or network shares.",
    "folder_unavailable": "A selected folder is missing, protected or not on a fixed local drive.",
    "no_approved_folders": "No eligible folders are available. Select a local folder or deny access.",
    "exclusion_outside_scope": "Each exclusion must be inside an approved folder.",
}


class PermissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    mode: Literal["all", "personal", "selected", "deny"]
    confirm: Literal[True]
    folders: list[Folder] = Field(default_factory=list, max_length=32)
    exclusions: list[Folder] = Field(default_factory=list, max_length=64)
    extensions: list[str] = Field(default_factory=lambda: list(SUPPORTED_EXTENSIONS), min_length=1, max_length=len(SUPPORTED_EXTENSIONS))

    @model_validator(mode="after")
    def validate_scope(self):
        if bool(self.folders) != (self.mode == "selected") or any(ext not in SUPPORTED_EXTENSIONS for ext in self.extensions):
            raise ValueError("invalid_scope")
        return self


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    action: Literal["pause", "resume", "cancel", "rescan"]


def invalid(error):
    code = str(error)
    if code not in MESSAGES:
        code = "invalid_path"
    return JSONResponse({"error": {"code": code, "message": MESSAGES[code]}}, status_code=422)


@router.get("")
def status(request: Request):
    return request.app.state.local_indexing.status()


@router.get("/options")
def options(request: Request):
    return request.app.state.local_indexing.options()


@router.put("/permission")
async def permission(request: Request):
    data = await read_input(request, PermissionInput)
    try:
        return await run_in_threadpool(request.app.state.local_indexing.configure, data.mode, data.folders,
                                       data.exclusions, data.extensions)
    except ValueError as error:
        return invalid(error)


@router.post("/control")
async def control(request: Request):
    data = await read_input(request, ControlInput)
    try:
        return await run_in_threadpool(request.app.state.local_indexing.control, data.action)
    except ValueError as error:
        return invalid(error)


@router.get("/files")
def files(request: Request, offset: int = Query(default=0, ge=0, le=10000), limit: int = Query(default=30, ge=1, le=100)):
    with request.app.state.local_indexing.sessions() as session:
        count = session.scalar(select(func.count()).select_from(LocalFile).join(Source).where(Source.is_deleted.is_(False)))
        rows = session.execute(select(LocalFile.path, LocalFile.size_bytes, Source.id, Source.processing_status)
            .join(Source, LocalFile.source_id == Source.id).where(Source.is_deleted.is_(False))
            .order_by(LocalFile.path).offset(offset).limit(limit)).all()
    return {"total": count, "items": [{"path": path, "bytes": size, "source_id": source_id, "status": status}
                                     for path, size, source_id, status in rows]}
