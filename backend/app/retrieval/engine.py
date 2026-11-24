"""Local retrieval and recovery across SQLite and the FAISS snapshot boundary."""

import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, text

from app.database.engine import create_session_factory
from app.database.fts import reconcile_fts
from app.database.models import Chunk, CollectionItem, Document, EmbeddingRecord, ImageEmbeddingRecord, IndexingJob, Source
from app.embeddings.local import LocalEncoder
from app.retrieval.errors import RetrievalFailure
from app.ingestion.errors import ImportFailure
from app.retrieval.vectors import VectorStore
from app.retrieval.reranking import Candidate, RERANK_VERSION, rerank
from app.retrieval.visual import VisualIndex, refresh_image_status
from app.retrieval.query import correct_query


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
        self.visual = VisualIndex(self)

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
            self.visual.reconcile()
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
                    refresh_image_status(session, source)

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
                    refresh_image_status(session, source)
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
                        refresh_image_status(session, source)
                self.model_error = code

    def rebuild(self):
        """Explicit operator action, under the process lock; never downloads a model."""
        with self.lock:
            identity = self.encoder.identity
            with self.sessions() as session:
                has_images = session.scalar(select(Source.id).where(Source.source_type == "image", Source.is_deleted.is_(False)).limit(1)) is not None
            visual_identity = self.visual.encoder.identity if has_images and self.settings.visual_indexing_enabled else None
            self.vectors.reset(identity)
            self.vectors.save()
            if visual_identity is not None:
                self.visual.vectors.reset(visual_identity)
                self.visual.vectors.save()
            with self.sessions.begin() as session:
                session.execute(delete(EmbeddingRecord))
                if visual_identity is not None:
                    session.execute(delete(ImageEmbeddingRecord))
                session.execute(delete(IndexingJob).where(IndexingJob.stage.in_(["indexing", "visual"])))
                for source in session.scalars(select(Source).join(Document).where(
                        Source.is_deleted.is_(False), Document.extraction_status == "complete")):
                    source.processing_status, source.indexed_at = "pending", None
                    session.add(IndexingJob(source_id=source.id, stage="indexing"))
                    if source.source_type == "image" and visual_identity is not None:
                        session.add(IndexingJob(source_id=source.id, stage="visual"))

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
                self.visual.remove(source_id)
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
            self.visual.vectors.load()
            return False  # Tombstone remains durable; worker/startup retries file/IO failures.

    def finish_deletions(self):
        # A permission revocation can tombstone thousands of sources. Persist
        # each vector snapshot once per bounded batch while retaining retries.
        last = 0
        while True:
            with self.lock:
                with self.sessions() as session:
                    batch = list(session.scalars(select(Source.id).where(
                        Source.is_deleted.is_(True), Source.id > last).order_by(Source.id).limit(64)))
                if not batch:
                    return
                last = batch[-1]
                if len(batch) == 1:
                    self._finish_delete(last)
                    continue
                self._finish_deletion_batch(batch)

    def _finish_deletion_batch(self, batch):
        try:
            with self.sessions.begin() as session:
                chunk_ids = set(session.scalars(select(Chunk.id).join(Document).where(Document.source_id.in_(batch))))
                for store, remove_ids in ((self.vectors, chunk_ids), (self.visual.vectors, set(batch))):
                    present = store.ids & remove_ids
                    if present:
                        store.remove(present)
                        store.save()
                    elif store.corrupt:
                        store.discard_corrupt()
                for source in session.scalars(select(Source).where(Source.id.in_(batch))):
                    try:
                        if source.file_path:
                            self.files.remove(source.file_path)
                    except (OSError, ImportFailure):
                        continue  # The tombstone is retried independently of the rest.
                    session.delete(source)
        except Exception:
            self.vectors.load()
            self.visual.vectors.load()

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
                    "visual": self.visual.status(),
                    "spelling_correction": self.settings.spelling_correction,
                    "error": error, "vector_count": len(self.vectors.ids), "sources_by_status": counts,
                    "deletions_pending": session.scalar(select(func.count()).select_from(Source).where(Source.is_deleted.is_(True))),
                    "indexing_incomplete": any(counts.get(key, 0) for key in ("pending", "processing", "failed"))}

    def search(self, query):
        with self.lock, self.sessions() as session:
            pool = self.settings.candidate_pool
            balanced = self.settings.retrieval_profile == "source_balanced"
            scan = self.settings.candidate_scan_limit if balanced else pool
            spelling = self.settings.spelling_correction if query.correct_spelling is None else query.correct_spelling
            effective, corrections = correct_query(session, query.query) if spelling and query.mode != "visual" else (query.query, [])
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
            visual_hits = []
            if query.mode == "visual":
                allowed = set(session.scalars(select(Document.source_id).join(Chunk).join(Source).where(
                    Chunk.id.in_(eligible), Source.source_type == "image")))
                for source_id, score in self.visual.search(query.query, allowed, pool):
                    chunk_id = session.scalar(select(Chunk.id).join(Document).where(Document.source_id == source_id).order_by(Chunk.chunk_index).limit(1))
                    if chunk_id is not None:
                        visual_hits.append((chunk_id, score))
            if query.mode in ("keyword", "hybrid", "hybrid_contextual"):
                tokens = list(dict.fromkeys(re.findall(r"\w+", effective, flags=re.UNICODE)))
                if tokens:
                    # Quotes make every token literal; user text is never FTS query syntax.
                    expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
                    fts = text("SELECT rowid AS id, bm25(chunk_fts) AS score FROM chunk_fts WHERE chunk_fts MATCH :match").columns(id=Chunk.id.type, score=Chunk.token_count.type).subquery()
                    rows = session.execute(select(fts.c.id, fts.c.score).where(fts.c.id.in_(eligible))
                        .order_by(fts.c.score, fts.c.id).limit(scan), {"match": expression}).all()
                    keyword = [(key, float(score)) for key, score in rows]
            if query.mode in ("semantic", "hybrid", "hybrid_contextual"):
                identity = self._identity()
                if self.vectors.index is None:
                    raise RetrievalFailure("index_unavailable")
                valid = eligible.where(Chunk.id.in_(select(EmbeddingRecord.chunk_id).where(
                    EmbeddingRecord.model_name == identity.name, EmbeddingRecord.model_version == identity.version)))
                semantic = self.vectors.search(self.encoder.encode([effective]), set(session.scalars(valid)), scan)
            scan_truncated = len(keyword) == scan or len(semantic) == scan
            representatives = {}
            if balanced and (keyword or semantic):
                source_for = dict(session.execute(select(Chunk.id, Document.source_id).join(Document).where(
                    Chunk.id.in_([key for key, _ in keyword + semantic]))).all())

                def distinct(rows):
                    result, seen = [], set()
                    for key, score in rows:
                        source_id = source_for[key]
                        if source_id not in seen:
                            seen.add(source_id)
                            representatives.setdefault(source_id, key)
                            result.append((source_id, score))
                            if len(result) == pool:
                                break
                    return result
                keyword, semantic = distinct(keyword), distinct(semantic)
            if query.mode in ("hybrid", "hybrid_contextual"):
                hits = reciprocal_rank_fusion(keyword, semantic, self.settings.rrf_k)
            elif query.mode == "keyword":
                hits = [(key, -score) for key, score in keyword]
            elif query.mode == "visual":
                hits = visual_hits
            else:
                hits = semantic
            keyword_ranks = {key: rank for rank, (key, _) in enumerate(keyword, 1)}
            semantic_ranks = {key: rank for rank, (key, _) in enumerate(semantic, 1)}
            if balanced and query.mode in ("hybrid", "hybrid_contextual"):
                # Equal fusion evidence prefers the stronger literal match, then ID.
                hits.sort(key=lambda item: (-item[1], keyword_ranks.get(item[0], pool + 1), item[0]))
            if representatives:
                hits = [(representatives[key], score) for key, score in hits]
                keyword_ranks = {representatives[key]: rank for key, rank in keyword_ranks.items()}
                semantic_ranks = {representatives[key]: rank for key, rank in semantic_ranks.items()}
            reranked = {}
            candidate_rows = {}
            if query.mode == "hybrid_contextual" and hits:
                rows = session.execute(select(Chunk, Source).join(Document, Chunk.document_id == Document.id)
                    .join(Source, Document.source_id == Source.id).where(Chunk.id.in_([key for key, _ in hits]))).all()
                candidate_rows = {chunk.id: (chunk, source) for chunk, source in rows}
                collection_sources = set()
                if query.context.collection_id is not None:
                    collection_sources = set(session.scalars(select(CollectionItem.source_id).where(
                        CollectionItem.collection_id == query.context.collection_id,
                        CollectionItem.source_id.in_({source.id for _, source in rows}))))
                candidates = [Candidate(key, score, candidate_rows[key][1].title,
                    candidate_rows[key][0].heading, candidate_rows[key][0].chunk_text,
                    candidate_rows[key][1].source_type, candidate_rows[key][1].id in collection_sources)
                    for key, score in hits]
                ordered = rerank(candidates, effective, query.context.source_types, self.settings.rerank_weights, self.settings.rrf_k)
                if balanced:
                    ordered.sort(key=lambda hit: (-hit.score, -hit.rrf_score, keyword_ranks.get(hit.chunk_id, pool + 1), hit.chunk_id))
                reranked = {hit.chunk_id: hit for hit in ordered}
                hits = [(hit.chunk_id, hit.score) for hit in ordered]
            seen, results = set(), []
            for chunk_id, score in hits:
                if chunk_id in candidate_rows:
                    chunk, source = candidate_rows[chunk_id]
                else:
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
                if chunk_id in reranked:
                    results[-1].update(rrf_score=reranked[chunk_id].rrf_score, rerank_signals=reranked[chunk_id].signals)
                if len(results) >= limit:
                    break
            response = {"mode": query.mode, "results": results, "candidate_counts": {"keyword": len(keyword), "semantic": len(semantic)},
                        "query_analysis": {"effective_query": effective, "corrections": corrections, "spelling_enabled": spelling},
                        "retrieval_profile": self.settings.retrieval_profile, "candidate_scan_truncated": scan_truncated,
                        "indexing_incomplete": self.status()["indexing_incomplete"]}
            if query.mode == "hybrid_contextual":
                response["reranking"] = {"version": RERANK_VERSION, "weights": self.settings.rerank_weights.model_dump()}
            return response
