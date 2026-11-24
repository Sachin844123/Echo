"""Opt-in discovery and change reconciliation using the existing ingestion queue."""

import hashlib
import json
import os
import re
import stat
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select, update

from app.core.config import REPO_ROOT
from app.database.models import IndexingJob, LocalAccess, LocalFile, Source
from app.ingestion.errors import ImportFailure
from app.retrieval.errors import RetrievalFailure
from app.storage.access import (SUPPORTED_EXTENSIONS, PathPolicy, checked_info, fingerprint, fixed_drives,
                                lexical_path, open_approved, path_key, personal_folders, protected_locations, safe_entry)
from app.storage.watch import windows_watch

EVENT_LIMIT = 1024
FILE_LIMIT = 10000
BYTE_LIMIT = 2 * 1024**3
RECONCILE_SECONDS = 900
BLOCK_SIZE = 256 * 1024
SENSITIVE_TEXT = re.compile(rb"(?:-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|PuTTY-User-Key-File:|(?:^|\n)\s*(?:password|client_secret|api_key|access_token)\s*[:=])", re.I)
ERRORS = {
    "read_failed": "A file could not be read. It will be checked again on rescan.",
    "directory_unavailable": "A directory could not be read.",
    "watch_unavailable": "Live monitoring is unavailable for some folders. Periodic scans still check them.",
    "file_limit": "An empty file or one above the import size limit was skipped.",
    "storage_limit": "The automatic indexing storage limit was reached.",
    "protected_content": "A file that looked like a private key or credential was skipped.",
    "protected_path": "A linked, hidden or otherwise protected path was skipped.",
    "changed_file": "A file changed while being read and will be checked again.",
    "import_failed": "A file could not be imported. Check Sources for extraction and indexing errors.",
    "service_error": "Local indexing encountered an error. Use Rescan to try again.",
}


@dataclass(frozen=True)
class Access:
    mode: str | None = None
    state: str = "cancelled"
    roots: tuple[Path, ...] = ()
    exclusions: tuple[Path, ...] = ()
    extensions: frozenset[str] = frozenset(SUPPORTED_EXTENSIONS)

    @property
    def active(self):
        return bool(self.roots) and self.state == "active"

    @classmethod
    def read(cls, row):
        if row is None:
            return cls()
        return cls(row.mode, row.state, tuple(map(lexical_path, json.loads(row.roots))),
                   tuple(map(lexical_path, json.loads(row.exclusions))), frozenset(json.loads(row.extensions)))

    def save(self, session):
        session.merge(LocalAccess(id=1, mode=self.mode, state=self.state,
            roots=json.dumps(list(map(str, self.roots))), exclusions=json.dumps(list(map(str, self.exclusions))),
            extensions=json.dumps(sorted(self.extensions))))


class ScanInterrupted(Exception):
    pass


