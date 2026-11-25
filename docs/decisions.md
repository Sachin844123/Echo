# Decisions

## Search workspace and Activity

- Put the search composer first, then surface recent searches and indexing
  activity using the existing local API. Keep the existing retrieval and
  permission workflows.
- Keep recent searches off by default. Opt-in browser storage retains at most
  12 completed searches with their modes and timestamps. Reuse fills the
  query and mode so the user chooses when to submit. Current filters stay visible.
- Reuse the existing Sources job view as Activity. Show real source counts and
  job timestamps without adding a second activity store.
- Apply theme colors together. Animate button presses with transforms so
  labels stay readable while switching themes.

## Source checkout setup — 2026-11-25

- Use the same Python setup driver from both shell entry points and the
  existing application launcher for migration and browser startup.
- Use the checked-in Python constraints and npm lockfile. Python, SQLite
  FTS5, Node.js, and npm are prerequisites supplied by the user's system.
- Compile Python modules on demand. The initial Windows install spent
  substantial time generating bytecode for installed dependencies.
- Download pinned assets through the existing model preparation utilities.
  Verify existing model assets and preserve them on reruns.
- Coordinate setup per checkout using the existing OS-released lock helper.
  Keep installation files, models, and the library local to the checkout
  by default.
- Run the existing browser launcher from `run.sh` on macOS and Linux.
  Require Node.js at launch only when the dashboard needs a build.

## Dashboard UI refinement — 2026-11-25

- Keep the workspace shell, green accent, system typography, and React/Tailwind
  stack. Separate canvas, navigation, and elevated surfaces with shared tokens.
  Use a small number of short CSS transitions for interaction feedback.
- Apply the saved theme from a same-origin script before the first paint.
  Reuse the existing theme preference key and startup security policy.
- Retain the search result order and relevance semantics from the API. Show
  matching query terms and the existing document passage as supporting evidence.
- Capture the isolated Playwright workspace with labelled test data. Store
  screenshots in ignored local storage.
- Allow four minutes for the Playwright server to become ready on Windows.
  A cold native dependency import exceeded the previous 90-second allowance.

## Local file access and automatic indexing

- Require an explicit persisted permission choice. On Windows, discover fixed
  drives through the OS and use known folders for personal access. Snapshot
  granted roots so a new drive does not expand prior consent automatically.
- Keep a separate path-to-source mapping with size, timestamp and identity.
  Publish the mapping in the ingestion transaction and retain deduplication by
  source content hash. Track manual ownership so revocation preserves manual
  copies. Use durable tombstones for deleted or no-longer-approved sources.
- Let one scanning worker feed the bounded ingestion queue. Use watchdog's
  native Windows notifications without its automatic subtree traversal. Reuse
  the permission-checked `os.scandir` routine for new directories, and reconcile
  periodically to account for missed notifications.
- Validate every path component and the final opened file before reading. Skip
  reparse points and hard links. Block known sensitive locations and recognizable
  key material, and expose only aggregate safe errors in the Storage page.
- Cap automatic storage and leave manual uploads available at all access levels.
  Batch physical cleanup during bulk revocation without changing ranking.

## Direct local startup and Windows launcher — 2026-11-24

- Remove manual authentication from the dashboard. A guarded same-origin
  startup request supplies a randomly generated process credential. The
  dashboard holds it in memory and retries a request once after a stale
  credential is rejected. Native API clients can still set a separate token.
- Keep loopback binding, strict Host and Origin checks, and bearer validation
  before routing API calls. Require browser Fetch Metadata and a custom header
  for the startup route. Cross-origin preflights cannot use that header.
- Use the existing Python environment and a normal Windows batch file. Build
  the dashboard if it is missing and run migrations under the same library
  lock as the CLI. Open the default browser after the local server is ready.

## M7 OCR, image search and retrieval coverage — 2026-11-24

- Use PyMuPDF's Tesseract integration inside the existing parser subprocess.
  Preserve native PDF text and add OCR for scanned pages and raster regions on
  mixed pages. Record how text was extracted so previews can distinguish it
  from filename metadata. Default to English and bound raster size and time.
- Index imported image appearance with CPU CLIP ViT-B/32 and a separate
  source-ID FAISS snapshot. Reuse Torch, Transformers and safetensors. Add
  Pillow for raster decoding, EXIF orientation and metadata-free previews.
  A pinned setup download checks the weights and the runtime verifies the
  manifest. Load CLIP on demand.
- Persist image-vector identity and source hash in SQLite. Publish through
  durable jobs, reconcile snapshots at startup and remove image vectors during
  deletion and reprocessing. Run visual inference outside the library lock
  and recheck the source and job before publication.
