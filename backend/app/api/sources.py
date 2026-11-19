"""Local source references, bounded previews and collection membership."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.search import read_input
from app.api.search import SourceType
from app.database.models import Chunk, Collection, CollectionItem, Document, Source
from app.retrieval.errors import RetrievalFailure

router = APIRouter(prefix="/api/v1")


class TitleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("nonblank text required")
        return value.strip()


class CollectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        return TitleInput.nonblank(value)


def source_data(source):
    return {key: getattr(source, key) for key in (
        "id", "source_type", "title", "mime_type", "captured_at", "indexed_at", "processing_status", "created_at", "updated_at")}


def require_source(session, source_id):
    source = session.get(Source, source_id)
    if source is None or source.is_deleted:
        raise RetrievalFailure("not_found", 404)
    return source


@router.get("/sources")
def sources(request: Request, limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
            collection_id: int | None = Query(default=None, gt=0), source_type: SourceType | None = None):
    service = request.app.state.search
    with service.lock, service.sessions() as session:
        conditions = [Source.is_deleted.is_(False)]
        if collection_id is not None:
            conditions.append(Source.id.in_(select(CollectionItem.source_id).where(CollectionItem.collection_id == collection_id)))
        if source_type is not None:
            conditions.append(Source.source_type == source_type)
        items = session.scalars(select(Source).where(*conditions).order_by(Source.id.desc()).limit(limit).offset(offset))
        return {"items": [source_data(item) for item in items], "total": session.scalar(
            select(func.count()).select_from(Source).where(*conditions))}


@router.get("/sources/{source_id}")
def source(request: Request, source_id: int):
    service = request.app.state.search
    with service.lock, service.sessions() as session:
        result = source_data(require_source(session, source_id))
        result["collection_ids"] = list(session.scalars(select(CollectionItem.collection_id).where(CollectionItem.source_id == source_id)))
        return result


@router.patch("/sources/{source_id}")
async def rename(request: Request, source_id: int):
    values = await read_input(request, TitleInput)
    service = request.app.state.search

    def update():
        with service.lock, service.sessions.begin() as session:
            item = require_source(session, source_id)
            item.title = values.title
            session.flush()
            return source_data(item)
    return await run_in_threadpool(update)


@router.delete("/sources/{source_id}")
def remove_source(request: Request, source_id: int):
    done = request.app.state.search.delete_source(source_id)
    request.app.state.ingestion.wake.set()
    return JSONResponse({"source_id": source_id, "status": "deleted" if done else "deletion_pending"}, status_code=200 if done else 202)


@router.get("/sources/{source_id}/document")
def document(request: Request, source_id: int, offset: int = Query(default=0, ge=0), length: int = Query(default=4000, ge=1, le=20000)):
    service = request.app.state.search
    with service.lock, service.sessions() as session:
        require_source(session, source_id)
        row = session.execute(select(Document.id, Document.content_length, Document.extraction_status,
            func.substr(Document.extracted_text, offset + 1, length)).where(Document.source_id == source_id)).first()
        if row is None:
            raise RetrievalFailure("not_found", 404)
        return {"document_id": row[0], "content_length": row[1], "extraction_status": row[2],
                "text": row[3], "offset": offset, "has_more": offset + length < row[1]}


@router.get("/sources/{source_id}/chunks")
def chunks(request: Request, source_id: int, offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
    service = request.app.state.search
    with service.lock, service.sessions() as session:
        require_source(session, source_id)
        rows = session.scalars(select(Chunk).join(Document).where(Document.source_id == source_id).order_by(Chunk.chunk_index).offset(offset).limit(limit))
        return {"items": [{key: getattr(chunk, key) for key in ("id", "chunk_index", "chunk_text", "token_count", "page_number", "heading", "start_offset", "end_offset")} for chunk in rows]}


@router.get("/collections")
def collections(request: Request, offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
    service = request.app.state.search
    with service.lock, service.sessions() as session:
        rows = session.scalars(select(Collection).order_by(Collection.id).offset(offset).limit(limit))
        counts = dict(session.execute(select(CollectionItem.collection_id, func.count()).join(Source).where(
            Source.is_deleted.is_(False)).group_by(CollectionItem.collection_id)).all())
        return {"items": [{"id": row.id, "name": row.name, "description": row.description, "source_count": counts.get(row.id, 0)} for row in rows],
                "total": session.scalar(select(func.count()).select_from(Collection))}


@router.post("/collections", status_code=201)
async def create_collection(request: Request):
    values = await read_input(request, CollectionInput)
    service = request.app.state.search

    def create():
        try:
            with service.lock, service.sessions.begin() as session:
                item = Collection(**values.model_dump())
                session.add(item)
                session.flush()
                return {"id": item.id, "name": item.name, "description": item.description}
        except IntegrityError:
            raise RetrievalFailure("conflict", 409) from None
    return await run_in_threadpool(create)


@router.delete("/collections/{collection_id}")
def delete_collection(request: Request, collection_id: int):
    service = request.app.state.search
    with service.lock, service.sessions.begin() as session:
        collection = session.get(Collection, collection_id)
        if collection is None:
            raise RetrievalFailure("not_found", 404)
        session.delete(collection)
    return {"status": "deleted"}


@router.put("/collections/{collection_id}/sources/{source_id}")
def add_member(request: Request, collection_id: int, source_id: int):
    service = request.app.state.search
    with service.lock, service.sessions.begin() as session:
        require_source(session, source_id)
        if session.get(Collection, collection_id) is None:
            raise RetrievalFailure("not_found", 404)
        if session.get(CollectionItem, (collection_id, source_id)) is None:
            session.add(CollectionItem(collection_id=collection_id, source_id=source_id))
    return {"collection_id": collection_id, "source_id": source_id}


@router.delete("/collections/{collection_id}/sources/{source_id}")
def remove_member(request: Request, collection_id: int, source_id: int):
    service = request.app.state.search
    with service.lock, service.sessions.begin() as session:
        session.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection_id, CollectionItem.source_id == source_id))
    return {"status": "removed"}
