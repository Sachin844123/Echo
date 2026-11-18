"""Source-level ranking metrics with explicit cutoffs and graded relevance."""

import math
import statistics
from collections.abc import Mapping, Sequence


def ranking_metrics(retrieved: Sequence[str], relevance: Mapping[str, int]) -> dict[str, float]:
    """P@5 uses a fixed denominator; MRR is truncated to the ten visible results.

    Grades 1–3 count as relevant for binary metrics; NDCG uses 2**grade - 1.
    Unjudged documents count as grade zero. No-positive queries score zero.
    Duplicate results are an engine error, never extra relevant hits.
    """
    if len(set(retrieved)) != len(retrieved):
        raise ValueError("duplicate result IDs")
    if any(type(grade) is not int or not 0 <= grade <= 3 for grade in relevance.values()):
        raise ValueError("relevance grades must be integers from zero to three")
    relevant = {key for key, grade in relevance.items() if grade > 0}
    hits = sum(key in relevant for key in retrieved[:5])
    reciprocal = next((1 / rank for rank, key in enumerate(retrieved[:10], 1) if key in relevant), 0.0)

    def dcg(grades):
        return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, 1))

    ideal = dcg(sorted(relevance.values(), reverse=True)[:10])
    actual = dcg([relevance.get(key, 0) for key in retrieved[:10]])
    return {"Precision@5": hits / 5, "Recall@5": hits / len(relevant) if relevant else 0.0,
            "MRR": reciprocal, "NDCG@10": actual / ideal if ideal else 0.0}


def macro_average(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    if not rows:
        raise ValueError("cannot summarize an empty query set")
    return {name: statistics.fmean(row[name] for row in rows) for name in ("Precision@5", "Recall@5", "MRR", "NDCG@10")}


def latency_summary(seconds: Sequence[float]) -> dict[str, float | int]:
    """Median and nearest-rank p95; all inputs are measured seconds."""
    if not seconds or any(not math.isfinite(value) or value < 0 for value in seconds):
        raise ValueError("latencies must be nonnegative finite measurements")
    ordered = sorted(seconds)
    return {"samples": len(ordered), "median_ms": statistics.median(ordered) * 1000,
            "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1] * 1000}
