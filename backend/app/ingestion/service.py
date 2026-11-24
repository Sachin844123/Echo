"""Durable single-worker ingestion with atomic publication and crash recovery."""

import io
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from sqlalchemy import Engine, delete, func, select

from app.core.config import REPO_ROOT, Settings
from app.database.engine import create_session_factory
from app.database.models import Chunk, Document, EmbeddingRecord, ImageEmbeddingRecord, IndexingJob, LocalAccess, Source
from app.ingestion.errors import ERRORS, ImportFailure
from app.retrieval.errors import MESSAGES, RetrievalFailure
from app.processing.chunking import iter_chunks, read_segments
from app.security.file_validation import MIMES, detect_file, safe_filename
from app.security.images import image_header
from app.storage.files import FileStore
from app.storage.instance_lock import InstanceLock

logger = logging.getLogger("echo.ingestion")


class IngestionService:
    def __init__(self, engine: Engine, settings: Settings):
        self.settings = settings
        self.sessions = create_session_factory(engine)
        self.store = FileStore(settings.data_dir)
        self.instance_lock = InstanceLock(settings.data_dir / "ingestion.lock")
        self.mutation_lock = threading.RLock()
        self.process_lock = threading.Lock()
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self.indexer = None
        self.import_generation = 0

    def start(self) -> None:
        self.instance_lock.acquire()
        try:
            self.store.prepare()
            self.recover()
            if self.indexer is not None:
                self.indexer.reconcile()
            self.thread = threading.Thread(target=self._loop, name="echo-ingestion", daemon=True)
            self.thread.start()
        except Exception:
            self.instance_lock.release()
            raise

    def stop(self) -> None:
        self.stopping.set()
        self.wake.set()
        with self.process_lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
        if self.thread is not None:
            # Wait for the current bounded embedding batch before releasing ownership.
            self.thread.join()
        self.instance_lock.release()

    def recover(self) -> None:
        """Called under the instance lock before the server accepts requests."""
        with self.mutation_lock, self.sessions.begin() as session:
            for job in session.scalars(select(IndexingJob).where(IndexingJob.status == "running")):
                source = session.get(Source, job.source_id)
                if job.attempts >= self.settings.max_job_attempts:
                    job.status, job.error = "failed", "interrupted"
                    source.processing_status = "failed"
                else:
                    job.status, job.error = "pending", None
                    source.processing_status = "pending"
            referenced = set(session.scalars(select(Source.file_path).where(Source.file_path.is_not(None))))
        self.store.recover_orphans(referenced)
        logger.info("jobs_recovered")

    def enqueue(self, staged: Path, filename: str, digest: str, note_title: str | None = None,
                expected_generation: int | None = None, *, register_local=None) -> dict:
        name = safe_filename(filename)
        detected = detect_file(staged, name, self.settings)
        source_type = "note" if note_title is not None else detected
        adopted = None
        try:
            with self.mutation_lock, self.sessions.begin() as session:
                if expected_generation is not None and expected_generation != self.import_generation:
                    raise ImportFailure("library_reset", 409)
                duplicate = session.scalar(select(Source).where(Source.content_hash == digest))
                if duplicate is not None:
                    if duplicate.is_deleted:
                        raise RetrievalFailure("source_deleted", 409)
                    job = session.scalar(select(IndexingJob).where(IndexingJob.source_id == duplicate.id).order_by(IndexingJob.id.desc()).limit(1))
                    if register_local is None:
                        duplicate.manual_capture = True
                    else:
                        register_local(session, duplicate)
                    return {"source_id": duplicate.id, "job_id": job.id if job else None, "duplicate": True}
                pending = session.scalar(select(func.count()).select_from(IndexingJob).where(IndexingJob.status.in_(["pending", "running"])))
                if pending >= self.settings.max_pending_jobs:
                    raise ImportFailure("queue_full", 429)
                adopted = self.store.adopt(staged, source_type)
                source = Source(
                    source_type=source_type, title=note_title or Path(name).stem,
                    manual_capture=register_local is None,
                    file_path=adopted, mime_type=(image_header(self.store.resolve(adopted), self.settings.max_image_pixels)[0]
                                                if source_type == "image" else MIMES[source_type]), content_hash=digest,
                )
                session.add(source)
                session.flush()
                job = IndexingJob(source_id=source.id)
                session.add(job)
                session.flush()
                if register_local is not None:
                    register_local(session, source)
                response = {"source_id": source.id, "job_id": job.id, "duplicate": False}
            # File publication precedes DB commit. A crash leaves an orphan removed at startup.
            self.wake.set()
            return response
        except BaseException:
            if adopted is not None:
                self.store.remove(adopted)
            raise
        finally:
            staged.unlink(missing_ok=True)

    def job(self, job_id: int) -> dict:
        with self.sessions() as session:
            job = session.get(IndexingJob, job_id)
            if job is None:
                raise ImportFailure("not_found", 404)
            source = session.get(Source, job.source_id)
            if source.is_deleted:
                raise ImportFailure("not_found", 404)
            messages = {**ERRORS, **MESSAGES}
            error_code = job.error if job.error in messages else "extraction_failed"
            document = session.scalar(select(Document.id).where(Document.source_id == source.id))
            chunk_count = session.scalar(select(func.count()).select_from(Chunk).join(Document).where(Document.source_id == source.id))
            return {
                "id": job.id, "source_id": source.id, "source_type": source.source_type,
                "title": source.title, "status": job.status, "stage": job.stage, "attempts": job.attempts,
                "error": {"code": error_code, "message": messages[error_code]} if job.error else None,
                "created_at": job.created_at, "updated_at": job.updated_at,
                "document_id": document, "chunk_count": chunk_count,
                "ready_for_indexing": job.stage == "ingestion" and job.status == "succeeded",
                "retryable": self._retryable(session, job),
            }

    def _retryable(self, session, job: IndexingJob) -> bool:
        if job.status != "failed" or job.attempts >= self.settings.max_job_attempts:
            return False
        if job.stage == "visual" and not self.settings.visual_indexing_enabled:
            return False
        newer = select(IndexingJob.id).where(
            IndexingJob.source_id == job.source_id, IndexingJob.id > job.id,
            IndexingJob.stage.in_([job.stage, "ingestion"]),
        ).limit(1)
        return session.scalar(newer) is None

    def jobs(self, limit: int, offset: int) -> dict:
        with self.mutation_lock, self.sessions() as session:
            ids = list(session.scalars(select(IndexingJob.id).join(Source).where(Source.is_deleted.is_(False)).order_by(IndexingJob.id.desc()).limit(limit).offset(offset)))
            total = session.scalar(select(func.count()).select_from(IndexingJob).join(Source).where(Source.is_deleted.is_(False)))
            return {"items": [self.job(job_id) for job_id in ids], "total": total,
                    "worker_alive": bool(self.thread and self.thread.is_alive())}

    def retry(self, job_id: int) -> dict:
        with self.mutation_lock, self.sessions.begin() as session:
            job = session.get(IndexingJob, job_id)
            if job is None:
                raise ImportFailure("not_found", 404)
            if session.get(Source, job.source_id).is_deleted:
                raise ImportFailure("not_found", 404)
            if not self._retryable(session, job):
                raise ImportFailure("retry_conflict", 409)
            pending = session.scalar(select(func.count()).select_from(IndexingJob).where(IndexingJob.status.in_(["pending", "running"])))
            if pending >= self.settings.max_pending_jobs:
                raise ImportFailure("queue_full", 429)
            job.status, job.error = "pending", None
            session.get(Source, job.source_id).processing_status = "pending"
        self.wake.set()
        return {"job_id": job_id, "status": "pending"}

    def reprocess(self, source_id: int) -> dict:
        """Explicitly re-extract a stored original, e.g. after enabling OCR."""
        with self.mutation_lock, self.sessions.begin() as session:
            source = session.get(Source, source_id)
            if source is None or source.is_deleted:
                raise RetrievalFailure("not_found", 404)
            if session.scalar(select(IndexingJob.id).where(IndexingJob.source_id == source_id,
                    IndexingJob.status.in_(["pending", "running"])).limit(1)):
                raise ImportFailure("reprocess_conflict", 409)
            pending = session.scalar(select(func.count()).select_from(IndexingJob).where(IndexingJob.status.in_(["pending", "running"])))
            if pending >= self.settings.max_pending_jobs:
                raise ImportFailure("queue_full", 429)
            ids = set(session.scalars(select(Chunk.id).join(Document).where(Document.source_id == source_id)))
            if self.indexer is not None:
                try:
                    self.indexer.vectors.remove(ids)
                    if self.indexer.vectors.index is not None:
                        self.indexer.vectors.save()
                    self.indexer.visual.remove(source_id)
                except Exception:
                    self.indexer.vectors.load()
                    self.indexer.visual.vectors.load()
                    raise ImportFailure("storage_error", 503) from None
            session.execute(delete(EmbeddingRecord).where(EmbeddingRecord.chunk_id.in_(ids)))
            session.execute(delete(ImageEmbeddingRecord).where(ImageEmbeddingRecord.source_id == source_id))
            document = session.scalar(select(Document).where(Document.source_id == source_id))
            if document is not None:
                document.extraction_status = "pending"
            source.processing_status, source.indexed_at = "pending", None
            job = IndexingJob(source_id=source_id, stage="ingestion")
            session.add(job)
            session.flush()
            result = {"job_id": job.id, "source_id": source_id, "status": "pending"}
        self.wake.set()
        return result

    def _claim(self) -> tuple[int, int] | None:
        with self.mutation_lock, self.sessions.begin() as session:
            active = select(LocalAccess.id).where(LocalAccess.id == 1, LocalAccess.mode != "deny", LocalAccess.state == "active").exists()
            job = session.scalar(select(IndexingJob).join(Source).where(
                IndexingJob.status == "pending", Source.is_deleted.is_(False),
                Source.manual_capture.is_(True) | active).order_by(IndexingJob.id).limit(1))
            if job is None:
                return None
            if job.attempts >= self.settings.max_job_attempts:
                job.status, job.error = "failed", "interrupted"
                session.get(Source, job.source_id).processing_status = "failed"
                return None
            job.status, job.error = "running", None
            job.attempts += 1
            session.get(Source, job.source_id).processing_status = "processing"
            return job.id, job.source_id

    def _loop(self) -> None:
        while not self.stopping.is_set():
            try:
                if self.indexer is not None:
                    self.indexer.finish_deletions()
                claimed = self._claim()
                if claimed is not None:
                    with self.sessions() as session:
                        job = session.get(IndexingJob, claimed[0])
                        stage = job.stage if job is not None else None
                    if stage == "indexing" and self.indexer is not None:
                        self.indexer.index_source(*claimed, self.stopping)
                    elif stage == "visual" and self.indexer is not None:
                        self.indexer.visual.index_source(*claimed, self.stopping)
                    elif stage == "ingestion":
                        self._execute(*claimed)
                    continue
            except Exception:
                # A failed DB write may leave a running record; startup will recover it.
                logger.exception("worker_failed")
            self.wake.wait(0.5)
            self.wake.clear()

    def _extract(self, source: Source, spool: Path) -> str:
        if source.file_path is None:
            raise ImportFailure("missing_file")
        path = self.store.resolve(source.file_path)
        request = {
            "input": str(path), "output": str(spool), "source_type": source.source_type,
            "content_hash": source.content_hash, "title": source.title,
            "limits": {name: self.settings.model_dump(mode="json")[name] for name in (
                "max_upload_bytes", "max_extracted_chars", "max_pdf_pages", "max_docx_expanded_bytes",
                "ocr_enabled", "ocr_languages", "ocr_data_dir", "ocr_dpi", "max_image_pixels",
            )},
        }
        environment = {key: value for key, value in os.environ.items() if not key.startswith("ECHO_")}
        environment["PYTHONUTF8"] = "1"
        with self.process_lock:
            if self.stopping.is_set():
                raise ImportFailure("interrupted")
            process = subprocess.Popen(
                [sys.executable, "-m", "app.extraction.worker"], cwd=REPO_ROOT / "backend",
                env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.process = process
        try:
            try:
                output, _ = process.communicate(json.dumps(request), timeout=self.settings.extraction_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
                raise ImportFailure("extraction_timeout") from None
            try:
                result = json.loads(output)
            except (ValueError, TypeError):
                raise ImportFailure("extraction_failed") from None
            if process.returncode != 0 or "error" in result:
                raise ImportFailure(result.get("error") if result.get("error") in ERRORS else "extraction_failed")
            return result["method"]
        finally:
            with self.process_lock:
                self.process = None

    def _execute(self, job_id: int, source_id: int) -> None:
        spool = self.store.new_stage("jsonl")
        try:
            with self.sessions() as session:
                source = session.get(Source, source_id)
                if source is None or source.is_deleted:
                    return
                session.expunge(source)
            method = self._extract(source, spool)
            if self.stopping.is_set():
                raise ImportFailure("interrupted")
            self._publish(job_id, source_id, spool, method)
            logger.info("job_succeeded", extra={"job_id": job_id, "source_id": source_id})
        except ImportFailure as error:
            self._failed(job_id, source_id, error.code)
        except Exception:
            logger.exception("job_failed", extra={"job_id": job_id, "source_id": source_id})
            self._failed(job_id, source_id, "extraction_failed")
        finally:
            spool.unlink(missing_ok=True)

    def _publish(self, job_id: int, source_id: int, spool: Path, method: str) -> None:
        # The normalized schema has one TEXT field: one bounded final text allocation is
        # unavoidable. Extraction and chunk insertion otherwise proceed incrementally.
        text = io.StringIO()
        for segment in read_segments(spool):
            if text.tell():
                text.write("\n\n")
            text.write(segment.text)
            if text.tell() > self.settings.max_extracted_chars:
                raise ImportFailure("text_limit")
        with self.mutation_lock, self.sessions.begin() as session:
            source = session.get(Source, source_id)
            if source is None or source.is_deleted:
                return
            session.execute(delete(Document).where(Document.source_id == source_id))
            document = Document(
                source_id=source_id, extracted_text=text.getvalue(), content_length=text.tell(),
                extraction_method=method, extraction_status="complete", language=None,
            )
            session.add(document)
            session.flush()
            batch = []
            for values in iter_chunks(read_segments(spool), self.settings.chunk_tokens, self.settings.chunk_overlap):
                batch.append({"document_id": document.id, **values})
                if len(batch) == 100:
                    session.execute(Chunk.__table__.insert(), batch)
                    batch.clear()
            if batch:
                session.execute(Chunk.__table__.insert(), batch)
            source.processing_status, source.indexed_at = "pending", None
            job = session.get(IndexingJob, job_id)
            job.status, job.error = "succeeded", None
            if self.indexer is not None:
                session.add(IndexingJob(source_id=source_id, stage="indexing"))
                if source.source_type == "image" and self.settings.visual_indexing_enabled:
                    session.add(IndexingJob(source_id=source_id, stage="visual"))

    def _failed(self, job_id: int, source_id: int, code: str) -> None:
        with self.mutation_lock, self.sessions.begin() as session:
            job = session.get(IndexingJob, job_id)
            source = session.get(Source, source_id)
            if job is None or source is None or source.is_deleted:
                return
            if self.stopping.is_set() and job.attempts < self.settings.max_job_attempts:
                job.status, job.error = "pending", None
                source.processing_status = "pending"
            else:
                job.status, job.error = "failed", code
                source.processing_status = "failed"
                session.execute(delete(Document).where(Document.source_id == source_id))
                session.add(Document(source_id=source_id, extracted_text="", content_length=0,
                                     extraction_method="failed", extraction_status="failed"))
        logger.warning("job_failed", extra={"job_id": job_id, "source_id": source_id})
