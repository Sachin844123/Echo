# ECHO progress

## Current state — 2026-11-19 (Asia/Calcutta)

**M1 through M6 LOCAL API HARDENING + DASHBOARD are complete and tested.**
Stopped at the M6 boundary. Existing ingestion, retrieval and evaluation are
preserved. Optional M7 is unstarted and requires explicit authorization.

## M6 delivered — 2026-11-19

- Local React/TypeScript/Vite/Tailwind dashboard: Search, Library, Collections,
  Sources and Settings; all four retrieval modes, hard filters and soft hints.
- Sequential file and note imports with duplicate/per-file results; paginated
  documents/jobs; collection creation, browsing and membership; rename/delete.
- Bounded text previews, source metadata and Unicode-correct passage highlights;
  plain text rendering prevents imported markup execution. No fake library data.
- Light/dark themes, narrow layouts, skip link, Ctrl/Cmd+K, native dialogs with
  focus return, empty/loading/error states and cancelled stale search requests.
- Public non-sensitive build shell on the API origin; authenticated data access,
  memory-only tab tokens, lock/reload/401 handling, theme-only browser storage.
- CSP/no-framing/no-referrer/permissions headers and redacted FastAPI validation.
  Safe settings projection and collection counts/filtering for the dashboard.
- Confirmed delete-all with durable tombstones, cascading cleanup and rejection
  of pre-reset in-flight uploads. Existing recovery retries unfinished deletion.
- Applied installed frontend-design, UI UX Pro Max and Vercel React guidance.
  Dependencies and design choices are recorded in dashboard-design.md. No new
  backend dependency, schema migration, remote runtime asset or cloud service.

### M6 files

New frontend: package manifest/lock, TypeScript/Vite/Playwright/Prettier configs,
index.html, local favicon, README; src/{App,ImportDialog,LibraryPage,PreviewPanel,
SearchPage,SystemPages,components}.tsx, src/{api,types}.ts, src/main.tsx and
src/styles.css; tests/workspace.spec.ts and tests/serve_backend.py.

New backend: app/api/dashboard.py and tests/test_dashboard.py.
New documentation: docs/dashboard-design.md.
Modified: .gitignore, AGENTS.md, CHANGELOG.md, README.md; backend app version,
api/ingestion.py, api/sources.py, ingestion/errors.py, ingestion/service.py,
main.py, security/middleware.py and tests/test_api.py; docs/PROGRESS.md,
docs/decisions.md, docs/schema.md and docs/security-model.md.

### M6 executed verification

- `.venv\Scripts\python.exe -m pytest backend/tests/test_dashboard.py -q --tb=short`:
  **`13 passed in 16.99s`**. An initial test-client DELETE syntax failure was
  corrected, not ignored.
- `.venv\Scripts\python.exe -m pytest -q --tb=short`:
  **`270 passed in 393.14s (0:06:33)`**, no skips or warnings.
- In frontend, `npm run build`: TypeScript check and production Vite build
  passed. Final assets: JavaScript 269.62 kB (81.69 kB gzip), CSS 29.84 kB
  (6.85 kB gzip). These are build sizes, not latency or memory benchmarks.
- In frontend, `npm test`: **`8 passed (1.5m)`** using installed Microsoft Edge
  against a real temporary backend with labelled TEST DATA. All workflow
  tests reject external browser requests and unhandled browser exceptions.
  Automated axe WCAG A/AA checks passed in the tested states/themes. Playwright
  emitted an inherited NO_COLOR/FORCE_COLOR tooling warning, not a test failure.
- Browser verification found and corrected modal focus return, asynchronous
  checkbox feedback and ambiguous test/field selectors. Final run passed every
  case. Reviewed actual light/dark, 375px and populated preview screenshots;
  screenshot artifacts remain ignored. No user library was altered by tests.
- `npm run format:check`, `npm audit --audit-level=moderate`, Python `pip check`
  and `git diff --check` passed. Audit reported **0 vulnerabilities**; Python
  reported **No broken requirements found**. Local documentation links and
  lock metadata validated; no runtime data, build artifacts or credentials
  appear in the publish inventory.

### M6 run commands