- Expand source and job constraints in a transactional SQLite migration under
  the supported launcher's instance lock. Disable foreign-key actions only on
  the migration connection during the rebuild. Check references before commit
  and restore enforcement even when the migration rolls back.
- Correct out-of-vocabulary words only when the local FTS vocabulary has a
  unique close match. Prefer the stronger keyword rank at equal RRF scores.
  Keep the prior candidate profile and old evaluation defaults for comparison.

## M6 development upload fix — 2026-11-19

- A running backend rejected both port-5173 browser origins with 403 while
  credential-free health requests without Origin returned 401. This supports an
  early Origin rejection as the cause of the reported Vite upload resets; no
  user documents or session tokens were read for diagnosis.
- Use a read-only POST session check for login and before each import batch.
  Browsers send Origin on POST, exposing misconfiguration before streaming files.
  Existing per-request security still applies. Keep the production allowlist
  strict and document the explicit backend restart/configuration required for HMR.
- Redact Vite's proxy error logger at the configured logger boundary. Preserve
  visible failures and HTTP status handling without printing private URL query
  parameters or raw error objects. No dependency or migration is added.
- Add real proxy transport tests alongside browser guidance/retry tests. Synthetic
  resets and labelled TEST DATA exercise the failure without opening user files.

## M6 — 2026-11-18

1. **Serve the build on the API origin.** React/TypeScript/Vite/Tailwind output
   is served by FastAPI on loopback. Only the non-sensitive shell/assets are
   public; all API calls retain bearer authentication. No cloud hosting plugin
   is needed. Optional Vite HMR uses an explicit additional loopback origin.
2. **Keep the session in memory.** Paste the existing server token; never embed
   it in a build, URL, cookie or browser storage. Lock/reload clears the session;
   unauthorized responses disconnect. Only the theme preference persists.
3. **Text previews and explicit retrieval.** Render bounded extracted text,
   use Unicode-aware offsets and no HTML rendering. Expose all four modes;
   unavailable semantics remains a visible error rather than silent fallback.
   Hard filters and soft hints stay distinct. Dates are local-day filters.
4. **Recoverable delete-all.** Validate exact confirmation, tombstone all
   sources in one transaction, remove collections/settings and reuse existing
   cleanup/reconciliation. Increment an import generation under the same lock
   to reject uploads that began before the reset. Keep originals/models and
   separate evaluation data. No new schema or backend dependencies.
5. **Minimal frontend dependencies.** Use native fetch with cancellation,
   native modal dialogs, bounded lists, shared SVGs and local system fonts.
   Official build plugins/type declarations support the requested stack.
   Playwright and axe are development-only browser/accessibility tooling;
   Prettier keeps TypeScript/JSX/CSS consistently readable for review.
   Pin resolved packages in a lockfile; no UI/router/animation framework.
6. **Test the actual integration.** Browser tests use a real temporary backend
   and tiny TEST DATA, not a fake production API. Cover session lifecycle,
   ingestion, retrieval, collections, deletion, failure/retry, stale searches,
   keyboard focus, narrow layouts and both themes. Keep browser artifacts
   ignored. Offline embedding correctness remains in the backend tests.

## Editor import resolution — 2026-11-18

- Keep `app` rooted in `backend`, matching the supported server launch and
  pytest configuration. Configure Pylance/Pyright search paths in the existing
  `pyproject.toml` for backend code and test helpers, with analysis scoped to
  backend, evaluation and scripts. Do not suppress missing-import diagnostics.
- Default VS Code to the repository's `.venv` using a portable folder path.
  Pyright CLI uses the same environment; Pylance uses VS Code's selected Python.
  Document interpreter selection for workspaces that already cached another
  interpreter. No dependency, runtime import or M6 change is required.

## M4/M5 audit — 2026-11-18

- Attribute each memory reading to the phase captured before querying process
  RSS. A phase transition during a slow process read must not relabel that
  sample. Aggregate missed child reads under the same statistics lock.
- Stop and join the sampler even when evaluation fails. A final sampling
  failure invalidates an otherwise successful run with a safe code; when a
  primary failure already exists, preserve it and attach a safe sampling note.
- Treat the failure artifact as best effort when storage is unavailable.
  Preserve the primary error and emit an allowlisted
  `failure_artifact_write_failed` event without paths or exception messages.
  A missing completion report still means the run failed. No new dependencies
  or milestone scope changes are needed.

## M5 — 2026-11-18