class LocalIndexing:
    def __init__(self, ingestion):
        self.ingestion = ingestion
        self.sessions = ingestion.sessions
        self.system_exclusions = (REPO_ROOT, ingestion.settings.data_dir, *protected_locations())
        self.guard = threading.Lock()
        self.wake = threading.Event()
        self.stop_flag = threading.Event()
        self.thread: threading.Thread | None = None
        self.access = Access()
        self.generation = 0
        self.scan_requested = False
        self.events: dict[Path, tuple[float, bool]] = {}
        self.phase = "idle"
        self.counts = Counter()
        self.errors = Counter()

    def policy(self, access):
        return PathPolicy(access.roots, (*self.system_exclusions, *access.exclusions), access.extensions)

    def options(self):
        return {"fixed_drives": [str(path) for path in fixed_drives()],
                "personal_folders": [str(path) for path in personal_folders()],
                "supported_extensions": SUPPORTED_EXTENSIONS, "limits": {"files": FILE_LIMIT, "bytes": BYTE_LIMIT}}

    def _roots(self, mode, folders):
        if mode == "deny":
            return ()
        drives = fixed_drives()
        candidates = drives if mode == "all" else personal_folders() if mode == "personal" else tuple(map(lexical_path, folders))
        roots = []
        for path in sorted(set(candidates), key=lambda p: (len(p.parts), path_key(p))):
            try:
                if os.name == "nt" and not any(path.is_relative_to(drive) for drive in drives):
                    raise ValueError("nonlocal_path")
                if mode == "selected" and path.parent == path:
                    raise ValueError("use_all_for_drive_root")
                policy = PathPolicy((path,), self.system_exclusions, frozenset())
                if not policy.covers(path, directory=True) or not stat.S_ISDIR(checked_info(path).st_mode):
                    raise ValueError("protected_path")
                if path_key(path.resolve(strict=True)) != path_key(path):
                    raise ValueError("protected_path")
            except (OSError, ValueError):
                if mode == "selected":
                    raise ValueError("folder_unavailable") from None
                continue
            if not any(path.is_relative_to(root) for root in roots):
                roots.append(path)
        if not roots:
            raise ValueError("no_approved_folders")
        return tuple(roots)

    def refresh_access(self, access):
        with self.guard:
            self.access = access
            self.generation += 1
            self.events.clear()
            self.scan_requested = access.active
            self.phase = "idle"
            self.counts.clear()
            self.errors.clear()
        self.wake.set()
        self.ingestion.wake.set()

    def start(self):
        with self.sessions() as session:
            self.refresh_access(Access.read(session.get(LocalAccess, 1)))
        self.thread = threading.Thread(target=self._run, name="echo-local-indexing", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join()

    @staticmethod
    def reap_unowned(session, source_id=None):
        session.flush()
        linked = select(LocalFile.source_id).where(LocalFile.source_id == Source.id).exists()
        statement = update(Source).where(Source.manual_capture.is_(False), Source.is_deleted.is_(False), ~linked)
        if source_id is not None:
            statement = statement.where(Source.id == source_id)
        session.execute(statement.values(is_deleted=True))

    def configure(self, mode, folders, exclusions, extensions):
        roots = self._roots(mode, folders)
        excluded = tuple(dict.fromkeys(map(lexical_path, exclusions))) if roots else ()
        if any(not any(path.is_relative_to(root) for root in roots) for path in excluded):
            raise ValueError("exclusion_outside_scope")
        access = Access(mode, "active" if roots else "cancelled", roots, excluded, frozenset(extensions))
        policy = self.policy(access)
        with self.ingestion.mutation_lock:
            with self.sessions.begin() as session:
                access.save(session)
                if not roots:
                    session.execute(delete(LocalFile))
                else:
                    for record in session.scalars(select(LocalFile)).yield_per(100):
                        if not policy.covers(Path(record.path)):
                            session.delete(record)
                self.reap_unowned(session)
            self.refresh_access(access)
        return self.status()

    def library_reset(self, session):
        """Called by delete-all inside the shared mutation lock and transaction."""
        if self.access.mode is None:
            return Access()
        access = Access("deny", "cancelled")
        access.save(session)
        session.execute(delete(LocalFile))
        return access

    @staticmethod
    def _totals(session):
        return session.execute(select(func.count(LocalFile.path), func.coalesce(func.sum(LocalFile.size_bytes), 0))).one()

    def status(self):
        with self.guard:
            access, phase = self.access, self.phase
            counts, errors = dict(self.counts), dict(self.errors)
        with self.sessions() as session:
            total, _ = self._totals(session)
            copies = select(LocalFile.source_id, func.max(LocalFile.size_bytes).label("size")).group_by(LocalFile.source_id).subquery()
            stored = session.scalar(select(func.coalesce(func.sum(copies.c.size), 0)))
            indexed = session.scalar(select(func.count()).select_from(LocalFile).join(Source).where(Source.processing_status == "indexed"))
            jobs = dict(session.execute(select(IndexingJob.status, func.count()).join(Source).where(
                Source.is_deleted.is_(False),
                select(LocalFile.path).where(LocalFile.source_id == Source.id).exists(),
            ).group_by(IndexingJob.status)).all())
            purging = session.scalar(select(func.count()).select_from(Source).where(Source.manual_capture.is_(False), Source.is_deleted.is_(True)))
        return {"mode": access.mode, "state": access.state, "phase": phase, "roots": list(map(str, access.roots)),
                "exclusions": list(map(str, access.exclusions)), "extensions": sorted(access.extensions),
                "files": total, "indexed_files": indexed, "stored_bytes": stored,
                "pending_jobs": jobs.get("pending", 0) + jobs.get("running", 0), "failed_jobs": jobs.get("failed", 0),
                "purging_sources": purging, "progress": counts,
                "errors": [{"code": code, "message": ERRORS[code], "count": count} for code, count in errors.items()]}

    def control(self, action):
        with self.ingestion.mutation_lock:
            access = self.access
            if not access.roots:
                raise ValueError("no_approved_folders")
            state = {"pause": "paused", "cancel": "cancelled", "resume": "active", "rescan": "active"}[action]
            updated = Access(access.mode, state, access.roots, access.exclusions, access.extensions)
            with self.sessions.begin() as session:
                updated.save(session)
            self.refresh_access(updated)
        return self.status()

    def _verify(self, generation):
        if self.stop_flag.is_set() or generation != self.generation:
            raise ScanInterrupted()

    def _count(self, generation, name, error=False):
        with self.guard:
            if generation == self.generation:
                (self.errors if error else self.counts)[name] += 1

    def _event(self, path, generation, policy, descend=False):
        if not (policy.covers(path) or policy.covers(path, directory=True)):
            return
        with self.guard:
            if generation != self.generation:
                return
            if len(self.events) >= EVENT_LIMIT and path not in self.events:
                self.scan_requested = True
            else:
                _, previous = self.events.get(path, (0.0, False))
                self.events[path] = time.monotonic() + 0.4, descend or previous
        self.wake.set()

    def _forget(self, path, generation, descendants=False):
        key = path_key(path)
        with self.ingestion.mutation_lock, self.sessions.begin() as session:
            self._verify(generation)
            matches = LocalFile.path == key
            if descendants:
                matches = matches | LocalFile.path.startswith(key.rstrip(os.sep) + os.sep, autoescape=True)
            result = session.execute(delete(LocalFile).where(matches))
            if result.rowcount:
                self.reap_unowned(session)
                self.ingestion.wake.set()

    def _capture(self, path, generation, policy):
        if not policy.covers(path):
            return
        self._count(generation, "examined")
        key = path_key(path)
        staged = self.ingestion.store.new_stage()
        try:
            self._verify(generation)
            info = checked_info(path)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                self._forget(path, generation)
                self._count(generation, "protected_path", True)
                return
            stamp = fingerprint(info)
            with self.sessions() as session:
                previous = session.get(LocalFile, key)
                if previous and stamp == (previous.size_bytes, previous.mtime_ns, previous.identity):
                    self._count(generation, "unchanged")
                    return
                count, total = self._totals(session)
                if count + (previous is None) > FILE_LIMIT or total - (previous.size_bytes if previous else 0) + info.st_size > BYTE_LIMIT:
                    raise ValueError("storage_limit")
            if not 0 < info.st_size <= self.ingestion.settings.max_upload_bytes:
                self._forget(path, generation)
                self._count(generation, "file_limit", True)
                return
            digest = hashlib.sha256()
            size = 0
            tail = b""
            with open_approved(path, policy) as (source, opened), staged.open("xb") as output:
                while True:
                    self._verify(generation)
                    block = source.read(BLOCK_SIZE)
                    if not block:
                        break
                    self._verify(generation)
                    size += len(block)
                    if size > opened.st_size:
                        raise ValueError("changed_file")
                    if path.suffix.lower() in {".txt", ".md", ".markdown"}:
                        sample = tail + block.replace(b"\0", b"")
                        if SENSITIVE_TEXT.search(sample):
                            raise ValueError("protected_content")
                        tail = sample[-128:]
                    output.write(block)
                    digest.update(block)
                stamp = fingerprint(opened)
                if size != opened.st_size or stamp != fingerprint(os.fstat(source.fileno())):
                    raise ValueError("changed_file")
                output.flush()
                os.fsync(output.fileno())

            def register(session, source):
                self._verify(generation)
                if stamp != fingerprint(checked_info(path)):
                    raise ValueError("changed_file")
                previous = session.get(LocalFile, key)
                count, total = self._totals(session)
                if count + (previous is None) > FILE_LIMIT or total - (previous.size_bytes if previous else 0) + size > BYTE_LIMIT:
                    raise ValueError("storage_limit")
                old = previous.source_id if previous else source.id
                session.merge(LocalFile(path=key, source_id=source.id, size_bytes=size, mtime_ns=stamp[1], identity=stamp[2]))
                if old != source.id:
                    self.reap_unowned(session, old)

            while True:
                self._verify(generation)
                # Wait before enqueue so a saturated ingestion queue does not stage more files.
                with self.ingestion.mutation_lock:
                    with self.sessions() as session:
                        pending = session.scalar(select(func.count()).select_from(IndexingJob).where(IndexingJob.status.in_(["pending", "running"])))
                    if pending < min(24, self.ingestion.settings.max_pending_jobs):
                        result = self.ingestion.enqueue(staged, path.name, digest.hexdigest(), register_local=register)
                        self._count(generation, "linked" if result["duplicate"] else "queued")
                        break
                self.stop_flag.wait(0.25)
        except FileNotFoundError:
            self._forget(path, generation)
        except ValueError as error:
            code = str(error)
            if code in {"protected_path", "protected_content", "storage_limit"}:
                self._forget(path, generation)
            if code in ERRORS:
                self._count(generation, code, True)
            else:
                self._count(generation, "import_failed", True)
            if code == "changed_file":
                self._event(path, generation, policy)
        except (ImportFailure, RetrievalFailure) as error:
            if error.code == "source_deleted":
                self._event(path, generation, policy)
            else:
                self._forget(path, generation)
                self._count(generation, "import_failed", True)
        except OSError:
            self._count(generation, "read_failed", True)
        finally:
            staged.unlink(missing_ok=True)

    def _walk(self, root, generation, policy, depth=0):
        self._verify(generation)
        if depth > 64 or not policy.covers(root, directory=True):
            return
        try:
            if not stat.S_ISDIR(checked_info(root).st_mode):
                return
            with os.scandir(root) as entries:
                for entry in entries:
                    self._verify(generation)
                    path = Path(entry.path)
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        self._count(generation, "read_failed", True)
                        continue
                    if not safe_entry(info):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        self._walk(path, generation, policy, depth + 1)
                    elif stat.S_ISREG(info.st_mode) and policy.covers(path):
                        self._capture(path, generation, policy)
        except ValueError:
            return
        except OSError:
            self._count(generation, "directory_unavailable", True)

    def _reconcile(self, generation, policy):
        last = ""
        while True:
            self._verify(generation)
            with self.sessions() as session:
                paths = list(session.scalars(select(LocalFile.path).where(LocalFile.path > last).order_by(LocalFile.path).limit(100)))
            if not paths:
                return
            last = paths[-1]
            for key in paths:
                path = Path(key)
                try:
                    info = checked_info(path)
                    if policy.covers(path) and stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        continue
                except (FileNotFoundError, NotADirectoryError, ValueError):
                    pass
                except OSError:
                    continue  # An inaccessible drive is not evidence of removal.
                self._forget(path, generation)

    def _handle_event(self, path, generation, policy, descend):
        try:
            info = checked_info(path)
        except (FileNotFoundError, NotADirectoryError, ValueError):
            self._forget(path, generation, descendants=True)
            return
        except OSError:
            self._count(generation, "read_failed", True)
            return
        if stat.S_ISDIR(info.st_mode):
            if descend:
                self._walk(path, generation, policy)
        else:
            self._capture(path, generation, policy)

    @staticmethod
    def _stop_watches(watches):
        for watch in watches.values():
            if watch.should_keep_running():
                watch.stop()
        for watch in watches.values():
            watch.join()
        watches.clear()

    def _run(self):
        watches = {}
        watching_generation = -1
        next_scan = 0.0
        try:
            while not self.stop_flag.is_set():
                with self.guard:
                    generation, access = self.generation, self.access
                    now = time.monotonic()
                    scan = access.active and (self.scan_requested or now >= next_scan)
                    if scan:
                        self.scan_requested = False
                        self.phase = "scanning"
                    events = [(path, descend) for path, (when, descend) in self.events.items() if when <= now][:64] if access.active else []
                    for path, _ in events:
                        self.events.pop(path)
                try:
                    if generation != watching_generation:
                        self._stop_watches(watches)
                        watching_generation = generation
                    if not access.active:
                        self.wake.wait(1)
                        self.wake.clear()
                        continue
                    policy = self.policy(access)
                    if scan:
                        for root in access.roots:
                            self._verify(generation)
                            existing = watches.get(root)
                            if existing is None or not existing.is_alive():
                                try:
                                    checked_info(root)
                                    watches[root] = windows_watch(root, lambda path, descend, g=generation, p=policy: self._event(path, g, p, descend))
                                except (OSError, ValueError):
                                    self._count(generation, "watch_unavailable", True)
                            self._walk(root, generation, policy)
                        self._reconcile(generation, policy)
                        self._count(generation, "completed_scans")
                        next_scan = time.monotonic() + RECONCILE_SECONDS
                    for path, descend in events:
                        self._verify(generation)
                        self._handle_event(path, generation, policy, descend)
                except ScanInterrupted:
                    continue
                except Exception:
                    self._count(generation, "service_error", True)
                    next_scan = time.monotonic() + 30
                finally:
                    with self.guard:
                        if generation == self.generation:
                            self.phase = "idle"
                self.wake.wait(0.25)
                self.wake.clear()
        finally:
            self._stop_watches(watches)