From the repository root, with Python dependencies already installed:

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..\backend
..\.venv\Scripts\python.exe -m app migrate
$env:ECHO_SESSION_TOKEN = (& ..\.venv\Scripts\python.exe -m app token).Trim()
$env:ECHO_SESSION_TOKEN
..\.venv\Scripts\python.exe -m app serve
```

Open http://127.0.0.1:8000/ and enter the displayed token. The token display is
an explicit local setup action; operational logs never contain it. Stop with
Ctrl+C. Full backend tests run from root; browser tests run with `npm test`
from frontend. The frontend README also covers optional local Vite development.

### M6 limits

- Real research documents/labels are still required; UI/test fixtures establish
  correctness, not retrieval quality. Placeholder reranker weights remain untuned.
- Semantic methods require the prepared local model. Browser tests deliberately
  use an absent model to verify failure visibility; backend tests use the actual
  offline MiniLM model. No runtime download or silent semantic fallback exists.
- Browser verification used Chromium-based Microsoft Edge; other engines and
  assistive technologies have not been manually certified. Automated accessibility
  checks and screenshots are evidence for tested states, not universal compliance.
- Previews show extracted text, not original-format document layouts. Processing
  and search retain the existing serialized index lock and can delay each other.
- Tokens are memory-only, so reload requires reconnecting. Settings exposes server
  configuration read-only; theme and library/session actions are interactive.
- Deletion keeps original files, embedding models and separate evaluation runs;
  it does not erase backups/disk blocks. No encryption, total disk/RSS quota,
  cloud sync, accounts, packaging, OCR or webpage capture is claimed.

## Editor import fix — 2026-11-18

- Reproduced the repository-root path mismatch: `app` lives in `backend`,
  while no Pylance/Pyright search paths were configured. Added shared analysis
  paths in `pyproject.toml` and `.vscode/settings.json` selecting `.venv` by
  default. Runtime imports and dependencies are unchanged; M6 is unstarted.
- Validated TOML/JSON and resolved all 142 `app.*`/test-helper import statements
  against the configured paths. The local virtual environment exists.
- `.venv\Scripts\python.exe -m pytest --collect-only -q` returned
  `257 tests collected in 1.67s`.
- `.venv\Scripts\python.exe -m pytest backend/tests/test_search_api.py backend/tests/test_config.py -q --tb=short`
  returned **`30 passed in 5.69s`**. `git diff --check` passed.
- These are configuration/import checks and focused runtime tests; the prior
  257-test full regression below was not repeated for this editor-only change.
  Live editor diagnostics were not inspected. README documents selecting the
  interpreter and reloading if VS Code retained an earlier interpreter choice.

## M4/M5 audit fixes — 2026-11-18

- Fixed memory readings crossing a phase transition: retain the starting phase
  and synchronize missed-child counters.
- Fixed final memory-read errors masking the primary evaluation failure; stop
  the sampler and preserve the original error with a safe secondary note.
- Fixed failure-artifact storage errors masking the original safe failure code;
  emit a redacted structured event when the artifact cannot be written.
- Added four regression cases. Before the fixes, the focused command returned
  `4 failed, 33 deselected in 3.02s`; afterward it returned
  `4 passed, 33 deselected in 0.68s`:
  `.venv\Scripts\python.exe -m pytest backend/tests/test_evaluation.py -q --tb=short -k "memory_sample_keeps or final_memory_read or failure_artifact_write"`.
- Dependency validation returned `No broken requirements found.` Local Markdown
  links resolve, and the publish inventory contains only source, tests,
  configuration and documentation. No M6 work was started.
- Final full regression: `.venv\Scripts\python.exe -m pytest -q --tb=short`
  returned **`257 passed in 401.05s (0:06:41)`**, with no skips or warnings.
  `git diff --check` also passed. Publication uses one changed file per commit
  on the GitHub default branch, `master`; private runtime data stays ignored.

## M5 delivered

- Explicit `hybrid_contextual` search mode (evaluation method D), reranking the
  same hybrid candidate union before source grouping; A–C and hard filters remain.
- Normalized theoretical-max RRF, title/heading coverage, exact query-token
  overlap, explicit source-type match and collection membership signals.
- Shared validated immutable weights in server/evaluation configuration; finite,
  nonnegative placeholders with at least one positive value. RRF-only ablation
  preserves C ordering. Stable ties use original RRF then chunk ID.
- Optional soft context hints separate from hard filters; no recency/history or
  wording inference, no bypass of filters and no additional captured content.
- Per-result normalized signal explanations, original RRF and effective weights/
  formula version. Reports use version 2 and compare four methods.
- Explicit bounded weight grids, tuning-only CLI/internal guards, one shared
  corpus, seeded setting order, per-setting metrics/timings and reusable full
  configurations with safe Windows filenames. No automatic winner selection.
- Documentation of formula, context collection, ablation, tuning/test discipline
  and limits; unit/API tests and actual offline-model sweep integration.

### M5 files

New: `backend/app/retrieval/reranking.py`, `backend/tests/test_reranking.py`,
`evaluation/sweep.py`, `evaluation/weights.example.json`, `docs/reranking.md`.
Updated: backend configuration, search request schema/search engine/version,
API/retrieval/search/embedding/evaluation regression tests, evaluation dataset/
runner/example config/README, root README, AGENTS, CHANGELOG, and progress,
decisions, search, schema and security documentation. Existing M4 work is
preserved. No new dependencies, migrations, frontend or M6 work.

### M5 verification

Executed from `C:\Projects\Echo`:

- `.venv\Scripts\python.exe -m pytest backend/tests/test_reranking.py backend/tests/test_retrieval.py backend/tests/test_config.py -q --tb=short`
  returned **`61 passed in 20.29s`**.
- `python -m pip check`: `No broken requirements found.`
- Full M1–M5 regression: `.venv\Scripts\python.exe -m pytest -q --tb=short`
  returned **`253 passed in 368.01s (0:06:08)`**, with no skips or warnings.
- Shared weight defaults/example config, the example grid and local documentation
  links validated. Runner help exposes the tuning-only sweep option; Git diff
  whitespace checks passed. No failing test was ignored.

Checks cover hand-calculated normalized scoring, Unicode/case/token matching,
independent signal effects, RRF-only/tie equivalence, unchanged A–C behavior,
candidate-count/hard-filter preservation, grouping and signal explanations,
authentication/redacted validation errors, finite/nonzero weights, explicit
complete grids, case-insensitive ID collisions, unknown context collections,
test-split rejection before file access, tuning-only outputs, frozen config
hashes and settings restoration on failure. The real MiniLM CLI test now runs
method D and all three example sweep settings without downloading anything.

### M5 run commands

From the repository root, after supplying real documents and labels:

```powershell
.\.venv\Scripts\python.exe evaluation\run_eval.py --dataset .local\datasets\my-study\dataset.json --config evaluation\config.example.json --split tuning --weight-sweep evaluation\weights.example.json --output .local\evaluation\my-study-sweep-01
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Output directories must be new. Choose a saved `configs/weights-<id>.json` using
tuning evidence, then run `--split test --config <selected-file>` without a
sweep. API mode is `hybrid_contextual`; optional `context.source_types` and
`context.collection_id` are soft hints. Set `ECHO_RERANK_WEIGHTS` JSON before
starting the server to override placeholders. App launch is unchanged; exact
PowerShell instructions remain in README.

