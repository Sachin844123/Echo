"""Offline MiniLM encoder, loaded once, with explicit long-input window pooling."""

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.config import Settings
from app.retrieval.errors import RetrievalFailure

MODEL_FILES = (
    "config.json", "config_sentence_transformers.json", "modules.json", "sentence_bert_config.json",
    "model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "vocab.txt", "1_Pooling/config.json",
)
POOLING_VERSION = "wordpiece-windows-32overlap-weighted-mean-v1"


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    version: str
    dimension: int = 384


def model_fingerprint(root: Path, files: dict[str, str]) -> str:
    digest = hashlib.sha256(POOLING_VERSION.encode())
    for name in sorted(files):
        path = root / name
        if name not in MODEL_FILES or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise RetrievalFailure("model_invalid")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != files[name]:
            raise RetrievalFailure("model_invalid")
        digest.update(f"{name}:{actual}\n".encode())
    return digest.hexdigest()


class LocalEncoder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._identity = None
        self._model = None
        self.lock = threading.RLock()

    @property
    def identity(self) -> ModelIdentity:
        with self.lock:
            if self._identity is None:
                path = self.settings.embedding_model_dir / "echo-model.json"
                if not path.is_file():
                    raise RetrievalFailure("model_unavailable")
                try:
                    descriptor = json.loads(path.read_text(encoding="utf-8"))
                    if descriptor["name"] != self.settings.embedding_model_name:
                        raise RetrievalFailure("model_mismatch")
                    files = descriptor["files"]
                    if set(files) != set(MODEL_FILES):
                        raise RetrievalFailure("model_invalid")
                    version = model_fingerprint(self.settings.embedding_model_dir, files)
                    self._identity = ModelIdentity(descriptor["name"], version)
                except (OSError, KeyError, ValueError, TypeError):
                    raise RetrievalFailure("model_invalid") from None
            return self._identity

    def _load(self):
        if self._model is not None:
            return self._model
        identity = self.identity
        # Set before importing HF/transformers; model loading cannot contact the Hub.
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                           "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
                           "TOKENIZERS_PARALLELISM": "false", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
        try:
            import torch
            from sentence_transformers import SentenceTransformer
            from transformers.utils import logging as transformer_logging

            transformer_logging.disable_progress_bar()
            transformer_logging.disable_default_handler()
            transformer_logging.enable_propagation()

            torch.set_num_threads(self.settings.embedding_threads)
            model = SentenceTransformer(
                str(self.settings.embedding_model_dir), device="cpu", local_files_only=True,
                trust_remote_code=False, model_kwargs={"use_safetensors": True},
            )
            model.eval()
            dimension = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
            if dimension() != identity.dimension:
                raise RetrievalFailure("model_mismatch")
            self._model = model
            return model
        except RetrievalFailure:
            raise
        except Exception:
            raise RetrievalFailure("model_invalid") from None

    def encode(self, texts: list[str]) -> np.ndarray:
        with self.lock:
            model = self._load()
            import torch

            if not texts:
                return np.empty((0, self.identity.dimension), dtype="float32")
            tokenizer = model.tokenizer
            capacity = int(model.max_seq_length) - tokenizer.num_special_tokens_to_add(pair=False)
            if capacity <= 32:
                raise RetrievalFailure("model_invalid")
            output = np.zeros((len(texts), self.identity.dimension), dtype="float32")
            weights = np.zeros(len(texts), dtype="float32")
            batch, owners, lengths = [], [], []

            def flush():
                if not batch:
                    return
                # MiniLM uses BERT's CLS/window/SEP format. Construct tensors directly:
                # Transformers 5 removed prepare_for_model from fast tokenizers.
                width = max(len(ids) for ids in batch)
                input_ids = torch.full((len(batch), width), tokenizer.pad_token_id, dtype=torch.long)
                mask = torch.zeros_like(input_ids)
                for row, ids in enumerate(batch):
                    input_ids[row, :len(ids)] = torch.tensor(ids, dtype=torch.long)
                    mask[row, :len(ids)] = 1
                features = {"input_ids": input_ids, "attention_mask": mask, "token_type_ids": torch.zeros_like(input_ids)}
                with torch.inference_mode():
                    vectors = model(features)["sentence_embedding"].cpu().numpy().astype("float32")
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                vectors /= np.maximum(norms, 1e-12)
                for owner, length, vector in zip(owners, lengths, vectors):
                    output[owner] += vector * length
                    weights[owner] += length
                batch.clear()
                owners.clear()
                lengths.clear()

            for owner, text in enumerate(texts):
                ids = tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False)
                if not ids:
                    raise RetrievalFailure("invalid_request", 422)
                start = 0
                while start < len(ids):
                    window = ids[start:start + capacity]
                    batch.append([tokenizer.cls_token_id, *window, tokenizer.sep_token_id])
                    owners.append(owner)
                    lengths.append(len(window))
                    if len(batch) >= self.settings.embedding_batch_size:
                        flush()
                    if start + capacity >= len(ids):
                        break
                    start += capacity - 32
            flush()
            output /= weights[:, None]
            norms = np.linalg.norm(output, axis=1, keepdims=True)
            if not np.isfinite(output).all() or (norms <= 1e-12).any():
                raise RetrievalFailure("indexing_failed")
            return np.ascontiguousarray(output / norms, dtype="float32")
