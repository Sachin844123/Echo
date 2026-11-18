"""Deterministic normalized contextual signals over existing hybrid candidates."""

import math
import re
import unicodedata
from dataclasses import dataclass

from app.core.config import RerankWeights

RERANK_VERSION = "normalized-rrf-query-coverage-context-v1"


def terms(value: str) -> set[str]:
    return set(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold(), flags=re.UNICODE))


def coverage(query_terms: set[str], text: str) -> float:
    return len(query_terms & terms(text)) / len(query_terms) if query_terms else 0.0


@dataclass(frozen=True)
class Candidate:
    chunk_id: int
    rrf_score: float
    title: str
    heading: str | None
    chunk_text: str
    source_type: str
    collection_match: bool = False


@dataclass(frozen=True)
class RerankedHit:
    chunk_id: int
    score: float
    rrf_score: float
    signals: dict[str, float]


def rerank(candidates: list[Candidate], query: str, source_types: list[str], weights: RerankWeights, k: int) -> list[RerankedHit]:
    query_terms = terms(query)
    values = weights.model_dump()
    total = math.fsum(values.values())
    normalized_weights = {key: value / total for key, value in values.items()}
    results = []
    for candidate in candidates:
        # Two ranked lists have maximum RRF 2/(k+1). No per-query min/max scaling.
        signals = {
            "rrf": min(1.0, max(0.0, candidate.rrf_score * (k + 1) / 2)),
            "title_heading": max(coverage(query_terms, candidate.title), coverage(query_terms, candidate.heading or "")),
            "keyword_overlap": coverage(query_terms, candidate.chunk_text),
            "source_type": float(candidate.source_type in source_types),
            "collection": float(candidate.collection_match),
        }
        score = min(1.0, max(0.0, math.fsum(normalized_weights[key] * signals[key] for key in values)))
        results.append(RerankedHit(candidate.chunk_id, score, candidate.rrf_score, signals))
    return sorted(results, key=lambda hit: (-hit.score, -hit.rrf_score, hit.chunk_id))
