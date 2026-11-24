"""Normalized foundation schema; UTC timestamps and DB-enforced invariants."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, MetaData, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """SQLite stores naive UTC; Python callers receive aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.current_timestamp())


class UpdatedAt(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class Source(UpdatedAt, Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("source_type IN ('pdf','txt','markdown','docx','note','image')", name="source_type"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        CheckConstraint("length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'", name="sha256"),
        CheckConstraint("processing_status IN ('pending','processing','indexed','failed')", name="processing_status"),
        CheckConstraint("is_deleted IN (0,1)", name="is_deleted"),
        Index("ix_sources_type_captured", "source_type", "captured_at"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text)
    original_url: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.current_timestamp(), index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processing_status: Mapped[str] = mapped_column(String(20), server_default="pending", index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default="0", index=True)


class Document(CreatedAt, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("extraction_status IN ('pending','complete','failed')", name="extraction_status"),
        CheckConstraint("content_length >= 0", name="content_length"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), unique=True)
    extracted_text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(35))
    extraction_method: Mapped[str] = mapped_column(String(50))
    extraction_status: Mapped[str] = mapped_column(String(20), server_default="pending")
    content_length: Mapped[int] = mapped_column(Integer)


class Chunk(CreatedAt, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index"),
        CheckConstraint("length(trim(chunk_text)) > 0", name="text_not_blank"),
        CheckConstraint("token_count > 0", name="token_count"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="page_number"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="offsets"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)


class EmbeddingRecord(CreatedAt, Base):
    __tablename__ = "embedding_records"
    __table_args__ = (
        CheckConstraint("dimension > 0", name="dimension"),
        CheckConstraint("vector_index_id = chunk_id", name="vector_is_chunk_id"),
        CheckConstraint("length(trim(model_name)) > 0 AND length(trim(model_version)) > 0", name="model_identity"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), unique=True)
    model_name: Mapped[str] = mapped_column(String(200))
    model_version: Mapped[str] = mapped_column(String(100))
    vector_index_id: Mapped[int] = mapped_column(Integer, unique=True)
    dimension: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), server_default="")


class Collection(UpdatedAt, Base):
    __tablename__ = "collections"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="name_not_blank"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class ImageEmbeddingRecord(CreatedAt, Base):
    __tablename__ = "image_embedding_records"
    __table_args__ = (CheckConstraint("dimension > 0", name="dimension"),)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(200))
    model_version: Mapped[str] = mapped_column(String(100))
    dimension: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))


class CollectionItem(CreatedAt, Base):
    __tablename__ = "collection_items"
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True, index=True)


class IndexingJob(UpdatedAt, Base):
    __tablename__ = "indexing_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending','running','succeeded','failed')", name="status"),
        CheckConstraint("attempts >= 0", name="attempts"),
        Index("ix_indexing_jobs_status_created", "status", "created_at"),
        Index("ix_indexing_jobs_stage_status", "stage", "status"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    stage: Mapped[str] = mapped_column(String(20), CheckConstraint("stage IN ('ingestion','indexing','visual')", name="stage"), server_default="ingestion")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)


class AppSetting(UpdatedAt, Base):
    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("length(trim(key)) > 0", name="key_not_blank"),)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
