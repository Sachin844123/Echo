# Decisions

## M2 — 2026-11-17–18

1. **Keep the schema.** M1's normalized tables already represent M2. Do not
   rebuild SQLite tables or change the immutable migration without a schema
   need. Ingestion jobs succeed when text/chunks are committed; indexed_at stays
   NULL and source processing status returns to pending until M3 actually
   indexes it. Expose ready_for_indexing explicitly in job responses. M3 must
   distinguish subsequent retrieval-index work when extending the job lifecycle.

2. **Raw-body upload protocol.** Stream file bytes directly, with a filename
   query parameter, instead of adding multipart parsing. Validate actual bytes
   and count them independently of Content-Length. Notes use bounded JSON.
   Supplied filenames provide title/extension metadata; random identifiers own
   all on-disk paths. No arbitrary-path import or URL capture endpoint exists.

3. **Format inspection.** Use PDF signature recognition, structural OOXML ZIP
   validation, and complete strict text decoding. Do not add libmagic/system DLL
   requirements on Windows. Text and Markdown are inherently indistinguishable
   by magic bytes: extension selects subtype only after text validation.
   Corrupt signed PDFs can be accepted into the queue and then fail visibly
   during parsing. Encrypted PDFs and unsafe DOCX packages are unsupported.

4. **Requested parser dependencies only.** Add PyMuPDF and python-docx from the
   requested stack. python-docx brings lxml as its required XML dependency.
   No OCR, encoding detector, Markdown renderer, multipart parser, task queue,
   model tokenizer or process-lock library is added. Record resolved versions
   in requirements-lock.txt. Use the standard library for signatures, ZIP,
   SHA-256, process lifecycle and Windows/POSIX locking.

5. **One parser process per job.** A coordinator thread runs durable SQLite jobs
   serially. It starts one short-lived child for extraction, rather than using
   PyMuPDF concurrently on request threads. This follows the
   [PyMuPDF process guidance](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html)
   and allows timeouts and shutdown termination. The subprocess receives no
   ECHO session-token environment variable and returns only safe status codes.
   This is fault isolation, not an OS sandbox or hard memory quota.

