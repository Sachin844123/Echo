"""Strict, local-only dataset contract with explicit held-out queries."""

import hashlib
import json
import unicodedata
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator, model_validator
from app.core.config import RerankWeights

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Grade = Annotated[StrictInt, Field(ge=0, le=3)]
SourceType = Literal["pdf", "txt", "markdown", "docx", "note", "image"]


class EvaluationError(Exception):
    """Codes only: never put dataset text, paths or raw parser errors in logs."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Filters(StrictModel):
    source_types: list[SourceType] = Field(default_factory=list, max_length=6)
    captured_from: datetime | None = None
    captured_to: datetime | None = None
    collection: Identifier | None = None

    @model_validator(mode="after")
    def dates(self):
        for date in (self.captured_from, self.captured_to):
            if date is not None and (date.tzinfo is None or date.utcoffset() is None):
                raise ValueError("timezone required")
        if self.captured_from and self.captured_to and self.captured_from > self.captured_to:
            raise ValueError("reversed date range")
        return self


class DocumentSpec(StrictModel):
    id: Identifier
    path: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    captured_at: datetime
    collections: list[Identifier] = Field(default_factory=list, max_length=100)

    @field_validator("title")
    @classmethod
    def title_text(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("nonblank title required")
        return value.strip()

    @field_validator("captured_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value


class QueryContext(StrictModel):
    source_types: list[SourceType] = Field(default_factory=list, max_length=6)
    collection: Identifier | None = None


class QuerySpec(StrictModel):
    id: Identifier
    text: str = Field(min_length=1, max_length=2000)
    filters: Filters = Field(default_factory=Filters)
    context: QueryContext = Field(default_factory=QueryContext)
    relevance: dict[Identifier, Grade] = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def query_text(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("nonblank query required")
        return value.strip()


class Splits(StrictModel):
    tuning: list[QuerySpec] = Field(min_length=1, max_length=100000)
    test: list[QuerySpec] = Field(min_length=1, max_length=100000)


def matches(document: DocumentSpec, filters: Filters) -> bool:
    return (not filters.source_types or document.source_type in filters.source_types) and (
        filters.captured_from is None or document.captured_at >= filters.captured_from) and (
        filters.captured_to is None or document.captured_at <= filters.captured_to) and (
        filters.collection is None or filters.collection in document.collections)


class Dataset(StrictModel):
    schema_version: Literal[1]
    id: Identifier
    kind: Literal["research", "test_fixture"]
    documents: list[DocumentSpec] = Field(min_length=1, max_length=100000)
    queries: Splits

    @field_validator("schema_version", mode="before")
    @classmethod
    def version_integer(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("schema version must be integer one")
        return value

    @model_validator(mode="after")
    def references_and_splits(self):
        documents = {doc.id: doc for doc in self.documents}
        if len(documents) != len(self.documents):
            raise ValueError("duplicate document ID")
        collections = {name for doc in self.documents for name in doc.collections}
        ids, texts = set(), set()
        for query in [*self.queries.tuning, *self.queries.test]:
            canonical = " ".join(unicodedata.normalize("NFKC", query.text).casefold().split())
            if query.id in ids or canonical in texts:
                raise ValueError("queries must have unique IDs and normalized text across splits")
            ids.add(query.id)
            texts.add(canonical)
            if query.filters.collection is not None and query.filters.collection not in collections:
                raise ValueError("unknown collection")
            if query.context.collection is not None and query.context.collection not in collections:
                raise ValueError("unknown context collection")
            if not any(grade > 0 for grade in query.relevance.values()):
                raise ValueError("each benchmark query requires a relevant document")
            for key, grade in query.relevance.items():
                if key not in documents:
                    raise ValueError("unknown relevance document")
                if grade > 0 and not matches(documents[key], query.filters):
                    raise ValueError("positive relevance is excluded by query filters")
        return self


class RunConfig(StrictModel):
    # Preserve the previous evaluation baseline when loading old frozen configs.
    retrieval_profile: Literal["classic", "source_balanced"] = "classic"
    spelling_correction: bool = False
    candidate_scan_limit: int = Field(default=2000, ge=200, le=10000)
    ocr_enabled: bool = False
    ocr_languages: str = Field(default="eng", pattern=r"^[a-z]{3}(?:\+[a-z]{3}){0,3}$")
    ocr_dpi: int = Field(default=200, ge=100, le=300)
    chunk_tokens: int = Field(default=350, ge=10, le=2000)
    chunk_overlap: int = Field(default=60, ge=0, le=1000)
    candidate_pool: int = Field(default=50, ge=10, le=200)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    rerank_weights: RerankWeights = Field(default_factory=RerankWeights)
    embedding_batch_size: int = Field(default=16, ge=1, le=64)
    embedding_threads: int = Field(default=2, ge=1, le=8)
    repeats: int = Field(default=3, ge=1, le=100)
    warmups: int = Field(default=1, ge=1, le=10)
    seed: int = Field(default=1729, ge=0, le=2**32 - 1)
    memory_sample_ms: int = Field(default=50, ge=10, le=1000)
    job_timeout_seconds: int = Field(default=600, ge=1, le=3600)

    @model_validator(mode="after")
    def overlap(self):
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("overlap must be below chunk size")
        return self


def read_json(path: Path, maximum: int):
    try:
        with path.open("rb") as stream:
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise EvaluationError("manifest_too_large")

        def unique_keys(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise EvaluationError("duplicate_json_key")
                data[key] = value
            return data
        return json.loads(payload, object_pairs_hook=unique_keys)
    except (OSError, ValueError, UnicodeError):
        raise EvaluationError("invalid_json_file") from None


def load_dataset(path: Path) -> Dataset:
    try:
        return Dataset.model_validate(read_json(path, 32 * 1024 * 1024))
    except ValidationError:
        raise EvaluationError("invalid_dataset_contract") from None


def load_config(path: Path | None) -> RunConfig:
    try:
        return RunConfig() if path is None else RunConfig.model_validate(read_json(path, 16384))
    except ValidationError:
        raise EvaluationError("invalid_run_configuration") from None


def resolve_document(root: Path, relative: str) -> Path:
    value = relative.replace("\\", "/")
    parts = value.split("/")
    if ("\x00" in value or ":" in value or PureWindowsPath(value).drive or Path(value).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)):
        raise EvaluationError("invalid_document_path")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise EvaluationError("missing_or_escaped_document")
    return resolved


def fingerprint(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()
