# ECHO progress

## Current state — 2026-11-18 (Asia/Calcutta)

**M1, M2 and M3 SEARCH ENGINE are complete and tested. Stopped at the M3 boundary.**
M1/M2 remain preserved. M4–M6 and optional M7 are unstarted. Stop at the M3
handoff; M4 needs a subsequent user instruction to continue.

## M3 delivered

- SQLite FTS5 text/title/heading index, synchronization triggers, populated-M2
  migration and startup integrity/content/trigger reconciliation.
- Offline MiniLM, one lazy model instance, CPU/batch configuration, bounded
  WordPiece window pooling and explicit setup-only model provisioning.
- Normalized FAISS IDMap/FlatIP with chunk IDs, checksummed generation files,
  atomic manifests, model fingerprints and explicit model-mismatch refusal.
- Keyword, semantic and RRF hybrid search; type/date/collection filters before
  candidate cutoff; deterministic source grouping and referenced excerpts.
- Durable ingestion/indexing stages, retained attempts, safe failures, retry,
  orphan/stale-vector repair and an explicit `rebuild-index` CLI.
- Source metadata/rename/preview/deletion and minimal collections/membership;
  recoverable deletion tombstones spanning SQLite, FTS, FAISS and owned files.
- Authenticated bounded search/management APIs, explicit readiness/incomplete
  status, real-model integration and synthetic fault/ordering fixtures.

### M3 files

New implementation: `backend/app/api/{search,sources}.py`,
`backend/app/database/fts.py`, `backend/app/embeddings/local.py`,
`backend/app/retrieval/{engine,errors,vectors}.py`,
`backend/migrations/versions/0002_retrieval.py`, `scripts/prepare_model.py`.
Updated integration: application version/launcher/factory, configuration,
database models/migration helper, ingestion service and Alembic environment.

New tests: `test_retrieval.py`, `test_search_api.py`, `test_embeddings.py`.
Updated fixtures and API/CLI/schema/ingestion regression expectations for M3.
Updated dependency requirements and exact resolved lock. Documentation changes:
README, this file, decisions, schema, security model, ingestion, new search
specification, CHANGELOG and AGENTS milestone boundary. No evaluation/frontend
files were created or changed.

### M3 verification

Executed from `C:\Projects\Echo` with the isolated project environment:

- Schema suite: `32 passed in 10.60s` before additional M3 upgrade tests.
- Initial retrieval unit/recovery suite: `13 passed in 5.79s`.
- Focused API, retrieval and actual offline-model integration suite:
  `27 passed in 89.13s (0:01:29)`.
- Real-model smoke: `(2, 384)`, norms `[1. 0.99999994]`, loaded-instance reuse
  `True`. This verifies shape/normalization/reuse, not retrieval performance.
- Dependency validation: `No broken requirements found.`
- Full regression: `.venv\Scripts\python.exe -m pytest -q --tb=short`
  returned **`195 passed in 200.21s (0:03:20)`**, with no skipped tests or warnings.
- `git diff --check` and local documentation-link validation passed.
- The default local database contained zero sources before upgrade; the supported
  `python -m app migrate` command completed successfully to revision
  `0002_retrieval`. No synthetic fixture documents were imported into it.

Commands to run from the repository root after dependencies/model provisioning:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m app migrate
$env:ECHO_SESSION_TOKEN = (& ..\.venv\Scripts\python.exe -m app token).Trim()
..\.venv\Scripts\python.exe -m app serve
```

Tests, from a repository-root terminal:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe -m pip check
```

Testing exposed Transformers 5's removed tokenizer preparation method and renamed
dimension API. The implementation now constructs supported MiniLM/BERT tensors
directly and uses the current dimension method with older-version compatibility.
No warning was suppressed. M2 assertions about ingestion-only job counts/source
pending state and the old CORS method list were updated for separate indexing
jobs and the new management routes. No failing test was ignored.

The model was provisioned at upstream revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Model files, local data, caches and the
virtual environment remain Git-ignored. The README requested before M3 was
committed locally as `f166176`; M3 implementation changes are separate.

### M3 decisions and limitations

- Additional direct NumPy declaration supplies the FAISS array interface;
  other new direct packages are the requested faiss-cpu/sentence-transformers.
- One CPU worker/model avoids parallel model copies. Search/source mutations
  are serialized with indexing, so large jobs can delay those requests.
- FAISS index and serialization require memory proportional to corpus size.
  No i3/8-GB memory or latency guarantee has been measured. WordPiece pooling
  and retrieval defaults need M4 evaluation, not claims of proven superiority.