### M5 decisions and limitations

- All signals are normalized before weighted combination. Title/heading uses
  maximum query coverage, not a sum. Repeated terms do not inflate overlap.
  No stemming, fuzzy matching, stopword removal or recency boost is included.
- Missing/unmatched hints have zero signals; A–C ignore hints. D can use extra
  remembered context, which must be gathered independently of relevance labels.
  Scores are ranking values, not confidence probabilities.
- Default/example weights are untuned placeholders, not measured improvements.
  Real documents/labels are still required; no research findings are fabricated.
- Sweeps report every setting and choose none. Test-split guards cannot prevent
  human inspection of labels, paraphrase leakage or repeated manual test tuning.
- Sweeps reuse indexing but perform full searches per setting. Work grows with
  settings/repeats/query count. Whole-run memory includes sweeps; method-phase
  peaks are shared-process residency, not isolated per-setting costs.
- Windows/Python 3.12 remains the verified environment. No new hardware-memory
  or latency guarantees, encryption claims, packaging or M6 hardening are added.

## M4 delivered

- Strict dataset/config contracts: explicit authorized local files, stable IDs,
  grades 0–3, timezone-aware capture/filter metadata, collections and nonempty
  tuning/test splits. Reject duplicate bytes, bad paths, unknown references,
  filtered-out positive labels and duplicate normalized queries.
- Fresh isolated corpus per run using the existing ingestion/search engine.
  Require complete, matching DB/FTS/embedding/vector ID sets for all documents
  before comparing A=keyword, B=semantic and C=hybrid on identical selected queries.
- Source-level macro Precision@5, Recall@5, MRR truncated at ten results and
  graded NDCG@10, with explicit definitions and unjudged-as-nonrelevant semantics.
- Real warm in-process latency samples, median/nearest-rank p95, indexing wall
  time and bounded sampled native parent/parser-child RSS aggregation.
