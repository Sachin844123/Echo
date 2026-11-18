# Search and index operations — M3

ECHO searches only imported content. M3 implements retrieval correctness and
recoverability; it does not establish research accuracy or laptop performance.

## Model setup

Run `scripts/prepare_model.py` from the repository root with the project Python.
This explicit setup utility downloads the official
`sentence-transformers/all-MiniLM-L6-v2` safetensors and tokenizer/configuration
files. The README pins the verified upstream commit. An omitted `--revision`
resolves the current commit once; it is recorded in `echo-model.json` together
with every downloaded file's SHA-256. Existing destinations are never replaced.
Use `--destination` to prepare another directory, then configure
`ECHO_EMBEDDING_MODEL_DIR`. A prepared directory can be copied to an offline PC.

Runtime verifies the descriptor and file hashes, then loads from that local
directory with `local_files_only=True`, `trust_remote_code=False`, safetensors,
CPU inference and Hub offline/telemetry-disabled settings. No runtime download
or alternative encoder fallback exists. Do not replace model files while the
server is running. One process owns one lazily loaded model; default Torch
threads are two and inference batch size is sixteen windows.

The supported encoder is MiniLM/BERT, 384 dimensions. M2's lexical chunks are
retained with exact offsets. Each input is tokenized without truncation and
split at MiniLM's configured token capacity minus special tokens (normally
254 WordPieces), overlapping by 32 WordPieces. Each window is embedded and
L2-normalized; a token-count-weighted mean is then L2-normalized. This policy
covers long chunks, includes overlap in window weights, and is an experimental
engineering choice to evaluate in M4. Its version is part of the model
fingerprint. It is not a claim that pooling improves recall.

## Search contract

`POST /api/v1/search` accepts JSON, limited to 16 KiB:

```json
{
  "query": "paper describing solar energy storage",
  "mode": "hybrid",
  "limit": 10,
  "source_types": ["pdf", "note"],
  "captured_from": "2025-01-01T00:00:00+05:30",
  "captured_to": "2026-12-31T23:59:59+05:30",
  "collection_id": 1
}
```

Only `query` is required. `mode` defaults to `hybrid`; filters are optional and
combined with AND. `source_types` uses OR within the supplied list. Capture-date
endpoints are inclusive and require a timezone; they never add a recency boost.
The query is nonblank and limited to 2,000 characters. The visible limit is
1–50 and cannot exceed the configured candidate pool. Unknown fields fail
validation with a fixed error message rather than reflecting private input.

| Mode | Ranking |
| --- | --- |
| `keyword` | FTS5 BM25 over chunk text, title and heading; lower raw BM25 ranks first |
| `semantic` | Inner product over L2-normalized MiniLM vectors; higher cosine similarity ranks first |
| `hybrid` | Reciprocal Rank Fusion over both ranked candidate lists |

Keyword terms are literal Unicode word tokens joined with OR. Advanced FTS
syntax is not accepted; punctuation is not an operator. All FTS column weights
use SQLite's defaults. Filters apply **before** each top-50 candidate cutoff.
Semantic search expands FAISS overfetch until enough eligible chunks (including
cutoff ties) are available. Its filtered ID set is drawn from SQLite metadata.

For each chunk, RRF is `sum(1 / (k + rank))` across the lists where it appears;
ranks begin at one and `k` defaults to 60. Raw BM25 and cosine values are never
added. Ties use ascending chunk ID. After ranking, group by source and retain
its best chunk; several candidates from one source can mean fewer than ten
visible results. These defaults will be benchmarked, not treated as optimal.

Each result includes source/document/chunk IDs, title, source type, capture
time, excerpt, page number, heading, half-open character offsets, score and
component ranks. `score` is negative raw BM25 for keyword, cosine for semantic,
or RRF for hybrid: scores are not comparable across modes and are not confidence
probabilities. `candidate_counts` reports each pre-grouping list length.

`indexing_incomplete` is true while any active source is pending, processing or
failed. Keyword search can see newly extracted chunks before their vectors are
ready; do not treat such responses as a fair comparison between methods.
M4 must wait for complete indexing before measuring methods on identical data.
`GET /api/v1/index/status` exposes source counts, vector count, model/manifest
availability and pending deletion count. Availability means that model files
and the snapshot identity validate; actual model loading/inference can still
fail and reports a safe error. It is not a memory/performance guarantee.

Missing or invalid models and model identity mismatches produce `503` on
semantic/hybrid requests. Keyword search remains available. There is no silent
fallback from hybrid to keyword. Failed indexing leaves document/chunks/FTS
intact and exposes an indexing job error; retry through the existing job API.

