# ECHO local dashboard

React, TypeScript, Vite and Tailwind. The production build is served by the
existing FastAPI process at `http://127.0.0.1:8000/`. No cloud service, remote
assets, account system or runtime network dependency is involved.

## Build and run (PowerShell)

Node 22.12+ is required; this workspace uses Node 24.11.1. From the repository root:

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

Open `http://127.0.0.1:8000/` and paste the displayed session token. Printing it
here is an explicit local setup action, never application logging. Close or
reload the page to clear its session, or use **Lock workspace**. Keep the same
server token until that process stops. API responses and previews remain
authenticated; only the empty shell and compiled assets are public.

Build again after frontend edits. Backend-only installations still support the
API; the root URL returns a safe setup message until the dashboard is built.
Prepare the offline embedding model using the root README for semantic modes.
Keywords remain available when the local model is absent.

## Screens and behavior

- **Search:** all four retrieval modes; type, collection and inclusive local-day
  date filters. Context mode adds separate optional soft hints. Queries stay in
  memory. Ctrl/Cmd+K focuses search; changes cancel stale requests.
- **Library:** paginated sources, type/collection filters, rename and deletion.
  Preview shows bounded extracted text, the matched passage, source references
  and collection membership. It renders text, never imported HTML or Markdown.
- **Collections:** create, browse and delete; deleting a collection keeps its
  documents. Add/remove documents through their preview.
- **Sources:** extraction/indexing activity, explicit failures and eligible
  retries. Counts come from the local API, never fabricated sample data.
- **Settings:** theme, session lock, read-only server configuration and confirmed
  delete-all. Search history remains off. Only `echo.theme.v1` persists in browser
  storage; tokens, queries, titles and document content do not.

Imports accept PDF, TXT, Markdown, DOCX and manual notes. Files upload sequentially
with per-file results and duplicates reported. Each file has the server's size
limit; the UI accepts up to 50 files per selection. Processing happens in the
existing backend worker. Date inputs use the browser's local timezone and are
sent as UTC-aware timestamps.

## Development server (optional)

The supported production flow above needs only one local server. For HMR, start
the backend on port 8000 with both exact origins explicitly allowed:

```powershell
$env:ECHO_ALLOWED_ORIGINS = '["http://127.0.0.1:8000","http://127.0.0.1:5173"]'
# Start ECHO as above in this shell.
```

Then, in a separate terminal under `frontend`, run `npm run dev` and open
`http://127.0.0.1:5173/`. The loopback-only, strict-port Vite server proxies API
requests to port 8000, preserving bearer authentication and Origin validation.
Do not expose either server on a network interface. The strict production CSP
is supplied by FastAPI; development HMR is not the production deployment.

## Verification

```powershell
# In frontend
npm ci
npm run build
npm test

# In the repository root
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Playwright defaults to the installed Microsoft Edge browser on Windows.
For another supported browser, set `ECHO_TEST_BROWSER` to a Playwright channel.
For bundled Chromium, run `npx playwright install chromium` and set the channel
to `chromium`. This is a setup-only download.

Browser tests start a separate real ECHO server on `127.0.0.1:8237`, with a new
temporary library and random token. They refuse to reuse an existing server.
All documents are tiny labelled TEST DATA; no user library is read or cleared.
The test model is deliberately absent to verify visible semantic failure and
real keyword retrieval. Actual offline-model behavior remains covered by the
backend suite. Tests cover real import/search/collection/delete flows, XSS-safe
previews, token privacy, stale requests, keyboard focus, theme changes, narrow
layouts and automated axe accessibility checks. Screenshots and reports are
Git-ignored. Automated checks do not replace a full assistive-technology audit.

## Implementation and limits

Components are split by workflow, with a shared API client and small UI primitives.
Independent metadata requests run concurrently; list requests are bounded and
cancelled when superseded. Index status polls every five seconds while visible.
Text previews fetch 4,000 Unicode code points at a time; highlights respect
Python code-point offsets, including non-BMP characters.

No new backend dependency or schema migration is needed. Requested frontend
packages are pinned in `package-lock.json`. Additional development dependencies
are justified in [the design record](../docs/dashboard-design.md). Rendering
uses system fonts and local SVGs; no icon/font CDN, analytics or service worker.

Delete-all immediately hides existing sources, clears collections/settings and
uses durable tombstones to retry removal of vectors, files and database/FTS rows.
An upload already in flight is rejected if it tries to publish after the reset.
New imports remain possible. Originals, model files and separate evaluation runs
are kept. Deletion does not promise forensic erasure or removal of backups.
There are no total disk/RSS quotas or encryption-at-rest claims.
