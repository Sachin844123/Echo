# Local security model — M1–M7

ECHO is a single-user local process. The primary boundaries are the loopback
HTTP server, browser origin checks and the user's filesystem permissions.
The dashboard opens directly for people using the running local browser.

## Implemented

- Automatic storage indexing requires a persisted opt-in scope. Only approved,
  eligible paths are read. The original files remain in place. The storage
  endpoints are authenticated, and revocation tombstones automatic-only sources
  for local cleanup. See [Storage & Permissions](local-storage.md) for the path
  checks, storage caps and sensitive-file filtering limits.

- The supported `python -m app serve` launcher binds to 127.0.0.1 only.
  Configuration rejects non-loopback bind addresses. One worker, no reload,
  no proxy trust, no WebSockets, no public docs/OpenAPI route.
- Every HTTP API request requires a bearer token, including health, errors
  reached by unknown routes and ordinary OPTIONS requests. No query-string or
  cookie authentication. Duplicate Authorization headers fail closed.
- `POST /session/open` is a dashboard startup route outside the protected API.
  It requires a permitted local origin, `Sec-Fetch-Site: same-origin` and the
  `X-Echo-Dashboard` header, which cross-origin preflights do not permit. It
  returns only the runtime dashboard credential with `Cache-Control: no-store`.
  The browser uses that credential for API requests and renews it after a
  rejected stale credential. The server creates it from 32 random bytes on
  each app start. An optional `ECHO_SESSION_TOKEN` for native clients is never
  returned to the dashboard.
- The peer must be 127.0.0.1. Exact Host validation permits only 127.0.0.1 or
  localhost with the configured port, mitigating browser DNS rebinding.
  Duplicate Host/Origin headers are rejected. Proxy headers cannot change the
  peer address through the supported launcher.
- Browser Origin must exactly match an explicit local allowlist. Wildcards,
  null origins, userinfo, nonlocal hosts, non-HTTP schemes, paths, queries and
  fragments are rejected. Native clients may omit Origin but still need the
  token. Origin and CORS are additional browser boundaries, not authentication.
- Imports use an authenticated, body-free POST session check so browsers
  send Origin before transferring a document. The Vite proxy preserves Origin and token
  checks. Development requires explicitly allowing its exact loopback origin
  before backend startup; no Origin rewriting or broad default allowance is used.
  Proxy transport diagnostics omit request URLs, filenames and raw error stacks.
- CORS allows GET/POST/PATCH/PUT/DELETE and Authorization/Content-Type, no credential cookies. A
  validated browser preflight may be unauthenticated because browsers do not
  send bearer credentials on preflight. It invokes no route and exposes no
  application data. Requests that follow it must authenticate.
- Responses have no-store, nosniff and generated request IDs. Database health
  errors return 503 and unexpected failures return generic 500 responses.
- Image previews require bearer authentication and are re-encoded at a bounded
  size. The dashboard displays them through temporary blob URLs and revokes
  each URL when its preview closes. CSP permits blob URLs for images only.
- PNG and JPEG imports undergo signature and dimension checks before decoding.
  OCR runs in the timed parser subprocess. CLIP loads verified local weights
  and uses no network at runtime. Visual deletion purges the source vector
  and any obsolete snapshots through the existing tombstone cleanup.
- GET/HEAD `/`, `/favicon.svg` and `/assets/*` serve the empty shell and compiled
  assets without a token. Host, Origin and peer checks apply to static content
  too. StaticFiles confines asset access to the build.
- Production responses add a restrictive self-only script/style/connect CSP,
  no inline scripts/styles, no framing, no referrers and disabled camera,
  microphone and geolocation permissions. Framework parameter validation is
  redacted instead of echoing user-supplied values.
- The dashboard keeps its credential and document/query state in tab memory.
  Reloading opens a fresh dashboard connection. Only a versioned theme
  preference persists. Previews render text instead of imported HTML.
  There is no service worker or browser-side content/history cache.
- Structured logs use a field/event allowlist. Content, queries, URLs, paths,
  tokens, headers, SQL parameters, exception messages and tracebacks are
  excluded. There are no content-bearing access logs or search history.
- No outbound runtime HTTP, AI calls or telemetry integration. Dependency
  installation is a separate setup operation. Tests deny external socket
  connections in-process and exercise a real local HTTP server.
- Uploads are streamed to randomly named staging files under app-owned local
  storage. Actual byte counts enforce the upload ceiling; Content-Length alone
  is insufficient. Interrupted/rejected uploads remove partial files. Notes
  have a bounded JSON body and bounded validated fields.
- Client filenames cannot contain directories, drive letters, UNC paths or
  alternate streams. Remaining Windows-invalid filename characters are
  sanitized; reserved device names are prefixed. Names supply title/format
  metadata only. Stored paths use generated identifiers, and stored-file reads
  reject traversal and resolved paths outside the imports directory.
