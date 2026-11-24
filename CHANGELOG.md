# Changelog

## Unreleased — M7 OCR, image search and retrieval coverage

- Read text in scanned PDF pages and PNG/JPEG images with local Tesseract.
- Search imported images by appearance with local CLIP and by recognized text
  or filename with document search. Add authenticated previews and reprocessing.
- Show optional corpus-based spelling corrections and combine ranks per source
  so a long document cannot occupy every slot in the final candidate lists.
- Add migration `0003_images`, durable visual indexing and isolated migration,
  OCR, visual retrieval and dashboard regression tests.
- Verified with 288 backend tests, 14 browser and proxy tests, focused browser
  reruns and a production build.

## Unreleased — M6 development upload fix

- Detect a rejected browser origin at login and before streaming imports, with
  clear guidance for the exact Vite origin and required backend restart.
- Preserve strict Origin/token validation; redact filenames and raw exceptions
  from Vite proxy transport diagnostics.
- Add backend session-check, browser retry and real Vite proxy regression tests.
  No dependency, migration or optional milestone work added.
- Verification: 44 focused backend tests and 12 browser/proxy tests passed;
  production build, type checking and formatting passed.

## 0.6.0 — 2026-11-19 — M6 local dashboard and API hardening

- Added the local React/TypeScript/Vite/Tailwind dashboard with Search, Library,
  Collections, Sources, Settings, import dialogs and bounded text previews.
- Added all retrieval modes/filters/context hints, collection membership,
  rename, deletion, job status/retry, light/dark themes and keyboard navigation.
- Added same-origin static serving, memory-only browser sessions, restrictive
  CSP/security headers and redacted framework parameter-validation responses.
- Added safe configuration projection, collection browsing/counts and confirmed
  recoverable delete-all with an in-flight upload generation guard.
- Added backend security/lifecycle and real-browser workflow/accessibility tests.
  Fixed dialog focus restoration and asynchronous collection checkbox feedback
  found during browser verification. No backend dependency or migration added.
- No research data/results, OCR, webpage capture or M7 work introduced.
- Verification: 270 backend tests passed; eight real-browser workflows passed,
  including automated accessibility checks. Production build, type checks,
  formatting, dependency audits and whitespace checks passed.

## 0.5.0 — 2026-11-18 — M5 contextual reranking

- Fixed repository-root editor resolution of `app.*` and test-helper imports
  through shared Pyright/Pylance paths and a local virtual-environment default.
- Fixed evaluation memory-phase attribution and preservation of primary errors
  when final memory sampling or failure-artifact storage fails; added four
  regression checks and a safe structured storage-failure event.
- Added `hybrid_contextual` mode with normalized RRF, title/heading coverage,
  exact keyword overlap and explicit source-type/collection context signals.
- Added validated configurable placeholder weights, separate soft context hints,
  deterministic ties and per-result signal explanations, preserving A–C behavior.
- Added evaluation method D and report version 2 with formula/weight provenance.
- Added bounded explicit tuning-only weight sweeps, per-setting JSON/CSV results
  and reusable full configurations; final-test sweeps are rejected before work.
- Added reranking/ablation/API/sweep tests and extended actual offline-model
  integration to method D and the example sweep. No new dependency or migration.
- M6 remains unstarted. Research improvements remain unmeasured without user data.
- Verification: 61 focused checks, four audit regressions and 257 full-regression tests passed, with no
  skips or warnings in the final suite; dependency checks passed.

## 0.4.0 — 2026-11-18 — M4 evaluation

- Added strict labelled manifests with source-level graded relevance, file/hash
  validation, source/date/collection metadata and separate tuning/test queries.
- Added an isolated runner comparing keyword, semantic and hybrid on identical,
  fully indexed data with macro P@5, R@5, MRR@10 and NDCG@10.
- Added measured warm-search median/p95 latency, raw per-query samples, indexing
  wall time and sampled native parent/parser-child RSS through psutil.
- Added configuration/model/dataset/code/environment provenance, private JSON/CSV
  reports, safe failure artifacts and no-overwrite output directories.
- Added dataset/grading/split/measurement documentation and synthetic correctness,
  isolation, failure and actual offline-model integration tests.
- No research study or results are supplied. M5 reranking and later milestones
  remain unstarted; M4 requires user-supplied documents and labels for findings.
- Verification: 33 focused M4 tests and 228 full-regression tests passed; no
  skips or warnings in the final suite. Dependency validation passed.

## 0.3.0 — 2026-11-18 — M3 search engine

- Added migration `0002_retrieval`: FTS5 with synchronization triggers, durable
  ingestion/indexing stages and embedding content fingerprints; preserves M2 data.
- Added offline MiniLM embeddings, bounded WordPiece window pooling, configurable
  batches, normalized FAISS IDMap/FlatIP snapshots and checksummed model manifests.
- Added keyword, semantic and RRF hybrid search with type/date/collection filters,
  source grouping, referenced excerpts and explicit incomplete-index reporting.
- Added source metadata/rename/preview/deletion, minimal collection membership,
  index status, recoverable tombstones and startup cross-store reconciliation.
- Added explicit model provisioning and stopped-server `rebuild-index` commands;
  no model downloads or external AI requests occur in application runtime.
- Added retrieval/recovery/security tests, real offline-model integration and
  search documentation. M4 evaluation and later milestones remain unstarted.
- Final M1–M3 regression: 195 passed, no skips or warnings; dependency validation
  passed. No research relevance or performance results are claimed.

## 0.2.0 — 2026-11-18 — M2 ingestion

- Added authenticated raw-file and manual-note imports, streamed byte limits,
  content-based format validation, SHA-256 deduplication and random storage paths.
- Added PDF, UTF-8/UTF-16 text, Markdown and DOCX extraction using the requested
  PyMuPDF/python-docx parsers, bounded by configured input/output/archive limits.
- Added cleaning, page/heading metadata and overlapping lexical-token chunks
  with exact cleaned-document offsets and incremental database inserts.
- Added durable background jobs, status/list/retry endpoints, attempt and queue
  limits, exclusive instance locking, interrupted-job recovery and orphan cleanup.
- Isolated parsers in one child process at a time with timeout/cancellation and
  safe public errors. Publish documents/chunks/job completion atomically.
- Added scripts/inspect_chunks.py, ingestion documentation and fixture-based
  parser/security/recovery tests. Extended the real-server test through ingestion.
- Final regression: 162 tests passed; dependency validation passed.
- No schema change was needed. M3 search/indexing and later milestones remain
  unstarted; ingestion success does not claim search readiness.

## 0.1.0 — 2026-11-17 — M1 foundation

- Added the Python backend package layout, validated environment configuration
  and a loopback-only FastAPI/Uvicorn launcher.
- Added generated session tokens, strict Host/Origin/peer checks, restrictive
  CORS, protected health API and content-safe structured JSON logging.
- Added eight normalized SQLAlchemy tables, a versioned Alembic migration,
  FK cascades, uniqueness/check constraints, indexes and UTC timestamps.
- Added migration/revision checks, an FTS5 capability probe and bounded SQLite
  connections with WAL and per-connection FK enforcement.
- Added foundation/security tests, including a real local-server test, and
  setup, schema, security and decision documentation.
- Recorded compatible dependency constraints and the resolved environment.
- M2–M6 have not started. No retrieval or evaluation results are claimed.
