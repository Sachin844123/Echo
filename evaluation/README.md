# Evaluation — reserved for M4

The research question compares recovery of remembered content using keyword,
semantic, hybrid (RRF), and later hybrid with contextual reranking.

No research documents, queries, labels, benchmark results, metrics code or
runner are supplied in M1. `datasets/` is intentionally empty. Unit-test
fixtures in backend/tests are explicitly synthetic TEST DATA and must never
be reported as research evidence.

In M4, the user will supply real documents and labelled queries. That milestone
will define the dataset format and provide Precision@5, Recall@5, MRR,
NDCG@10, latency median/p95, indexing time and memory measurement on identical
data. Tuning and test query splits must remain separate. M5 adds contextual
reranking and weight sweeps restricted to the tuning split. No weights may be
tuned against final-reporting queries.