- A prepared model is required for semantic operations; missing-model errors
  retain extraction and keyword usability. Real-model tests explicitly skip
  only if their local model descriptor is absent; they never download fixtures.
- Failed indexing retries respect attempt caps; exhausted jobs can be reset
  through explicit `rebuild-index`. Permanent disk/path failures can leave a
  visible pending deletion or prevent repair; no false completion is returned.
- Deletion is application-store removal, not forensic erasure of WAL/backups/SSD
  blocks. There is no at-rest or end-to-end encryption claim.
- No contextual reranker, evaluation runner/data/results, frontend, OCR, webpage
  capture or packaging was implemented. Windows/Python 3.12.6 is verified;
  Python 3.11 and other platforms remain unverified.

## Environment and preserved M1 foundation

The original workspace at `C:\Projects\Echo` was empty. M1 initialized Git,
created an isolated `.venv`, and established the normalized schema, migration,
authenticated local API and security boundary. No commit or remote was created.
M2 inspection found that foundation intact and preserved it.

Testing uses Windows, Python 3.12.6 and SQLite 3.45.3 with FTS5 available. Python
3.11 and other OS versions have not been verified. Global Python packages were
not modified. M1's recorded final suite was `85 passed in 27.83s`.

## M2 delivered

- Authenticated raw-file imports for PDF/TXT/Markdown/DOCX and JSON manual notes.
- Streaming byte ceilings, content-based detection, strict text decoding,
  filename/path defense and bounded/safe DOCX archive validation.
- SHA-256 duplicate detection across captured bytes; concurrent duplicates
  return the same source/job and create only one stored file.
- Page-oriented PDF, incremental text/Markdown and ordered DOCX body/table
  extraction, Unicode/whitespace cleaning and capture/extraction metadata.
- Default 350-token lexical windows with 60-token overlap, page/heading
  boundaries, exact cleaned-text offsets and batches of 100 chunk inserts.
- Durable jobs with status/list/retry endpoints, attempts and queue limits,
  one parser child at a time, timeout/cancellation and safe error codes.
- Atomic document/chunk/job publication, exclusive instance locking,
  interrupted-job recovery and app-owned orphan-file cleanup.
- `scripts/inspect_chunks.py` with metadata-only default and explicit text opt-in.
- Setup/API/limits/recovery documentation and synthetic TEST DATA fixtures.

There is no schema change: revision `0001_foundation` already supports M2.
Source `indexed_at` remains NULL. A succeeded ingestion job reports
`ready_for_indexing`; it does not claim the content is searchable. Source
processing_status returns to pending until M3 implements actual indexing.

## M2 files created

```text
backend/app/api/ingestion.py
backend/app/ingestion/errors.py
backend/app/ingestion/service.py
backend/app/security/file_validation.py
backend/app/storage/files.py
backend/app/storage/instance_lock.py
backend/app/extraction/parsers.py
backend/app/extraction/worker.py
backend/app/processing/text.py
backend/app/processing/chunking.py
backend/tests/test_file_validation.py
backend/tests/test_processing.py
backend/tests/test_ingestion.py
backend/tests/test_jobs.py
backend/tests/test_ingestion_limits.py
scripts/inspect_chunks.py
docs/ingestion.md
```

## M2 files modified

```text
AGENTS.md
README.md
CHANGELOG.md
backend/requirements.txt
backend/requirements-lock.txt
backend/app/__init__.py
backend/app/main.py
backend/app/core/config.py
backend/app/core/logging.py
backend/app/ingestion/__init__.py
backend/app/extraction/__init__.py
backend/app/processing/__init__.py
backend/app/storage/__init__.py
backend/tests/test_api.py
backend/tests/test_cli.py
docs/PROGRESS.md
docs/decisions.md
docs/schema.md
docs/security-model.md
```

Existing migrations, models, evaluation scope and M3 package namespaces are
unchanged. There is no frontend, search stub, benchmark dataset, model download
or out-of-scope integration. M1/M2 source, tests and documentation are tracked
in Git, with origin linked to https://github.com/Sachin844123/Echo.git.
`.venv`, `.local` and test caches remain ignored local artifacts.

## Exact setup, run and test commands

Install/update the isolated environment from the root (the environment already
exists here; create it with `py -3.12 -m venv .venv` on a fresh checkout):

```powershell
Set-Location C:\Projects\Echo
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt -c backend\requirements-lock.txt
```

Run:

