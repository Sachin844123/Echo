"""Local retrieval and recovery across SQLite and the FAISS snapshot boundary."""

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, text

from app.database.engine import create_session_factory
from app.database.fts import reconcile_fts
from app.database.models import Chunk, CollectionItem, Document, EmbeddingRecord, IndexingJob, Source
from app.embeddings.local import LocalEncoder
from app.retrieval.errors import RetrievalFailure
from app.retrieval.vectors import VectorStore


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def reciprocal_rank_fusion(keyword, semantic, k: int = 60):
    scores = {}
    for hits in (keyword, semantic):
        for rank, (chunk_id, _) in enumerate(hits, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


class SearchEngine:
    def __init__(self, engine, settings, lock, files, encoder=None):
        self.engine, self.settings, self.lock, self.files = engine, settings, lock, files
        self.sessions = create_session_factory(engine)
        self.encoder = encoder if encoder is not None else LocalEncoder(settings)
        self.vectors = VectorStore(settings.data_dir / "vectors")
        self.model_error = None

    def _identity(self):
        identity = self.encoder.identity
        if self.vectors.identity is not None and self.vectors.identity != identity:
            raise RetrievalFailure("model_mismatch")
        return identity

    def reconcile(self):
        """Run exclusively at startup. A different configured model requires explicit rebuild."""
        with self.lock:
            with self.engine.begin() as connection:
                reconcile_fts(connection)
            self.vectors.load()
            self.finish_deletions()
            try:
                identity = self._identity()
                self.model_error = None
            except RetrievalFailure as error:
                self.model_error = error.code
                identity = None
            if identity is not None and self.vectors.index is None:
                self.vectors.reset(identity)
                self.vectors.save()
            # Metadata is trusted only when all three stores agree on content and identity.
            valid = set()
            with self.sessions.begin() as session:
                records = session.execute(select(EmbeddingRecord, Chunk.chunk_text).join(Chunk)).yield_per(100)
                stored = self.vectors.identity
                vector_ids = self.vectors.ids
                for record, content in records:
                    if (stored is not None and record.chunk_id in vector_ids
                            and record.model_name == stored.name and record.model_version == stored.version
                            and record.dimension == stored.dimension and record.content_hash == digest(content)):
                        valid.add(record.chunk_id)
                    else:
                        session.delete(record)
                if self.vectors.index is not None and vector_ids - valid:
                    self.vectors.remove(vector_ids - valid)
                    self.vectors.save()
                session.flush()
                sources = session.scalars(select(Source).join(Document).where(
                    Source.is_deleted.is_(False), Document.extraction_status == "complete"))
                for source in sources:
                    missing = session.scalar(select(func.count()).select_from(Chunk).join(Document).where(
                        Document.source_id == source.id, ~Chunk.id.in_(select(EmbeddingRecord.chunk_id))))
                    if missing:
                        source.indexed_at = None
                        last = session.scalar(select(IndexingJob).where(IndexingJob.source_id == source.id,
                            IndexingJob.stage == "indexing").order_by(IndexingJob.id.desc()).limit(1))
                        if last is None or last.status == "succeeded":
                            session.add(IndexingJob(source_id=source.id, stage="indexing"))
                            source.processing_status = "pending"
                    elif identity is not None:
                        source.processing_status = "indexed"
                        source.indexed_at = source.indexed_at or datetime.now(timezone.utc)

    def index_source(self, job_id: int, source_id: int, stopping):
        with self.lock:
            try:
                identity = self._identity()
                if self.vectors.index is None:
                    self.vectors.reset(identity)
                with self.sessions.begin() as session:
                    source = session.get(Source, source_id)
                    job = session.get(IndexingJob, job_id)
                    if source is None or source.is_deleted or job is None:
                        return
                    ids = set(session.scalars(select(Chunk.id).join(Document).where(Document.source_id == source_id)))
                    self.vectors.remove(ids)
                    session.execute(delete(EmbeddingRecord).where(EmbeddingRecord.chunk_id.in_(
                        select(Chunk.id).join(Document).where(Document.source_id == source_id))))
                    last_id = 0
                    while True:
                        if stopping.is_set():
                            raise RetrievalFailure("indexing_failed")
                        chunks = session.scalars(select(Chunk).join(Document).where(
                            Document.source_id == source_id, Chunk.id > last_id).order_by(Chunk.id)
                            .limit(self.settings.embedding_batch_size)).all()
                        if not chunks:
                            break
                        values = self.encoder.encode([chunk.chunk_text for chunk in chunks])
                        self.vectors.add([chunk.id for chunk in chunks], values)
                        session.add_all([EmbeddingRecord(chunk_id=chunk.id, vector_index_id=chunk.id,
                            model_name=identity.name, model_version=identity.version, dimension=identity.dimension,
                            content_hash=digest(chunk.chunk_text)) for chunk in chunks])
                        session.flush()
                        last_id = chunks[-1].id
                    # Persist vectors before committing metadata. Reconciliation removes orphans.
                    self.vectors.save()
                    source.processing_status = "indexed"
                    source.indexed_at = datetime.now(timezone.utc)
                    job.status, job.error = "succeeded", None
                self.model_error = None
            except Exception as error:
                self.vectors.load()
                code = error.code if isinstance(error, RetrievalFailure) else "indexing_failed"
                with self.sessions.begin() as session:
                    job, source = session.get(IndexingJob, job_id), session.get(Source, source_id)
                    if job is not None and source is not None:
                        job.status = "pending" if stopping.is_set() and job.attempts < self.settings.max_job_attempts else "failed"
                        job.error = code
                        source.processing_status = "pending" if job.status == "pending" else "failed"
                        source.indexed_at = None
                self.model_error = code

    def rebuild(self):
        """Explicit operator action, under the process lock; never downloads a model."""
        with self.lock:
            identity = self.encoder.identity
            self.vectors.reset(identity)
            self.vectors.save()
            with self.sessions.begin() as session:
                session.execute(delete(EmbeddingRecord))
                session.execute(delete(IndexingJob).where(IndexingJob.stage == "indexing"))
                for source in session.scalars(select(Source).join(Document).where(
                        Source.is_deleted.is_(False), Document.extraction_status == "complete")):
                    source.processing_status, source.indexed_at = "pending", None
                    session.add(IndexingJob(source_id=source.id, stage="indexing"))

    def delete_source(self, source_id: int) -> bool:
        with self.lock:
            with self.sessions.begin() as session:
                source = session.get(Source, source_id)
                if source is None:
                    raise RetrievalFailure("not_found", 404)
                source.is_deleted = True  # Durable intent, immediately excluded from retrieval.
            return self._finish_delete(source_id)

    def _finish_delete(self, source_id: int) -> bool:
        try:
            with self.sessions.begin() as session:
                source = session.get(Source, source_id)
                if source is None:
                    return True
                ids = set(session.scalars(select(Chunk.id).join(Document).where(Document.source_id == source_id)))
                self.vectors.remove(ids)
                if self.vectors.index is not None:
                    self.vectors.save()
                elif self.vectors.corrupt:
                    self.vectors.discard_corrupt()
                if source.file_path is not None:
                    self.files.remove(source.file_path)
                session.delete(source)
            return True
        except Exception:
            self.vectors.load()
            return False  # Tombstone remains durable; worker/startup retries file/IO failures.

    def finish_deletions(self):
        with self.lock:
            with self.sessions() as session:
                ids = list(session.scalars(select(Source.id).where(Source.is_deleted.is_(True))))
            for source_id in ids:
                self._finish_delete(source_id)

    def status(self):
        with self.lock, self.sessions() as session:
            try:
                self._identity()
                error = "index_unavailable" if self.vectors.index is None else None
            except RetrievalFailure as failure:
                error = failure.code
            counts = dict(session.execute(select(Source.processing_status, func.count()).where(
                Source.is_deleted.is_(False)).group_by(Source.processing_status)).all())
            return {"model_name": self.settings.embedding_model_name, "semantic_available": error is None,
                    "error": error, "vector_count": len(self.vectors.ids), "sources_by_status": counts,
                    "deletions_pending": session.scalar(select(func.count()).select_from(Source).where(Source.is_deleted.is_(True))),
                    "indexing_incomplete": any(counts.get(key, 0) for key in ("pending", "processing", "failed"))}

    def search(self, query):
        with self.lock, self.sessions() as session:
            pool = self.settings.candidate_pool
            limit = query.limit or self.settings.result_limit
            if limit > pool:
                raise RetrievalFailure("invalid_request", 422)
            eligible = select(Chunk.id).join(Document).join(Source).where(
                Source.is_deleted.is_(False), Document.extraction_status == "complete")
            if query.source_types:
                eligible = eligible.where(Source.source_type.in_(query.source_types))
            if query.captured_from:
                eligible = eligible.where(Source.captured_at >= query.captured_from)
            if query.captured_to:
                eligible = eligible.where(Source.captured_at <= query.captured_to)
            if query.collection_id:
                eligible = eligible.where(Source.id.in_(select(CollectionItem.source_id).where(
                    CollectionItem.collection_id == query.collection_id)))
            keyword, semantic = [], []
            if query.mode in ("keyword", "hybrid"):
                tokens = list(dict.fromkeys(re.findall(r"\w+", query.query, flags=re.UNICODE)))
                if tokens:
                    # Quotes make every token literal; user text is never FTS query syntax.
                    expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
                    fts = text("SELECT rowid AS id, bm25(chunk_fts) AS score FROM chunk_fts WHERE chunk_fts MATCH :match").columns(id=Chunk.id.type, score=Chunk.token_count.type).subquery()
                    rows = session.execute(select(fts.c.id, fts.c.score).where(fts.c.id.in_(eligible))
                        .order_by(fts.c.score, fts.c.id).limit(pool), {"match": expression}).all()
                    keyword = [(key, float(score)) for key, score in rows]
            if query.mode in ("semantic", "hybrid"):
                identity = self._identity()
                if self.vectors.index is None:
                    raise RetrievalFailure("index_unavailable")
                valid = eligible.where(Chunk.id.in_(select(EmbeddingRecord.chunk_id).where(
                    EmbeddingRecord.model_name == identity.name, EmbeddingRecord.model_version == identity.version)))
                semantic = self.vectors.search(self.encoder.encode([query.query]), set(session.scalars(valid)), pool)
            if query.mode == "hybrid":
                hits = reciprocal_rank_fusion(keyword, semantic, self.settings.rrf_k)
            elif query.mode == "keyword":
                hits = [(key, -score) for key, score in keyword]
            else:
                hits = semantic
            keyword_ranks = {key: rank for rank, (key, _) in enumerate(keyword, 1)}
            semantic_ranks = {key: rank for rank, (key, _) in enumerate(semantic, 1)}
            seen, results = set(), []
            for chunk_id, score in hits:
                chunk, source = session.execute(select(Chunk, Source).join(Document, Chunk.document_id == Document.id).join(Source, Document.source_id == Source.id)
                    .where(Chunk.id == chunk_id)).one()
                if source.id in seen:
                    continue
                seen.add(source.id)
                results.append({"source_id": source.id, "title": source.title, "source_type": source.source_type,
                    "captured_at": source.captured_at, "chunk_id": chunk.id, "document_id": chunk.document_id,
                    "excerpt": chunk.chunk_text, "page_number": chunk.page_number, "heading": chunk.heading,
                    "start_offset": chunk.start_offset, "end_offset": chunk.end_offset,
                    "score": score, "keyword_rank": keyword_ranks.get(chunk_id), "semantic_rank": semantic_ranks.get(chunk_id)})
                if len(results) >= limit:
                    break
            return {"mode": query.mode, "results": results, "candidate_counts": {"keyword": len(keyword), "semantic": len(semantic)},
                    "indexing_incomplete": self.status()["indexing_incomplete"]}
