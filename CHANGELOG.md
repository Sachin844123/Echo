# Changelog

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
