"""Validated environment configuration without implicit dotenv loading."""

import json
import os
import re
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


REPO_ROOT = Path(__file__).resolve().parents[3]


class RerankWeights(BaseModel):
    """Untuned placeholder weights; shared by the API and evaluation runner."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    rrf: float = Field(default=1.0, ge=0, le=100)
    title_heading: float = Field(default=0.2, ge=0, le=100)
    keyword_overlap: float = Field(default=0.2, ge=0, le=100)
    source_type: float = Field(default=0.1, ge=0, le=100)
    collection: float = Field(default=0.1, ge=0, le=100)

    @model_validator(mode="after")
    def nonzero(self):
        if not any(self.model_dump().values()):
            raise ValueError("at least one reranking weight must be positive")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    data_dir: Path = REPO_ROOT / ".local"
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    session_token: SecretStr | None = None
    allowed_origins: tuple[str, ...] = ()
    log_level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    max_extracted_chars: int = Field(default=5_000_000, ge=100, le=20_000_000)
    max_pdf_pages: int = Field(default=2000, ge=1, le=10000)
    max_docx_expanded_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)
    extraction_timeout_seconds: int = Field(default=120, ge=1, le=600)
    chunk_tokens: int = Field(default=350, ge=10, le=2000)
    chunk_overlap: int = Field(default=60, ge=0, le=1000)
    max_job_attempts: int = Field(default=3, ge=1, le=10)
    max_pending_jobs: int = Field(default=100, ge=1, le=1000)
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_dir: Path = REPO_ROOT / ".local" / "models" / "all-MiniLM-L6-v2"
    embedding_batch_size: int = Field(default=16, ge=1, le=64)
    embedding_threads: int = Field(default=2, ge=1, le=8)
    candidate_pool: int = Field(default=50, ge=10, le=200)
    result_limit: int = Field(default=10, ge=1, le=50)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    rerank_weights: RerankWeights = Field(default_factory=RerankWeights)

    @field_validator("data_dir", "embedding_model_dir")
    @classmethod
    def resolve_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("session_token")
    @classmethod
    def validate_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value.get_secret_value()):
            raise ValueError("session token must be 43-128 URL-safe characters; use the token command")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.port is None
                or not 1024 <= parsed.port <= 65535
                or value != f"http://{parsed.hostname}:{parsed.port}"
            ):
                raise ValueError("origins must be exact loopback HTTP origins with an explicit port")
        return tuple(dict.fromkeys(values))

    @model_validator(mode="after")
    def default_origin(self) -> Self:
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        if self.result_limit > self.candidate_pool:
            raise ValueError("result_limit cannot exceed candidate_pool")
        if not self.allowed_origins:
            object.__setattr__(self, "allowed_origins", (f"http://127.0.0.1:{self.port}",))
        return self

    @property
    def database_path(self) -> Path:
        return self.data_dir / "echo.sqlite3"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}"})

    @classmethod
    def from_env(cls) -> Self:
        names = {
            "ECHO_DATA_DIR": "data_dir", "ECHO_HOST": "host", "ECHO_PORT": "port",
            "ECHO_SESSION_TOKEN": "session_token", "ECHO_LOG_LEVEL": "log_level",
            "ECHO_MAX_UPLOAD_BYTES": "max_upload_bytes",
            "ECHO_MAX_EXTRACTED_CHARS": "max_extracted_chars",
            "ECHO_MAX_PDF_PAGES": "max_pdf_pages",
            "ECHO_MAX_DOCX_EXPANDED_BYTES": "max_docx_expanded_bytes",
            "ECHO_EXTRACTION_TIMEOUT_SECONDS": "extraction_timeout_seconds",
            "ECHO_CHUNK_TOKENS": "chunk_tokens", "ECHO_CHUNK_OVERLAP": "chunk_overlap",
            "ECHO_MAX_JOB_ATTEMPTS": "max_job_attempts", "ECHO_MAX_PENDING_JOBS": "max_pending_jobs",
            "ECHO_EMBEDDING_MODEL_NAME": "embedding_model_name",
            "ECHO_EMBEDDING_MODEL_DIR": "embedding_model_dir",
            "ECHO_EMBEDDING_BATCH_SIZE": "embedding_batch_size",
            "ECHO_EMBEDDING_THREADS": "embedding_threads",
            "ECHO_CANDIDATE_POOL": "candidate_pool", "ECHO_RESULT_LIMIT": "result_limit",
            "ECHO_RRF_K": "rrf_k",
        }
        values = {field: os.environ[name] for name, field in names.items() if name in os.environ}
        if "ECHO_ALLOWED_ORIGINS" in os.environ:
            values["allowed_origins"] = json.loads(os.environ["ECHO_ALLOWED_ORIGINS"])
        if "ECHO_RERANK_WEIGHTS" in os.environ:
            values["rerank_weights"] = json.loads(os.environ["ECHO_RERANK_WEIGHTS"])
        return cls.model_validate(values)
