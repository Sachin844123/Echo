# ECHO

ECHO is a local-first personal document memory and retrieval research project.
It will search **only content the user explicitly imports**. It cannot recover
uncaptured information or remember everything.

The research question is whether hybrid keyword + semantic retrieval, with and
without contextual reranking, recovers remembered content better than either
retrieval method alone on a labelled dataset. Evaluation is the primary
deliverable; no retrieval results or accuracy claims exist yet.

**Current scope: Milestone 2 ingestion.** The authenticated local API imports
PDF, TXT, Markdown, DOCX and manual notes into durable background jobs. It
validates files, extracts and cleans text, records metadata, and stores chunks.
Search, embedding/FTS indexing, evaluation, deletion endpoints and a dashboard
are not implemented yet. Successful ingestion means ready for future indexing.

## Setup (Windows PowerShell)

Requires Python 3.11+ with SQLite FTS5. This milestone is tested on Windows with
Python 3.12.6 and SQLite 3.45.3; Python 3.11 is not yet tested. From the repository:

```powershell
Set-Location C:\Projects\Echo
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt -c backend\requirements-lock.txt
```

The last file records the exact resolved M2 environment, including transitive
dependencies. It is a version lock, not a hash-verified supply-chain lock.
Package installation may need internet access. ECHO itself makes no outbound
network or AI API calls and contains no telemetry integration. No model is
downloaded in M1 or M2. The isolated virtual environment avoids unrelated global
Python packages. Shell activation and execution-policy changes are unnecessary.

## Run

```powershell
Set-Location C:\Projects\Echo\backend
..\.venv\Scripts\python.exe -m app migrate
$env:ECHO_SESSION_TOKEN = (& ..\.venv\Scripts\python.exe -m app token).Trim()
..\.venv\Scripts\python.exe -m app serve
```

The supported launcher binds to `127.0.0.1:8000`, with one worker, no reload,
no proxy-header trust, no access log, and no WebSocket transport. Stop with
Ctrl+C. Generate a new token before each session. Restart the server to rotate
an existing token; changing an environment variable does not change a running
process. Clear your shell's copy after stopping:

```powershell
Remove-Item Env:ECHO_SESSION_TOKEN
```

`GET http://127.0.0.1:8000/api/v1/health` requires
`Authorization: Bearer <session-token>`. The token command produces 256 bits of
randomness and is captured above without displaying or persisting the token.
Give API clients the same token through private local input, never a query
parameter. An ordinary browser address-bar request receives 401. Swagger,
ReDoc and OpenAPI endpoints are disabled.

A healthy authenticated request returns:

```json
{"status":"ok","version":"0.2.0","database":"ok"}
```

Missing/invalid tokens return 401; disallowed origins or non-loopback clients
return 403; invalid Host headers return 400. Database health failures return
503. Startup refuses missing or outdated databases. Migration is explicit and
idempotent; stop the server before applying migrations. Back up the data
directory before future schema upgrades. Do not run schema downgrades on real
data; the initial downgrade removes all tables.

## Import and inspect

All endpoints use the same session token. File imports use a raw request body,
not multipart form data. With the server running and the same token set in your
client PowerShell session:

```powershell
$headers = @{ Authorization = "Bearer $env:ECHO_SESSION_TOKEN" }
$job = Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8000/api/v1/imports/files?filename=paper.pdf' `
  -Headers $headers -ContentType 'application/octet-stream' -InFile 'C:\path\paper.pdf'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/indexing-jobs/$($job.job_id)" -Headers $headers
```

Replace the path and filename with a document you own. Never put the token in
the URL. For a manual note, POST JSON containing `title` and `text` to
`/api/v1/imports/notes`. New imports return 202 with `source_id`, `job_id`, and
`duplicate: false`. Identical captured bytes return 200 and the existing IDs.
Poll the job until `succeeded` or `failed`. Failed jobs return a fixed error
code/message and whether they can be retried.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/imports/files?filename=<name>` | Stream a PDF/TXT/MD/Markdown/DOCX file |
| `POST /api/v1/imports/notes` | Import a note; JSON title ≤200 and text ≤100,000 characters |
| `GET /api/v1/indexing-jobs?limit=20&offset=0` | Paginated recent jobs and worker liveness |
| `GET /api/v1/indexing-jobs/{id}` | Status, attempts, sanitized error and chunk count |
| `POST /api/v1/indexing-jobs/{id}/retry` | Retry a failed job below the attempt limit |

Inspect prepared chunks locally, with the server stopped or running:

```powershell
Set-Location C:\Projects\Echo
.\.venv\Scripts\python.exe scripts\inspect_chunks.py --source-id 1 --limit 20
# Explicit private-content display, not an application log:
.\.venv\Scripts\python.exe scripts\inspect_chunks.py --source-id 1 --show-text
```

See `docs/ingestion.md` for file validation, recovery, chunking semantics,
limitations and the distinction between ingestion and search indexing.

## Test

```powershell
Set-Location C:\Projects\Echo
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Tests use isolated temporary databases and tiny labelled test fixtures. They
include a real subprocess server and HTTP requests to a dynamically chosen
loopback port; they do not need imported documents, an embedding model or
external services. The final executed results are in `docs/PROGRESS.md`.

## Configuration

Environment variables are read explicitly; `.env` files are not loaded. Values
are validated with Pydantic. No token is stored in SQLite or in the repository.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ECHO_DATA_DIR` | repository `.local` directory | Local SQLite storage; relative paths resolve against the launch directory |
| `ECHO_HOST` | `127.0.0.1` | Any other value is rejected |
| `ECHO_PORT` | `8000` | Integer 1024–65535 |
| `ECHO_SESSION_TOKEN` | absent | Required to serve; generate with the CLI; 43–128 URL-safe characters |
| `ECHO_ALLOWED_ORIGINS` | `["http://127.0.0.1:<port>"]` | JSON array of exact loopback HTTP origins with explicit ports; no wildcards or trailing slash |
| `ECHO_LOG_LEVEL` | `INFO` | `INFO`, `WARNING` or `ERROR` |
| `ECHO_MAX_UPLOAD_BYTES` | `20971520` (20 MiB) | Per-file limit; checked against actual bytes, even without Content-Length |
| `ECHO_MAX_EXTRACTED_CHARS` | `5000000` | Cleaned document character ceiling |
| `ECHO_MAX_PDF_PAGES` | `2000` | PDF page ceiling |
| `ECHO_MAX_DOCX_EXPANDED_BYTES` | `67108864` (64 MiB) | Sum of uncompressed DOCX members |
| `ECHO_EXTRACTION_TIMEOUT_SECONDS` | `120` | Time allowed for each parser process |
| `ECHO_CHUNK_TOKENS` | `350` | Lexical-token window, not a model's WordPiece count |
| `ECHO_CHUNK_OVERLAP` | `60` | Lexical-token overlap; must be below the window |
| `ECHO_MAX_JOB_ATTEMPTS` | `3` | Includes interrupted attempts; retries are explicit except crash recovery |
| `ECHO_MAX_PENDING_JOBS` | `100` | Pending + running queue capacity |

Origin-less authenticated requests are supported for native/CLI clients.
If a browser sends Origin, it must match the allowlist exactly, including for
same-origin requests. `localhost` as a Host is accepted on the configured port,
but its browser Origin requires explicit allowlisting. CORS permits GET/POST
and Authorization/Content-Type headers. Browser preflight is transport metadata,
not an API call: an allowed OPTIONS preflight requires no token and invokes no
route. Every actual API request, including health and unknown routes, requires
a valid token.

Logs contain fixed event names, UTC timestamps, status codes, generated request
IDs, job/source IDs, durations and exception class names. They exclude bodies, URLs, queries,
paths, headers, SQL parameters and exception text. Data is **not encrypted at
rest**. Use a private local data directory; this is not a defense against
malware or other code running as the same OS user.

## Layout and milestone boundary

```text
backend/
  app/                 API, core, database and security implementation
                       ingestion/extraction/processing/storage (M2 packages)
                       embeddings/retrieval (M3 packages)
  migrations/          immutable Alembic revisions
  tests/               foundation, security and real-server tests
scripts/
  inspect_chunks.py    bounded metadata inspection; explicit text opt-in
evaluation/
  datasets/            empty; user-supplied research data arrives in M4
  README.md            research scope only, no fabricated results
docs/
  PROGRESS.md           status, file inventory, executed checks, limitations
  decisions.md          rationale and dependency decisions
  schema.md             schema and invariants
  security-model.md     protections and trust boundaries
  ingestion.md          import contract, job recovery, formats and limits
```

M2 is ingestion; M3 is retrieval (including FTS5 synchronization, FAISS,
deletion consistency and reconciliation); M4 is evaluation; M5 is contextual
reranking; M6 is hardening and a local dashboard. Each requires an explicit
continuation. No frontend directory exists before M6. OCR and webpage capture
are optional and require an explicit request.

Desktop packaging, extensions, mobile, cloud sync, accounts, installers,
PostgreSQL, local LLMs, LangChain/LangGraph and vector database servers are
future-work discussion only; none is scaffolded here.
