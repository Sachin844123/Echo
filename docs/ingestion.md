# Ingestion — M2

ECHO imports only bytes explicitly supplied by the caller. It does not scan
folders, retrieve URLs, follow embedded links, run macros or perform OCR.

## Capture and API contract

`POST /api/v1/imports/files?filename=<plain-name>` accepts the file as the raw
HTTP body. This permits bounded streaming without adding multipart-parser
dependencies. Accepted extensions are `.pdf`, `.txt`, `.md`, `.markdown`, and
`.docx`; content must match. Declared MIME is ignored in favor of inspection.
There is no API that opens an arbitrary client filesystem path.

`POST /api/v1/imports/notes` accepts JSON `{ "title": "...", "text": "..." }`.
Titles are limited to 200 characters, text to 100,000; empty/blank values and
unknown fields are rejected. The JSON body is limited to 1,000,000 bytes. Note
text is stored as UTF-8 and participates in the same duplicate check as files.

Each accepted new import returns HTTP 202 with source/job IDs. An identical
SHA-256 of captured bytes returns HTTP 200 with existing IDs and `duplicate:
true`; no second file, source, document or job is created. Titles and extensions
do not enter the hash. Therefore a note and TXT file with identical UTF-8 bytes
deduplicate, while differently encoded or differently formatted equivalent text
does not. The first capture's metadata wins. Duplicating a failed import does
not implicitly retry it; use its retry endpoint.

Validation/format errors return 400/415/422, excessive bytes return 413, a full
queue returns 429, and storage unavailability returns 503 where detected.
Responses use fixed `error.code` and `error.message` values; parser contents and
tracebacks are not returned. All routes require the existing session token.

`GET /api/v1/indexing-jobs/{id}` returns job/source IDs, source title/type,
status, attempts, sanitized error, timestamps, document ID, chunk count,
`ready_for_indexing`, and `retryable`. The list endpoint supports limit 1–100
and a nonnegative offset and also reports coordinator thread liveness. It does
not return document bodies. Source management/preview endpoints await M3.

## Formats and cleaning

| Input | Extraction | Preserved metadata / limitations |
| --- | --- | --- |
| PDF | PyMuPDF page text, sorted reading order | One-based page numbers; no OCR, password handling, reliable multi-column layout reconstruction or inferred headings |
| TXT | Incremental text decoding | UTF-8 (optional BOM) or BOM-marked UTF-16; legacy encodings/UTF-32 rejected |
| Markdown | Same text reader; source markup retained | ATX heading metadata outside fenced code; no rendered HTML, external fetches or full Markdown parser |
| DOCX | python-docx body paragraphs and tables in document order, including nested tables | Heading styles; page numbers unknown; headers, footers, footnotes, tracked changes, text boxes and image text are not comprehensively extracted |
| Note | UTF-8 text | Caller title, capture time; unknown language remains NULL |

Cleaning normalizes Unicode to NFC and line endings to LF, removes disallowed
control characters, collapses horizontal whitespace and excess blank lines,
and trims boundaries. It does not summarize, invent language labels or
rewrite the text. Paragraph/segment boundaries join with two newlines; offsets
refer to that cleaned document, not original PDF/Word byte offsets.

Documents with no extractable text fail explicitly. Image-only PDFs never
silently appear as successfully indexed documents. Empty pages in a mixed PDF
produce no text chunks; extracted pages retain their original page numbers.

## Chunking and limits

Defaults are 350 lexical tokens with 60 tokens of overlap. Tokens are Unicode
word runs or punctuation, with long runs split at 32 characters to bound
pathological words. This is a deterministic, model-free M2 approximation, not
MiniLM WordPiece tokenization. M3 must account for the embedding model's input
limit; the research defaults need benchmarking and tuning.

Chunks cross streaming-record boundaries with overlap but never cross a PDF
page or heading change. Each chunk stores its exact half-open character range
in cleaned text. The final window is emitted once. Token spans are generated
incrementally with a bounded window; DB inserts use batches of 100.

Defaults: files 20 MiB, PDF 2,000 pages, cleaned text 5,000,000 characters,
DOCX expanded members 64 MiB, 2,048 archive entries, maximum compression ratio
1,000:1, and parser time 120 seconds. The configurable limits appear in README.
Raw extracted characters also have a 4× cleaned-character ceiling, preventing
unbounded whitespace-only output. Text is read in bounded blocks and PDFs one
page at a time. DOCX necessarily builds a bounded XML tree. The normalized
schema's one extracted_text column requires one bounded final-text allocation;
this is not a claim of constant-memory ingestion or a measured RSS bound.

## Job and crash lifecycle

1. Stream and hash bytes into an app-owned staging file, then flush/fsync it.
2. Validate content off the event loop. Under a mutation lock, check duplicates
   and queue capacity, atomically rename the file, and commit source + pending
   job together. If commit fails, remove the adopted file. A crash in the gap
   can leave only an unreferenced file, which startup removes.
3. The coordinator claims the oldest pending job, increments attempts and marks
   it running. Extraction uses a separate short-lived Python process. It
   rechecks the captured hash and writes cleaned records to an app-owned spool.
4. Publish document + chunks + succeeded status in one SQLite transaction.
   Failures roll back all partial chunks and persist a safe failure state. No
   search index is created, so indexed_at stays NULL and source processing
   status returns to pending. The API's ready_for_indexing means M2 succeeded.
5. Explicit retries transition failed → pending if attempts remain (default
   three total). Successful/running/pending jobs cannot be retried. The input
   file is retained to permit retry; there is no fabricated successful result.

On startup, an OS lock ensures no second coordinator owns the same directory.
Running jobs become pending unless their attempt limit is exhausted; attempts
are retained. Already pending jobs are discovered from SQLite, not an ephemeral
in-memory queue. App-owned staging files and unreferenced import files are
cleaned before requests begin. Unrecognized filenames are left alone.

Normal shutdown terminates an active parser, stops the coordinator and leaves
unfinished work pending when attempts remain. Exhausted interruptions become
failed. Native-parser crashes and timeouts become visible failures. If SQLite
itself cannot record a failure (for example disk full), the error is logged
without private content and a running job may need recovery on the next start.
This is ingestion recovery only; FTS5/FAISS reconciliation arrives in M3.

## Inspection

`scripts/inspect_chunks.py` reads the configured database and prints up to 20
chunk metadata records by default (maximum 100). `--source-id` filters records;
`--show-text` deliberately prints private text and heading metadata to the
terminal. Do not redirect that output into routine logs. This script does not
start jobs, import data or build a search index.