```powershell
Set-Location C:\Projects\Echo\backend
..\.venv\Scripts\python.exe -m app migrate
$env:ECHO_SESSION_TOKEN = (& ..\.venv\Scripts\python.exe -m app token).Trim()
..\.venv\Scripts\python.exe -m app serve
```

Test and inspect:

```powershell
Set-Location C:\Projects\Echo
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\inspect_chunks.py --source-id 1 --limit 20
```

Use `--show-text` only when deliberately displaying private chunk text. All API
calls require the session token; import examples and endpoints are in README.md.
Tests require local loopback networking for Windows asyncio/TestClient and the
real-server smoke test, but no external service or model.

## Executed verification

Final complete-suite result, executed on Windows / Python 3.12.6:

```text
........................................................................ [ 44%]
........................................................................ [ 88%]
..................                                                       [100%]
162 passed in 79.18s (0:01:19)
```

No tests failed or were skipped, and no warnings were reported. The suite ran
with approved local-loopback access because the Windows sandbox otherwise
blocks asyncio's internal socket-pair setup.

Additional final checks:

```text
No broken requirements found.
Trailing whitespace check: PASS
Default database sources: 0
Schema revision: 0001_foundation
```

The inspection script also exited successfully against the empty default
database. Test fixtures did not populate the user's working library.

Completed intermediate checks:

- Validation/configuration/chunking: `52 passed in 2.32s`.
- Actual parser/API/recovery tests: `34 passed in 40.71s`.
- First complete M1+M2 regression: `160 passed in 94.63s (0:01:34)`.
- Extended real-server upload/status/log-redaction test after its harness fix:
  `1 passed in 10.12s`.
- `python -m pip check`: `No broken requirements found.`

No failing test was ignored. A new timeout-test double initially assumed
constructor arguments before being spawned; its fixture setup was corrected.
Review then added queue-capacity enforcement for retries and suppressed false
Markdown headings inside fenced code. Extending the real-server test exposed
an undrained stderr PIPE: request polling filled the pipe and blocked server
logging. The harness now captures stderr in a temporary file and still checks
that tokens, query text and imported content are absent from logs. The final
full suite passed after those changes.

Tests cover real file parsers, UTF-16/Unicode, nested DOCX tables, multi-page
PDFs, no-text/encrypted/corrupt PDFs, binary/extension mismatches, hostile ZIPs,
streamed uploads with misleading or absent lengths, disconnected uploads,
concurrent duplicates, retry caps, queue caps, process timeouts/shutdown,
publication rollback after partial batch insertion, a genuinely new interpreter
recovering queued work, stored-file hash/path failures and guarded inspection.
All fixture content is clearly synthetic TEST DATA, not research evidence.

## Decisions and known limitations

- New direct dependencies are only the requested PyMuPDF and python-docx;
  lxml is python-docx's XML dependency. Exact resolved versions are locked.
- Raw-body uploads avoid a multipart dependency. Format inspection does not
  rely on client MIME claims; Markdown subtype requires an extension because
  plain text and Markdown do not have distinct binary signatures.
- The coordinator owns one data directory and runs one parser process at a
  time. This respects PyMuPDF's process guidance and bounds concurrency.
- Parser processes are not an OS sandbox and have no hard RSS quota. DOCX
  loads a bounded XML tree; native PDF parsing can allocate before text checks.
  An abruptly killed parent may leave a parser child until it exits, though
  children cannot publish DB state. Normal shutdown terminates active parsing.
- Defaults: 20 MiB upload, 5,000,000 extracted characters, 2,000 PDF pages,
  64 MiB expanded DOCX, 120-second parser timeout, 100 queued/running jobs,
  three total attempts. These are configurable engineering defaults, not
  measured performance guarantees.
- Chunk tokens are lexical approximations, not MiniLM WordPieces. M3 must
  respect model input limits. Complex PDF reading order, DOCX ancillary content,
  legacy text encodings and a complete Markdown renderer are unsupported.
- No OCR, webpage capture, embeddings, persistent FTS5 table, FAISS, search,
  evaluation runner, source/deletion API or dashboard was built. No real corpus,
  relevance labels, accuracy, indexing-speed or memory results were fabricated.
- Files and database are not encrypted at rest. Same-user malicious code and
  administrators are outside the local HTTP trust boundary. Broader rate/disk
  quotas and final dashboard hardening remain for M6.

Detailed rationale is in decisions.md; the import contract and recovery model
are in ingestion.md. No server is intentionally left running after verification.
