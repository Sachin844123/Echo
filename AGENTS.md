# ECHO engineering rules

Implement one user-authorized milestone at a time. M1 through M6 and the
authorized M7 scope (OCR, imported image search and retrieval coverage) are
complete and tested. The authorized local storage indexing milestone and the
dashboard UI refinement are complete and tested. React Bits is the separate
requested dashboard update.
Source checkout setup is complete and verified end to end on Windows.
Webpage capture and packaging remain unstarted.
Update this status after each milestone.
Run its tests, fix failures, update docs/PROGRESS.md,
docs/decisions.md and CHANGELOG.md, then stop.

ECHO searches explicitly imported content and eligible files inside scopes the
user explicitly approves. The primary deliverable is
an honest retrieval evaluation on user-supplied documents and labels. Never
fabricate research data or results. Tiny test fixtures must be labelled.

Use Python 3.11+, pathlib, Pydantic v2, SQLAlchemy 2.x and SQLite. Windows 11
is the primary environment. Keep dependencies minimal and justify additions.
Never log content, tokens, query text, file paths, SQL parameters or raw
exception messages. Never commit secrets or local data. The supported server
must bind to 127.0.0.1 and authenticate data API requests. The dashboard opens
directly using a guarded same-origin startup route and a memory-only credential.

No frontend before M6. No desktop packaging, extensions, mobile, cloud sync,
accounts, PostgreSQL, local LLMs, orchestration frameworks or vector servers.
OCR and webpage capture require explicit user authorization.

Run tests from the repository root:
`.venv\Scripts\python.exe -m pytest -q`