- Format checks inspect content: PDF signature, validated OOXML ZIP structure,
  or fully decoded UTF-8/BOM-marked UTF-16 text without binary controls.
  Supplied MIME headers are not trusted; incompatible extensions are rejected.
  Plain text and Markdown have no distinct magic signature, so their extension
  determines subtype only after text validation.
- DOCX checks bound expanded size, member count and compression ratio and reject
  encryption, duplicate members, traversal names, symlinks, VBA payloads and
  XML DTD/entity declarations. No archive is extracted to filesystem paths.
- Only one ingestion coordinator owns a data directory, guarded by an OS file
  lock. It runs one parser child at a time, with a timeout and captured status
  output. Session-token environment variables are removed from parser children;
  parser stderr is suppressed and failures become fixed error codes. PDF page
  and extracted-character limits constrain accepted work.
- Stored bytes are rehashed before parsing. DB publication is atomic. Startup
  recovers interrupted jobs and removes only recognizable, unreferenced
  app-owned files. Startup also reconciles FTS, embeddings and FAISS snapshots.
- `scripts/inspect_chunks.py` prints metadata by default. `--show-text` is an
  explicit user request to display private content, not operational logging.
- Semantic runtime uses only prepared local safetensors, verified file hashes,
  disabled remote code and explicit offline/telemetry-disabled settings. The
  separate `prepare_model.py` setup utility uses network access only when invoked.
- Search/management JSON bodies are limited to 16 KiB. Keyword tokens are quoted
  literals and SQL parameters are bound. Dates require timezones. Source previews
  are bounded and internal file paths are never returned by source/search APIs.
- FAISS manifests verify file checksums before deserialization and validate index
  types, dimensions, IDs and norms. These checks detect accidental drift/corruption;
  they do not authenticate files against same-user tampering. Index paths stay
  within the owned vector directory. Models must match the configured identity.
- Deletion commits a hidden tombstone before removing vectors, snapshots, files
  and DB/FTS rows. File/IO failures remain visible as pending deletion and are
  retried by the worker/startup. An in-flight parser cannot republish the source.
- Delete-all requires an authenticated bounded JSON body with exact confirmation
  `DELETE ALL`. It atomically tombstones existing sources and clears collections
  and application settings, then uses the same recoverable deletion mechanism.
  A generation guard rejects pre-reset uploads that have not yet published;
  genuinely new imports are allowed. User originals, models and separate
  evaluation runs remain outside the deleted library.

## Trust and limitations

M5 adds no endpoint or external service. Context hints pass through the existing
bounded authenticated JSON search API; they are not persisted or logged.
Reranking uses only eligible imported candidates and never bypasses hard filters.
Weights are validated server/evaluation configuration, not per-request overrides.
Tuning grids are bounded, reject ambiguous IDs, use safe prefixed output filenames,
and cannot run against the test split. Reports retain the existing privacy rules;
effective weights and formula identifiers are operational metadata, not secrets.

The M4 evaluation CLI runs under the same local OS account and opens no HTTP
port. It requires explicit local dataset paths, confines declared document
paths to the manifest directory, creates a new isolated output/corpus and never
overwrites the application library. It uses the same validated imports and
offline encoder. Reports exclude content, titles, query text, input paths and
tokens, but retain opaque IDs/hashes and judgments-derived metrics; these can
still be sensitive. Private corpus copies remain on disk for auditing. Default
run and dataset data are Git-ignored. CLI errors use fixed safe codes. Split
validation supports experimental discipline, not access control over test labels.

Anyone with access to the running desktop browser can open ECHO. Local programs
can also construct a loopback request meeting the dashboard startup checks.
Stop ECHO or lock the operating-system session when leaving a shared machine.

The local filesystem is not encrypted by ECHO. The process environment is not
a secret vault. Same-user malware, an administrator or a debugger can read
process memory and local data. Use a private local directory and ordinary OS
account protections. ECHO does not claim encryption at rest or end-to-end
encryption. Local HTTP carries credentials in plaintext over loopback.

Loopback binding is enforced by the supported launcher. An operator who runs
an arbitrary ASGI launcher can change binding settings, though peer/Host/token
validation still applies. Running untrusted local code or changing ECHO's
source/dependencies is outside this boundary. Health indicates database
reachability, not retrieval readiness or an integrity audit of every page.

Parser subprocesses are fault-isolation mechanisms, not an OS security sandbox:
they run under the same OS account and have no hard RSS quota. Keep parsers
updated. DOCX parsing constructs a bounded in-memory XML tree; a PDF page can
allocate memory before text limits are checked. An abruptly killed parent can
leave a parser child alive until that child exits; it cannot publish DB state.
Normal server shutdown terminates its active parser and requeues unfinished work.

Deletion does not promise forensic erasure of SQLite pages/WAL, backups or SSD
blocks. FAISS and its serialization require memory proportional to the index;
there is no measured RSS guarantee or hard quota. Source/index mutations and
search are serialized; indexing can delay those requests. Total request-rate,
disk and memory quotas are not implemented. Do not expose this service through
a proxy or tunnel. Development HMR uses a separately allowed loopback origin;
the production build uses the API origin and its strict CSP.
