# ECHO local dashboard

React, TypeScript, Vite and Tailwind. The production build is served by the
existing FastAPI process at `http://127.0.0.1:8000/`. No cloud service, remote
assets, account system or runtime network dependency is involved.

## Build and run on Windows

After completing the backend setup, double-click `Run-ECHO.bat` from the
repository root. It builds the dashboard if needed, migrates the database,
starts the local server and opens your browser to the workspace. Stop it with
Ctrl+C in the launcher window. Use `Run-ECHO.bat --build` after frontend edits
to rebuild an existing dashboard. Building requires Node 22.12+.

The equivalent manual commands are:

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..\backend
..\.venv\Scripts\python.exe -m app launch
```

The workspace opens directly. The dashboard establishes its local session
automatically and keeps it in memory. API calls and previews still authenticate.

Build again after frontend edits. Backend-only installations still support the
API; the root URL returns a safe setup message until the dashboard is built.
Prepare the offline embedding model using the root README for semantic modes.
Keywords remain available when the local model is absent.

## Screens and behavior

- **Search:** four text retrieval modes plus visual search. Type, collection,
  and date filters start collapsed on narrow displays. Context mode has
  separate optional ranking hints. Ctrl/Cmd+K focuses search.
- **Recent searches:** opt in from Search or Settings. The browser keeps up
  to 12 completed queries, their modes, and timestamps. Selecting an entry
  fills in its query and mode. The search runs when you submit it. You can
  remove entries individually, clear history, or turn it off.
- **Library:** paginated sources, type/collection filters, rename and deletion.
  Preview shows bounded extracted text, the matched passage, source references
  and collection membership. It renders text, never imported HTML or Markdown.
- **Collections:** create, browse and delete; deleting a collection keeps its
  documents. Add/remove documents through their preview.
- **Activity:** extraction and indexing jobs with timestamps, explicit failures and eligible
  retries. Counts come from the local API, never fabricated sample data.
- **Settings:** theme, opt-in browser history, read-only server configuration,
  and confirmed delete-all. Themes persist in `echo.theme.v1`. Recent searches
  use `echo.recent-searches.v1` while enabled. Tokens and documents stay in
  tab memory.

Imports accept PDF, TXT, Markdown, DOCX, PNG, JPEG and manual notes. Files upload sequentially
with per-file results and duplicates reported. Each file has the server's size
limit; the UI accepts up to 50 files per selection. Processing happens in the
existing backend worker. Date inputs use the browser's local timezone and are
sent as UTC-aware timestamps.
Use **Images** for visual descriptions and **Keywords** or **Hybrid** with the
Image filter for recognized text and filenames. Open an existing scan and choose
**Reprocess** after setting up OCR. See [OCR and image search](../docs/images.md).

## Development server (optional)

The supported production flow above needs only one local server. For HMR, start
the backend on port 8000 with both exact origins explicitly allowed:

```powershell
Set-Location C:\Projects\Echo\backend
$env:ECHO_ALLOWED_ORIGINS = '["http://127.0.0.1:8000","http://127.0.0.1:5173"]'
..\.venv\Scripts\python.exe -m app serve
```

Then, in a separate terminal under `frontend`, run `npm run dev` and open
`http://127.0.0.1:5173/`. The loopback-only, strict-port Vite server proxies API
requests and dashboard startup to port 8000, preserving bearer authentication
and Origin validation.
Do not expose either server on a network interface. The strict production CSP
is supplied by FastAPI; development HMR is not the production deployment.

### Upload fails with a Vite connection reset or an Origin error

If the backend was started with its default settings, it only permits the
port-8000 dashboard origin. A proxied browser GET can succeed without an Origin
header while an upload POST includes the port-5173 origin and is rejected before
its body is read. Vite can then report `write ECONNRESET` during the upload.

Stop the backend with Ctrl+C in its terminal, set `ECHO_ALLOWED_ORIGINS` using
the commands above, and start it again in that same terminal. Environment changes
do not update a running server. Open **http://127.0.0.1:5173/** exactly;
`localhost` is a different origin. Alternatively, use the built dashboard at
**http://127.0.0.1:8000/** with the default allowlist. After updating this code,
restart the backend and Vite and reload the dashboard to pick up the session check.

Startup checks the exact browser origin before opening the workspace. Import
also makes an authenticated, body-free `POST /api/v1/session/check` before
transferring files.
This check does not replace validation on each upload or other API request.
Vite transport errors remain visible with fixed diagnostics that omit request
URLs, filenames and raw exception stacks. Other failures, including an unavailable
backend or interrupted connection, still require their own diagnosis.

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
The text embedding model is deliberately absent in browser tests to exercise
semantic failure and real keyword retrieval. Before running the image workflow,
prepare the English OCR data and CLIP assets in their default locations using
the [image setup guide](../docs/images.md). Tests cover import, search, collection
and deletion flows, image OCR and visual search, XSS-safe
previews, token privacy, stale requests, keyboard focus, theme changes, narrow
layouts and automated axe accessibility checks. Screenshots and reports are
Git-ignored. Automated checks do not replace a full assistive-technology audit.
Proxy tests start additional ephemeral loopback listeners, check authentication
and exact allowed/denied origins, perform a real tiny TEST DATA upload, and
simulate an upstream reset to verify redacted diagnostics. The test backend
explicitly permits the separate test origin on port 8238; production defaults
remain unchanged.

## Implementation and limits

Components are split by workflow, with a shared API client and small UI primitives.
Independent metadata requests run concurrently; list requests are bounded and
cancelled when superseded. Index status polls every five seconds while visible.
Text previews fetch 4,000 Unicode code points at a time; highlights respect
Python code-point offsets, including non-BMP characters.

Image search requires schema revision `0003_images` and Pillow in the backend.
Frontend packages are pinned in `package-lock.json`. Development dependencies
are justified in [the design record](../docs/dashboard-design.md). Rendering
uses system fonts and local SVGs; no icon/font CDN, analytics or service worker.

Delete-all immediately hides existing sources, clears collections/settings and
uses durable tombstones to retry removal of vectors, files and database/FTS rows.
An upload already in flight is rejected if it tries to publish after the reset.
New imports remain possible. Originals, model files and separate evaluation runs
are kept. Deletion does not promise forensic erasure or removal of backups.
There are no total disk/RSS quotas or encryption-at-rest claims.