## Jobs, persistence and reconciliation

Migration `0002_retrieval` backfills `chunk_fts` from existing chunks and adds
`indexing_jobs.stage` (`ingestion` or `indexing`) and an embedding content hash.
Existing M2 jobs become ingestion jobs. Successful extraction publishes chunks,
FTS entries and a new indexing job in the same SQLite transaction. Source
`indexed_at` is assigned only after successful vector publication.

The coordinator processes jobs serially off the ASGI event loop. Each stage
retains attempts and errors; failed jobs are explicitly retried, with a default
three-attempt ceiling. Automatic drift repair queues a new index job only when
no previous job exists or the previous job succeeded. Failed attempts are not
silently reset on every startup. Source/index mutations and search share a lock
so readers cannot observe partial vector publication. A large index job can
delay search and source operations; health remains independent. Inference and
chunk reads use bounded batches, but FAISS stores the complete index in RAM.

Vectors use `IndexIDMap(IndexFlatIP(384))`, with chunk IDs as vector IDs. Each
save writes and fsyncs a new generation, then atomically replaces a manifest
containing model name, model fingerprint, dimension, count, filename and file
checksum. Old generations are removed after publication. Reads validate the
checksum, index type, dimensions, unique positive IDs and vector normalization.
Serialization uses pathlib-compatible streams, including Windows Unicode paths.

SQLite and FAISS do not share a transaction. Vectors are persisted before the
embedding metadata/job completion commit. Under the exclusive process lock,
startup repairs interrupted jobs, completes pending deletions, checks/recreates
FTS triggers, verifies FTS content against normalized tables, and compares
vector IDs, metadata identities and chunk content hashes. It removes orphan or
stale vectors/metadata and queues missing embeddings. Corrupt snapshots rebuild
from durable chunks when a valid model is available. Unreadable disk/storage
errors can still prevent startup or repair; they are not reported as success.

A valid stored index with a different configured model fails closed. It is not
automatically overwritten. Restore the matching model or explicitly reset the
derived vector index while the server is stopped:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m app rebuild-index
..\.venv\Scripts\python.exe -m app serve
```

`rebuild-index` requires the prepared model, acquires the same exclusive process
lock and clears derived vectors/metadata/indexing jobs, then queues fresh work.
It preserves imports, extracted text, chunks and ingestion jobs. It is also the
explicit recovery path after indexing retry attempts are exhausted. Never edit
FAISS files or SQLite rows while the server owns the directory.

## Source and collection APIs

All endpoints require the same token, Host and Origin validation as imports.
Listings use `limit` (1–100) and `offset` (nonnegative). Source metadata excludes
internal file paths and content hashes.

- `GET /sources`, `GET /sources/{id}`: source metadata and processing state.
- `PATCH /sources/{id}` with `{"title":"New title"}`: rename and update FTS titles.
- `GET /sources/{id}/document?offset=0&length=4000`: at most 20,000 characters,
  with document length, extraction status and `has_more`.
- `GET /sources/{id}/chunks?limit=20&offset=0`: excerpt/reference inspection.
- `GET /collections`, `POST /collections` with `name` and optional `description`.
- `PUT /collections/{id}/sources/{source_id}`: idempotent membership addition.
- `DELETE /collections/{id}/sources/{source_id}`: idempotent membership removal.
- `DELETE /collections/{id}`: remove the collection and memberships, retaining sources.

Paths above are relative to `/api/v1`. No raw HTML rendering, arbitrary-path file
download, source-content editing, delete-all endpoint or dashboard is included.

## Source deletion

`DELETE /api/v1/sources/{id}` first commits a tombstone. Searches, previews and
job listings exclude tombstoned sources immediately. It then removes vectors
and old snapshots, deletes the owned import file and cascades database rows,
including FTS entries and collection memberships. A successful response is
`200 {"status":"deleted",...}`. Temporary file/storage failure returns
`202 {"status":"deletion_pending",...}` and retains the tombstone; the worker
and next startup retry cleanup. Check `/index/status` for outstanding deletions.
Attempts to reimport the same bytes while deletion is pending return `409`.

Parser publication checks for deletion before writing, so an in-flight parser
cannot recreate a removed source. A Windows file handle can delay cleanup until
the parser closes. Corrupt owned snapshots can be discarded without the model;
remaining sources require reindexing. Successful deletion means removal from
active application stores, not forensic erasure of SQLite pages/WAL, backups,
filesystem history or SSD blocks.