- Separate tuning/test runs, explicit configuration for final-test CLI runs,
  seeded query order, rotated method order, warmups and fixed-result repeats.
- Private JSON/CSV reports with dataset/split/config/model/code/environment
  fingerprints; no query text, document contents, excerpts, titles, paths or tokens.
- Safe failure artifacts and no output overwrites, silent document exclusions,
  method fallback, fabricated success or automatic publishing of research data.
- Dataset/grading/split/measurement documentation and tiny TEST DATA tests,
  including a fresh-process runner using the actual offline MiniLM model.

### M4 files

New: `evaluation/__init__.py`, `dataset.py`, `metrics.py`, `resources.py`,
`run_eval.py`, `config.example.json`, `evaluation/datasets/README.md`, and
`backend/tests/test_evaluation.py`.

Updated: evaluation/README.md, root README, .gitignore, AGENTS, CHANGELOG,
pyproject test import paths, backend requirements-dev/requirements-lock,
application version and health test, docs/decisions, schema, security model
and this progress record. No application schema, ingestion or retrieval
algorithms changed. No M5 reranker/sweep or frontend was created.

### M4 verification

Executed from `C:\Projects\Echo`:

- First focused suite: `1 failed, 28 passed in 116.02s (0:01:56)`. The sole
  failure compared a measured floating-point median to an exact decimal;
  `10.499999999999998` correctly represents the calculation. Changed the test
  to numeric tolerance, preserving full measured precision in the implementation.
- Expanded focused suite: `.venv\Scripts\python.exe -m pytest backend/tests/test_evaluation.py -q --tb=short`
  returned **`33 passed in 87.40s (0:01:27)`**.
- `python -m pip check`: `No broken requirements found.`
- Runner `--help` and `git diff --check` succeeded.
- Full M1–M4 regression: `.venv\Scripts\python.exe -m pytest -q --tb=short`
  returned **`228 passed in 179.01s (0:02:59)`**, with no skips or warnings.
- The example configuration matches validated defaults; all local documentation
  links resolve. The normal application DB remains at `0002_retrieval` with
  zero sources; evaluation did not import fixtures into the user's library.

Tests verify known graded-ranking arithmetic and cutoffs, small-sample p95,
invalid grades/contracts, JSON duplicate keys, path restrictions, byte duplicates,
normalized-query leakage, held-out-only scoring, fixed config fingerprints,
failure/no-overwrite behavior, aborted comparisons after corrupt document
extraction, unstable rankings, actual child-process RSS and real offline-model
CLI integration. Exported artifacts exclude the fixture's private markers and
held-out query IDs during a tuning run. No failing test was ignored.

### M4 run commands

Install updated development/evaluation dependencies and use the already prepared
model. From the repository root, after supplying real documents and labels:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt -c backend\requirements-lock.txt
.\.venv\Scripts\python.exe evaluation\run_eval.py --dataset .local\datasets\my-study\dataset.json --config evaluation\config.example.json --split tuning --output .local\evaluation\my-study-tuning-01
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Replace input/output placeholders and use a new output directory every time.
Final `--split test` requires an explicit configuration selected on tuning data.
App launch remains `python -m app migrate`, generate `ECHO_SESSION_TOKEN`, then
`python -m app serve` from backend; see README for full PowerShell commands.

### M4 decisions and limitations

- psutil is an evaluation/development dependency because native Torch/FAISS and
  parser-child memory are not covered by tracemalloc. The API does not import it.
- Latencies are warm in-process calls, excluding HTTP/serialization. Sampled
  memory peaks are lower bounds; shared pages may be double-counted and method
  phases share a resident model/index. Indexing time is one shared-corpus cost,
  includes first model loading and polling, and excludes preflight/setup.
- Metrics use source labels and ten returned sources; MRR is explicitly @10.
  Unjudged means nonrelevant. Incomplete labels bias scores; no-positive queries
  are rejected. Candidate grouping can return fewer than ten sources.
- Normalized-text checks cannot detect paraphrase leakage or prevent human
  inspection/tuning on held-out labels. Human study design remains essential.
- Full manifests are bounded at 32 MiB; FAISS/corpus/result storage still scales
  with study size. There is no i3/8-GB performance or RSS guarantee. Processing
  deadlines are soft around bounded embedding batches; no hard native quota.
- Reports retain opaque IDs/hashes and private corpus copies. They are not
  encrypted and are not automatically deleted or committed. No real study has
  been run: user-supplied documents and judgments are still required. Fixture
  measurements/scores are verification only and are not research evidence.

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
