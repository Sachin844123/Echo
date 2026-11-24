"""A lazy, CPU-only CLIP encoder; validated safetensors and no runtime network."""

import hashlib
import json
import os
import threading

import numpy as np

from app.embeddings.local import ModelIdentity
from app.retrieval.errors import RetrievalFailure
from app.security.images import image_header

MODEL_NAME = "openai/clip-vit-base-patch32"
MODEL_FILES = ("config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json",
               "special_tokens_map.json", "vocab.json", "merges.txt", "model.safetensors")


class VisualEncoder:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self._identity = None
        self._model = None

    @property
    def identity(self):
        if self._identity is not None:
            return self._identity
        with self.lock:
            if self._identity is None:
                root = self.settings.visual_model_dir
                descriptor = root / "echo-model.json"
                if not descriptor.is_file():
                    raise RetrievalFailure("visual_model_unavailable")
                try:
                    data = json.loads(descriptor.read_text(encoding="utf-8"))
                    if data["name"] != MODEL_NAME or set(data["files"]) != set(MODEL_FILES):
                        raise RetrievalFailure("model_invalid")
                    digest = hashlib.sha256(b"clip-rgb-center-crop-normalized-v1")
                    for name in sorted(MODEL_FILES):
                        path = root / name
                        if not path.resolve().is_relative_to(root):
                            raise RetrievalFailure("model_invalid")
                        with path.open("rb") as stream:
                            actual = hashlib.file_digest(stream, "sha256").hexdigest()
                        if actual != data["files"][name]:
                            raise RetrievalFailure("model_invalid")
                        digest.update(f"{name}:{actual}\n".encode())
                    self._identity = ModelIdentity(MODEL_NAME, digest.hexdigest(), 512)
                except (OSError, ValueError, TypeError, KeyError):
                    raise RetrievalFailure("model_invalid") from None
            return self._identity

    def _load(self):
        if self._model is not None:
            return
        self.identity
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                           "DO_NOT_TRACK": "1", "TOKENIZERS_PARALLELISM": "false", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
        try:
            import torch
            from transformers import CLIPModel, CLIPTokenizerFast
            from transformers.models.clip.image_processing_pil_clip import CLIPImageProcessorPil
            from transformers.utils import logging
            logging.disable_progress_bar()
            logging.disable_default_handler()
            logging.enable_propagation()
            torch.set_num_threads(self.settings.embedding_threads)
            root = str(self.settings.visual_model_dir)
            model = CLIPModel.from_pretrained(root, local_files_only=True, use_safetensors=True).to("cpu").eval()
            self._processor = CLIPImageProcessorPil.from_pretrained(root, local_files_only=True)
            self._tokenizer = CLIPTokenizerFast.from_pretrained(root, local_files_only=True)
            if model.config.projection_dim != 512:
                raise RetrievalFailure("model_mismatch")
            self._model = model
        except RetrievalFailure:
            raise
        except Exception:
            raise RetrievalFailure("model_invalid") from None

    @staticmethod
    def _normalize(features):
        # Transformers 5 returns an output container; older APIs returned the tensor.
        tensor = getattr(features, "pooler_output", features)
        values = tensor.detach().cpu().numpy().astype("float32")
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if not np.isfinite(values).all() or (norms <= 1e-12).any():
            raise RetrievalFailure("indexing_failed")
        return np.ascontiguousarray(values / norms, dtype="float32")

    def encode_image(self, path):
        with self.lock:
            self._load()
            import torch
            from PIL import Image, ImageOps
            image_header(path, self.settings.max_image_pixels)
            with Image.open(path) as image:
                if image.width * image.height > self.settings.max_image_pixels:
                    raise RetrievalFailure("invalid_request", 422)
                with ImageOps.exif_transpose(image).convert("RGB") as rgb:
                    inputs = self._processor(images=rgb, return_tensors="pt")
            with torch.inference_mode():
                return self._normalize(self._model.get_image_features(**inputs))

    def encode_text(self, text):
        with self.lock:
            self._load()
            import torch
            inputs = self._tokenizer([text], return_tensors="pt", truncation=False)
            if inputs["input_ids"].shape[1] > self._model.config.text_config.max_position_embeddings:
                raise RetrievalFailure("visual_query_too_long", 422)
            with torch.inference_mode():
                return self._normalize(self._model.get_text_features(**inputs))
