# Local security model — M1 and M2

ECHO is a single-user local process. The primary boundaries are the HTTP server,
the local session token and the user's filesystem permissions. It is not a
multi-user service and has no account system.

## Implemented

- The supported `python -m app serve` launcher binds to 127.0.0.1 only.
  Configuration rejects non-loopback bind addresses. One worker, no reload,
  no proxy trust, no WebSockets, no public docs/OpenAPI route.
- Every HTTP API request requires a bearer token, including health, errors
  reached by unknown routes and ordinary OPTIONS requests. No query-string or
  cookie authentication. Duplicate Authorization headers fail closed.
- Token generation uses 32 random bytes. Secrets are passed via the process
  environment, never stored in SQLite, a token file or application logs. Use a
  fresh generated token per session. A token lasts until server shutdown;
  restarting with a new token revokes the previous session.
- The peer must be 127.0.0.1. Exact Host validation permits only 127.0.0.1 or
  localhost with the configured port, mitigating browser DNS rebinding.
  Duplicate Host/Origin headers are rejected. Proxy headers cannot change the
  peer address through the supported launcher.
- Browser Origin must exactly match an explicit local allowlist. Wildcards,
  null origins, userinfo, nonlocal hosts, non-HTTP schemes, paths, queries and
  fragments are rejected. Native clients may omit Origin but still need the
  token. Origin and CORS are additional browser boundaries, not authentication.
- CORS allows GET/POST and Authorization/Content-Type, no credential cookies. A
  validated browser preflight may be unauthenticated because browsers do not
  send bearer credentials on preflight. It invokes no route and exposes no
  application data. Requests that follow it must authenticate.
- Responses have no-store, nosniff and generated request IDs. Database health
  errors return 503 and unexpected failures return generic 500 responses.
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
  app-owned files. These ingestion repairs are separate from M3 FTS/FAISS repair.
- `scripts/inspect_chunks.py` prints metadata by default. `--show-text` is an
  explicit user request to display private content, not operational logging.

## Trust and limitations

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

Cross-store deletion, FTS5/vector drift recovery and index reconciliation belong
to M3. Broader request-rate/disk quotas, dashboard interactions and delete-all
belong to M6. Those protections are not represented as implemented here. Do not
expose this service through a proxy or tunnel.
