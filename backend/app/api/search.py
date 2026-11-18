"""Bounded search requests with explicit retrieval modes and inclusive date filters."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from app.api.ingestion import body_blocks
from app.retrieval.errors import MESSAGES, RetrievalFailure

router = APIRouter(prefix="/api/v1")
SourceType = Literal["pdf", "txt", "markdown", "docx", "note"]


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    limit: int | None = Field(default=None, ge=1, le=50)
    source_types: list[SourceType] = Field(default_factory=list, max_length=5)
    captured_from: datetime | None = None
    captured_to: datetime | None = None
    collection_id: int | None = Field(default=None, gt=0)

    @field_validator("query")
    @classmethod
    def meaningful(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("query must be nonblank")
        return value.strip()

    @model_validator(mode="after")
    def date_range(self):
        for value in (self.captured_from, self.captured_to):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("date filters require a timezone")
        if self.captured_from and self.captured_to and self.captured_from > self.captured_to:
            raise ValueError("invalid date range")
        return self


async def read_input(request, model):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise RetrievalFailure("invalid_request", 415)
    data = bytearray()
    async for block in body_blocks(request, 16384):
        data.extend(block)
    try:
        return model.model_validate_json(data)
    except (ValidationError, ValueError):
        raise RetrievalFailure("invalid_request", 422) from None


async def retrieval_failure_handler(request, error):
    return JSONResponse({"error": {"code": error.code, "message": MESSAGES[error.code]}}, status_code=error.status)


@router.post("/search")
async def search(request: Request):
    query = await read_input(request, SearchInput)
    return await run_in_threadpool(request.app.state.search.search, query)


@router.get("/index/status")
def index_status(request: Request):
    return request.app.state.search.status()