6. **Bounded work.** Process PDF pages and text incrementally; reject oversized
   archives and documents. DOCX requires a bounded in-memory XML tree. Its body
   iterator preserves paragraph/table order, following
   [python-docx's document API](https://python-docx.readthedocs.io/en/latest/api/document.html).
   The existing extracted_text column requires one final bounded text value;
   avoid claiming constant memory. Chunks use a rolling token window and DB
   batches of 100. Limits and excluded DOCX content are documented explicitly.

7. **Lexical chunking before embeddings.** Use deterministic Unicode words and
   punctuation, with long runs split at 32 characters, default window 350 and
   overlap 60. Preserve exact cleaned-document offsets. Never cross PDF pages
   or heading changes; preserve overlap across streaming records. No model
   download is justified in M2. M3 must reconcile these sizes with MiniLM's
   tokenizer/context limit. No retrieval quality is inferred from these defaults.

8. **Durable queue and atomic publication.** Persist source + pending job only
   after a flushed input file is renamed into owned storage. Duplicate hashes
   reuse the first capture, including metadata. Publish document/chunks/job
   success in one transaction. Keep failed inputs for explicit retry; attempts
   are capped and retries also honor queue capacity. Preserve fixed error codes,
   never parser text. FTS/FAISS reconciliation remains wholly in M3.

9. **Single-instance recovery.** An OS-released data-directory lock prevents a
   second server from resetting active jobs. Startup requeues interrupted jobs
   below their attempt limit and cleans only recognized orphan paths. Pending
   work is rediscovered from SQLite. Normal shutdown cancels its active parser.
   An abrupt parent kill may leave a parser child until it exits, but children
   cannot publish database state. This limitation is documented, not presented
   as guaranteed process-tree containment.

10. **Inspection is explicit.** The chunk inspection script prints metadata
    unless --show-text is supplied. Intentional private terminal output is
    separate from application logs, which continue excluding captured content.
    All new parser fixtures are synthetic TEST DATA, never a research dataset.

## M1 — 2026-11-17

1. **Repository scope.** Use the existing `C:\Projects\Echo` as the repository
   root, without nesting another `echo` directory. Initial inspection found an
   empty directory, no Git repository, and no applicable parent AGENTS.md.
   Initialize Git, but do not create a commit or remote. Build M1 only.

2. **Explicit migrations.** Alembic owns schema creation; application imports
   and startup do not call `create_all`. Startup checks the current revision
   and fails closed if migration is needed. The revision contains fixed SQL
   types, not imports of mutable application models. Migration upgrades and
   downgrades are tested, including populated databases.

3. **SQLite operational defaults.** Enable FK enforcement on every connection,
   WAL, a five-second busy timeout and FULL synchronous durability. A two-slot
   pool bounds connections. Explicit BEGIN fixes SQLite driver's legacy
   transaction behavior across Python versions. Keep the database on a local
   disk; network shares are not a supported target. See the
   [SQLAlchemy SQLite documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
   and [SQLite foreign-key documentation](https://sqlite.org/foreignkeys.html).

4. **Normalized schema.** One extracted document per source, one active
   embedding record per chunk, and source membership in many collections.
   Chunk IDs are never reused and must equal vector IDs. A future model switch
   requires rebuilding the active index; concurrent model indexes are not
   represented. Store timestamps as UTC; reject naive Python datetime input.
   Use database triggers for updated_at on mutable records, including raw SQL
   writes. SQLAlchemy relationships are not needed for foundation operations;
   database FKs own cascading deletion. M3 will coordinate files and FAISS.

5. **Milestone boundary.** Create all requested ordinary tables in M1, but
   defer the FTS5 virtual table, synchronization triggers, vector implementation
   and reconciliation to M3. M1 probes FTS5 capability in a throwaway in-memory
   database. Empty package namespaces satisfy the requested layout without
   fake ingestion/search implementations. Evaluation algorithms and datasets
   await M4; no metrics or runner stubs exist.

6. **Local session authentication.** Generate a 32-byte random bearer token
   through a CLI command, then pass it via the process environment. There is
   no unauthenticated token-discovery endpoint or token file to secure with
   platform-specific ACL tooling. Tokens remain stable for a process lifetime;
   rotate by generating a fresh one and restarting. Reject missing tokens at
   startup; compare tokens with constant-time comparison. Token syntax checks
   cannot prove entropy: use the generator rather than a hand-chosen token.

7. **Request boundary.** Bind only to 127.0.0.1 via the supported launcher,
   disable proxy-header trust and enforce loopback client addresses. Validate
   Host against exact loopback authorities and Origin against explicit local
   origins before authentication and routing. Permit no-Origin CLI requests
   with a valid token. Handle CORS preflight without a token only after origin,
   host and peer validation; it returns transport policy and never calls an
   API route. This is necessary for browser bearer authentication. See
   [Starlette middleware documentation](https://www.starlette.io/middleware/).

8. **Minimal dependencies.** FastAPI, Pydantic, SQLAlchemy and Alembic are from
   the requested stack. Uvicorn is necessary to serve ASGI. HTTPX is a test-only
   dependency required by Starlette TestClient and the real-server smoke test.
   Use the standard library for logging, environment loading, paths, secrets
   and JSON. No dotenv, pydantic-settings, structured-logging package, async
   SQLite driver, packaging build system or migration plugin is necessary.
   Model/extraction dependencies will be added only in their milestones.

9. **Dependency compatibility.** An initial unbounded-compatible install
   selected FastAPI 0.163.1 and Starlette 1.10.0. Test collection exposed a
   deprecated HTTPX client interface. The newest FastAPI also introduced a
   telemetry integration unnecessary for ECHO. Select FastAPI 0.141.1, constrain
   Starlette below 1.0 and AnyIO below 4.13 (the newer AnyIO deprecated a symbol
   used by Starlette 0.52.1). No warning was suppressed to pass tests. Remove the
   unused OpenTelemetry package and record the full resolved environment in
   requirements-lock.txt. Reassess these constraints when upgrading together.

10. **Logging and errors.** Use allowlisted JSON events and scalar metadata;
    never format arbitrary messages, exception text or tracebacks. Keep error
    responses generic and correlate them through generated request IDs. Fixed
    event names and exception classes retain operational failures without
    capturing content. Disable request access logs. Health executes a real
    SQLite query in FastAPI's thread pool; startup checks run off the event loop.

11. **Privacy defaults.** No search-history functionality or telemetry exists.
    There are no outbound runtime calls. Local SQL data and environment tokens
    are not encrypted. Ingestion security and full deletion semantics arrive
    in their designated milestones and are not claimed by M1.