1. **Rerank the existing hybrid union.** Add explicit `hybrid_contextual` mode
   (evaluation D), retaining hybrid as the API default and preserving A–C.
   Apply hard filters/candidate cutoffs first, then rerank chunks and group by
   source. No new candidates, vector work or recency boost are introduced.

2. **Normalize every component.** Divide RRF by its two-list theoretical maximum,
   use unique normalized query-token coverage for title/heading and chunk text,
   and use binary type/collection matches. Title/heading takes maximum coverage,
   avoiding double-counting the same metadata match. Combine by nonnegative
   normalized weights; tie-break on original RRF then chunk ID. Return signal
   explanations and original RRF. These scores are not confidence probabilities.

3. **Separate soft context from hard filters.** Add optional nested `context`
   with source-type/collection hints. Existing top-level filters still exclude
   candidates; soft context only affects D ranking. Reusing hard filters as
   match signals would be constant for all survivors, so separate hints are
   necessary. Missing/unmatched hints score zero; no wording/history inference
   exists. Dataset hints must be collected independently of relevance judgments.

4. **One validated configuration model.** Shared immutable RerankWeights supports
   API environment JSON and evaluation configuration, finite nonnegative values
   capped at 100, and at least one positive weight. Defaults are explicit untuned
   placeholders. RRF-only weighting preserves C's ordering and enables ablation.
   No new dependency, embedding-model change or schema migration is needed.

5. **Bounded tuning-only grids.** Accept 1–100 explicit complete weight settings,
   reject duplicate vectors/IDs (including case collisions), shuffle settings
   with the recorded seed and reuse one corpus. CLI/internal guards reject test
   sweeps before reading inputs or creating output. The sweep helper selects
   dataset.queries.tuning directly, never the requested final-test queries.

6. **Report every setting, select none automatically.** Save metrics, latency
   samples, weights, configuration hashes and full reusable configurations.
   Prefix config filenames to avoid Windows reserved device names. Restore
   original search settings even on failure; publish completion JSON last.
   Report version 2 records method D/formula identity and optional sweep results.
   Use a predeclared objective on tuning evidence to choose a fixed test config.
   Do not claim effectiveness from synthetic checks or placeholder weights.

## M4 — 2026-11-18

1. **Evaluate the production engine on an isolated corpus.** A CLI run creates
   a new directory, imports only declared local files with existing validation/
   extraction/indexing, applies supplied titles/dates/collections and waits for
   every source to be indexed. Compare exact DB/FTS/embedding/vector ID sets.
   Reuse one corpus for A=keyword, B=semantic and C=hybrid; abort on any failure
   instead of omitting sources or falling back. Preserve the normal library.

2. **Explicit labelled contract.** Require versioned JSON, stable opaque IDs,
   known document references, grades 0–3, timezone-aware dates and nonempty
   tuning/test splits. Resolve files inside the manifest directory; reject
   duplicate bytes because the production importer deduplicates them. Reject
   positive labels excluded by filters and queries with no known positive.
   No research documents, labels or results are invented. Synthetic tests are
   explicitly marked in their inputs and reports.

3. **Hold out queries.** Reject duplicate IDs and normalized query text across
   the dataset. Evaluate exactly the selected split, default tuning; require
   an explicit configuration for final-test CLI runs and fingerprint it. No
   automatic parameter selection or reranker sweep exists in M4. Semantic
   paraphrase leakage and human inspection of test labels require study-design
   discipline; these checks are not a claim of access control over held-out data.

4. **Define metrics precisely.** Score distinct sources: fixed-denominator P@5,
   R@5 against all positive labels, MRR truncated at ten returned sources,
   NDCG@10 with exponential graded gains. Unjudged documents are grade zero.
   Macro-average queries once; latency repetitions do not duplicate quality
   observations. Reject duplicate results or ranking changes between repeats.
   Explicit cutoff metadata avoids presenting truncated MRR as unlimited MRR.

5. **Measure real work, disclose scope.** Use perf_counter for indexing and warm
   in-process search, record per-query samples, median and nearest-rank p95.
   Warm all selected query/method pairs, shuffle queries with a recorded seed,
   rotate method order and keep all methods on the same index. Indexing includes
   first model load but excludes preflight/setup; HTTP overhead and cold-cache
   latency are not claimed. No benchmark findings are inferred from tiny fixtures.

