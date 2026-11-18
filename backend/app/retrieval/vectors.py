"""FAISS IDMap/FlatIP snapshots with checksum validation and atomic manifests."""

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

import faiss
import numpy as np

from app.embeddings.local import ModelIdentity
from app.retrieval.errors import RetrievalFailure


class VectorStore:
    def __init__(self, root: Path):
        if root.is_symlink() or root.resolve().parent != root.parent.resolve():
            raise RetrievalFailure("index_unavailable")
        self.root = root
        self.index = None
        self.identity: ModelIdentity | None = None
        self.corrupt = False
        faiss.omp_set_num_threads(1)

    @property
    def ids(self) -> set[int]:
        return set(map(int, faiss.vector_to_array(self.index.id_map))) if self.index is not None else set()

    def reset(self, identity: ModelIdentity):
        self.index = faiss.IndexIDMap(faiss.IndexFlatIP(identity.dimension))
        self.identity = identity

    def load(self):
        self.index, self.identity, self.corrupt = None, None, False
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = self.root / "manifest.json"
        if not manifest.exists():
            self.corrupt = any(self.root.glob("index-*.faiss"))
            return
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data["format"] != 1 or not re.fullmatch(r"index-[0-9a-f]{32}\.faiss", data["file"]):
                raise ValueError("invalid manifest")
            path = self.root / data["file"]
            if path.is_symlink() or path.resolve().parent != self.root.resolve():
                raise ValueError("invalid index path")
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != data["sha256"]:
                    raise ValueError("checksum mismatch")
                stream.seek(0)
                index = faiss.deserialize_index(np.fromfile(stream, dtype="uint8"))
            if not isinstance(index, faiss.IndexIDMap) or not isinstance(faiss.downcast_index(index.index), faiss.IndexFlatIP):
                raise ValueError("unexpected index type")
            ids = faiss.vector_to_array(index.id_map)
            if index.d != data["dimension"] or index.ntotal != data["count"] or len(set(map(int, ids))) != len(ids) or (ids <= 0).any():
                raise ValueError("invalid index metadata")
            raw = faiss.downcast_index(index.index)
            for start in range(0, index.ntotal, 1024):
                vectors = raw.reconstruct_n(start, min(1024, index.ntotal - start))
                if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
                    raise ValueError("invalid vectors")
            self.index = index
            self.identity = ModelIdentity(data["model_name"], data["model_version"], data["dimension"])
        except (OSError, KeyError, ValueError, TypeError, RuntimeError):
            self.index, self.identity, self.corrupt = None, None, True

    def save(self):
        if self.index is None or self.identity is None:
            raise RetrievalFailure("index_unavailable")
        self.root.mkdir(parents=True, exist_ok=True)
        name = f"index-{uuid.uuid4().hex}.faiss"
        path = self.root / name
        payload = faiss.serialize_index(self.index)
        with path.open("xb") as stream:
            stream.write(memoryview(payload))
            stream.flush()
            os.fsync(stream.fileno())
        data = {"format": 1, "file": name, "sha256": hashlib.sha256(memoryview(payload)).hexdigest(),
                "model_name": self.identity.name, "model_version": self.identity.version,
                "dimension": self.identity.dimension, "count": int(self.index.ntotal)}
        temporary = self.root / "manifest.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.root / "manifest.json")
        # Previous snapshots must not retain vectors after a successful deletion.
        for old in self.root.glob("index-*.faiss"):
            if old.name != name and re.fullmatch(r"index-[0-9a-f]{32}\.faiss", old.name) and not old.is_symlink():
                old.unlink()
        self.corrupt = False

    def remove(self, ids):
        if self.index is not None and len(ids):
            self.index.remove_ids(np.asarray(list(ids), dtype="int64"))

    def discard_corrupt(self):
        """Purge unreadable owned snapshots without needing the embedding model."""
        for path in self.root.glob("index-*.faiss"):
            if re.fullmatch(r"index-[0-9a-f]{32}\.faiss", path.name) and not path.is_symlink():
                path.unlink()
        for name in ("manifest.json", "manifest.tmp"):
            (self.root / name).unlink(missing_ok=True)
        self.index, self.identity, self.corrupt = None, None, False

    def add(self, ids: list[int], vectors: np.ndarray):
        values = np.ascontiguousarray(vectors, dtype="float32")
        if values.shape != (len(ids), self.identity.dimension) or not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-4):
            raise RetrievalFailure("indexing_failed")
        if len(set(ids)) != len(ids) or any(value <= 0 for value in ids):
            raise RetrievalFailure("indexing_failed")
        self.remove(ids)
        self.index.add_with_ids(values, np.asarray(ids, dtype="int64"))

    def search(self, vector: np.ndarray, allowed: set[int], limit: int) -> list[tuple[int, float]]:
        if self.index is None or not allowed:
            return []
        requested = min(max(limit, 1), self.index.ntotal)
        while requested:
            scores, ids = self.index.search(np.ascontiguousarray(vector, dtype="float32"), requested)
            hits = [(int(key), float(score)) for key, score in zip(ids[0], scores[0]) if int(key) in allowed]
            hits.sort(key=lambda item: (-item[1], item[0]))
            # Expand to include score ties at the cutoff, ensuring deterministic ID order.
            if requested == self.index.ntotal or (len(hits) >= limit and hits[limit - 1][1] > float(scores[0][-1])):
                return hits[:limit]
            requested = min(self.index.ntotal, max(requested + 1, requested * 2))
        return []
