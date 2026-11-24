"""Recoverable source-ID FAISS index for explicitly imported raster images."""

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select

from app.database.models import Document, ImageEmbeddingRecord, IndexingJob, Source
from app.embeddings.visual import VisualEncoder
from app.retrieval.errors import RetrievalFailure
from app.retrieval.vectors import VectorStore


def refresh_image_status(session, source):
    if source.source_type != "image":
        return
    session.flush()
    latest = {}
    for job in session.scalars(select(IndexingJob).where(IndexingJob.source_id == source.id).order_by(IndexingJob.id.desc())):
        latest.setdefault(job.stage, job.status)
    states = set(latest.values())
    source.processing_status = "failed" if "failed" in states else ("pending" if states & {"pending", "running"} else "indexed")
    source.indexed_at = (source.indexed_at or datetime.now(timezone.utc)) if source.processing_status == "indexed" else None


class VisualIndex:
    def __init__(self, owner):
        self.owner = owner
        self.encoder = VisualEncoder(owner.settings)
        self.vectors = VectorStore(owner.settings.data_dir / "visual-vectors")

    def identity(self):
        if not self.owner.settings.visual_indexing_enabled:
            raise RetrievalFailure("visual_disabled")
        identity = self.encoder.identity
        if self.vectors.identity is not None and self.vectors.identity != identity:
            raise RetrievalFailure("model_mismatch")
        return identity

    def reconcile(self):
        self.vectors.load()
        if not self.owner.settings.visual_indexing_enabled:
            return
        try:
            identity = self.identity()
        except RetrievalFailure:
            identity = None
        if identity is not None and self.vectors.index is None:
            self.vectors.reset(identity)
            self.vectors.save()
        with self.owner.sessions.begin() as session:
            valid = set()
            stored = self.vectors.identity
            vector_ids = self.vectors.ids
            for record, source in session.execute(select(ImageEmbeddingRecord, Source).join(Source)).yield_per(100):
                if (stored is not None and record.source_id in vector_ids and not source.is_deleted
                        and source.source_type == "image" and source.content_hash == record.content_hash
                        and (record.model_name, record.model_version, record.dimension) == (stored.name, stored.version, stored.dimension)):
                    valid.add(source.id)
                else:
                    session.delete(record)
            if self.vectors.index is not None and vector_ids - valid:
                self.vectors.remove(vector_ids - valid)
                self.vectors.save()
            for source in session.scalars(select(Source).join(Document).where(Source.source_type == "image",
                    Source.is_deleted.is_(False), Document.extraction_status == "complete")):
                if source.id not in valid:
                    last = session.scalar(select(IndexingJob).where(IndexingJob.source_id == source.id,
                        IndexingJob.stage == "visual").order_by(IndexingJob.id.desc()).limit(1))
                    if last is None or last.status == "succeeded":
                        session.add(IndexingJob(source_id=source.id, stage="visual"))
                        source.processing_status, source.indexed_at = "pending", None

    def remove(self, source_id):
        if source_id in self.vectors.ids:
            self.vectors.remove({source_id})
            self.vectors.save()
        elif self.vectors.corrupt:
            self.vectors.discard_corrupt()

    def index_source(self, job_id, source_id, stopping):
        try:
            with self.owner.lock, self.owner.sessions() as session:
                identity = self.identity()
                source = session.get(Source, source_id)
                if source is None or source.is_deleted:
                    return
                path = self.owner.files.resolve(source.file_path)
                content_hash = source.content_hash
            if stopping.is_set() or path.stat().st_size > self.owner.settings.max_upload_bytes:
                raise RetrievalFailure("indexing_failed")
            # File verification and inference must not block unrelated keyword searches.
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != content_hash:
                    raise RetrievalFailure("indexing_failed")
            values = self.encoder.encode_image(path)
            with self.owner.lock:
                with self.owner.sessions.begin() as session:
                    source, job = session.get(Source, source_id), session.get(IndexingJob, job_id)
                    if source is None or source.is_deleted or job is None or job.status != "running":
                        return
                    if stopping.is_set() or source.content_hash != content_hash:
                        raise RetrievalFailure("indexing_failed")
                    if self.vectors.index is None:
                        self.vectors.reset(identity)
                    self.vectors.add([source_id], values)
                    self.vectors.save()
                    session.merge(ImageEmbeddingRecord(source_id=source_id, model_name=identity.name,
                        model_version=identity.version, dimension=identity.dimension, content_hash=source.content_hash))
                    job.status, job.error = "succeeded", None
                    refresh_image_status(session, source)
        except Exception as error:
            with self.owner.lock:
                self.vectors.load()
                with self.owner.sessions.begin() as session:
                    source, job = session.get(Source, source_id), session.get(IndexingJob, job_id)
                    if source is not None and not source.is_deleted and job is not None:
                        job.status = "pending" if stopping.is_set() and job.attempts < self.owner.settings.max_job_attempts else "failed"
                        job.error = error.code if isinstance(error, RetrievalFailure) else "indexing_failed"
                        refresh_image_status(session, source)

    def search(self, text, allowed, limit):
        identity = self.identity()
        if self.vectors.index is None:
            raise RetrievalFailure("index_unavailable")
        with self.owner.sessions() as session:
            valid = set(session.scalars(select(ImageEmbeddingRecord.source_id).where(
                ImageEmbeddingRecord.model_name == identity.name, ImageEmbeddingRecord.model_version == identity.version)))
        candidates = allowed & valid
        if not candidates:
            return []
        return self.vectors.search(self.encoder.encode_text(text), candidates, limit)

    def status(self):
        try:
            self.identity()
            error = None if self.vectors.index is not None else "index_unavailable"
        except RetrievalFailure as failure:
            error = failure.code
        return {"available": error is None, "error": error, "image_count": len(self.vectors.ids)}