6. **Justified evaluation dependency.** Add psutil to development/evaluation
   requirements, not the API runtime dependency list. Native Torch/FAISS memory
   and parser-child RSS cannot be measured by Python tracemalloc alone. Sample
   parent and summed process-tree RSS, aggregate bounded peak/count state,
   disclose interval/missed children/shared-page double-counting, and label
   peaks as sampled lower bounds. Method-phase RSS is shared-process residency,
   not isolated algorithm attribution. Record the dependency in the lock.

7. **Private reproducible artifacts.** Save JSON/CSV with selected-query IDs,
   ranked document IDs, metrics, timing samples, resource use and dataset/model/
   config/code/environment fingerprints. Omit content, titles, query text,
   input paths and tokens. Preserve private corpus copies for auditing; never
   overwrite a run, delete inputs or auto-publish data. Git-ignore dataset data
   and default run directories. Publish report.json only after successful work;
   failed runs get safe failure codes, not partial success metrics.

## M3 — 2026-11-18

1. **Separate durable stages.** Add revision `0002_retrieval`, preserving M2
   data. Existing jobs become `ingestion`; extraction atomically queues an
   `indexing` job. A failed model/index operation preserves extracted content.
   One coordinator, one model and a shared mutation/search lock keep lifecycle
   state understandable. Search/source operations can wait behind indexing;
   asynchronous parallel model pools are deliberately deferred pending measurement.

2. **Requested retrieval libraries.** Add faiss-cpu and sentence-transformers.
   Declare NumPy explicitly because application code uses its float32/int64
   arrays as FAISS's interface; it is already a required transitive dependency.
   Torch, Transformers, tokenizers, safetensors, Hugging Face Hub and scientific
   dependencies come through sentence-transformers; no orchestration framework,
   separate vector server or additional download client was added. Refresh the
   resolved dependency lock and run `pip check`.

3. **Explicit setup, offline runtime.** A standard-library setup script downloads
   only required official MiniLM files at a recorded revision. Runtime validates
   hashes and uses local safetensors with remote code disabled and offline/
   telemetry-disabled environment settings. No automatic download, secret API
   key, cloud embedding or fake encoder fallback exists. Model absence is a
   visible error; keyword functionality remains usable. Tests use the real model
   for integration and explicitly labelled deterministic vectors only for unit
   ordering/failure cases.

4. **Preserve chunk coverage.** Lexical chunks can exceed MiniLM's WordPiece
   capacity. Embed overlapping 32-WordPiece windows, normalize each, then take
   a token-count-weighted mean and normalize again. Include this policy in the
   model fingerprint. Defaults are hypotheses for M4; no quality improvement is
   claimed. Transformers 5 removed `prepare_for_model`, so construct the supported
   MiniLM/BERT CLS/window/SEP tensors directly. Use the renamed dimension API when
   available; do not suppress deprecation warnings to make tests pass.

5. **FTS as derived state.** A content-bearing FTS5 table indexes text, title and
   heading. Database triggers synchronize inserts, edits, title/source changes
   and cascaded deletion; chunk edits invalidate embedding metadata. Startup
   verifies trigger definitions and actual content and rebuilds on drift. Keep
   virtual/shadow tables outside ORM autogeneration, with static migration SQL.

6. **Recoverable snapshots.** Use normalized vectors in IDMap/FlatIP, chunk IDs
   as vector IDs, checksummed generation files and an atomic manifest pointer.
   Persist FAISS before committing SQLite metadata; reconcile interrupted gaps
   using chunk hashes, IDs and model identity. Remove old snapshots after saves.
   A valid different model never silently overwrites the index: an explicit
   stopped-server `rebuild-index` resets derived state and queues fresh jobs.

7. **Transparent retrieval.** Literal OR keyword tokens and unweighted FTS BM25;
   cosine semantic ranking; RRF with one-based ranks and configurable k=60.
   Apply date/type/collection filters before top-50 selection and group by source
   afterward. Return the best excerpt and references. No raw-score addition,
   recency boost, contextual reranker or confidence interpretation. Report an
   incomplete-index flag so M4 cannot silently compare unequal indexed corpora.

8. **Recoverable deletion.** Commit a tombstone before cross-store cleanup;
   hide the source immediately and retry interrupted removal. Only report
   deletion complete after vectors/old snapshots, owned file and cascaded rows
   are removed. Parser completion cannot resurrect deleted sources. This is
   logical application-store removal, not forensic disk erasure.

9. **Narrow source APIs.** Include metadata, rename, bounded text/chunk preview,
   deletion and minimal collections/membership to make search filters usable.
   Keep all routes authenticated; restrict JSON request sizes and new CORS
   methods explicitly. No frontend, arbitrary file-serving, content-editing,
   delete-all or evaluation scaffolding is introduced.

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
