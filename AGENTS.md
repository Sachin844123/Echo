# ECHO engineering rules

Implement one user-authorized milestone at a time. M1 through M6 are complete
and tested. Stop at the M6 boundary. Do not begin optional M7 without explicit
authorization.
Update this status after each milestone.
Run its tests, fix failures, update docs/PROGRESS.md,
docs/decisions.md and CHANGELOG.md, then stop.

ECHO searches only explicitly imported content. The primary deliverable is
an honest retrieval evaluation on user-supplied documents and labels. Never
fabricate research data or results. Tiny test fixtures must be labelled.

Use Python 3.11+, pathlib, Pydantic v2, SQLAlchemy 2.x and SQLite. Windows 11
is the primary environment. Keep dependencies minimal and justify additions.
Never log content, tokens, query text, file paths, SQL parameters or raw
exception messages. Never commit secrets or local data. The supported server
must bind to 127.0.0.1 and require a token on every API request.

No frontend before M6. No desktop packaging, extensions, mobile, cloud sync,
accounts, PostgreSQL, local LLMs, orchestration frameworks or vector servers.
OCR and webpage capture require explicit user authorization.

Run tests from the repository root:
`.venv\Scripts\python.exe -m pytest -q`
