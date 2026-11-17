# Schema — revision 0001_foundation

All required values are NOT NULL unless marked nullable below. Integer entity
IDs use SQLite AUTOINCREMENT so deleted IDs cannot be reassigned. This matters
when future external vector state is stale. All foreign keys use ON DELETE
CASCADE and have a leading index (including unique/primary indexes).

| Table | Columns and purpose |
| --- | --- |
| sources | id; source_type; title; original_url (nullable); file_path (nullable); mime_type; unique content_hash; captured_at; indexed_at (nullable); processing_status; is_deleted; created_at; updated_at |
| documents | id; unique source_id FK; extracted_text; language (nullable); extraction_method; extraction_status; content_length; created_at |
| chunks | id; document_id FK; chunk_index; chunk_text; token_count; page_number (nullable); heading (nullable); start_offset; end_offset; created_at |
| embedding_records | id; unique chunk_id FK; model_name; model_version; unique vector_index_id; dimension; created_at |
| collections | id; unique name; description (nullable); created_at; updated_at |
| collection_items | composite PK (collection_id FK, source_id FK); created_at |
| indexing_jobs | id; source_id FK; status; attempts; error (nullable); created_at; updated_at |
| app_settings | key PK; value (text); created_at; updated_at |

`alembic_version` is migration metadata, not application data. Settings values
are reserved for validated application settings in later milestones; M1 reads
operational configuration from the environment and stores no secrets here.

## Constraints and indexes

- Source types: `pdf`, `txt`, `markdown`, `docx`, `note`. URL metadata does not
  implement webpage capture. Titles cannot be blank. Content hashes are unique
  lowercase 64-character SHA-256 hex values, calculated over the captured bytes.
  File paths are app-owned relative paths (`imports/<random-id>.<extension>`).
- Source processing status: `pending`, `processing`, `indexed`, `failed`.
  `is_deleted` is restricted to 0 or 1; it is reserved state, not evidence of
  physical deletion. Source indexes cover captured time, type + captured time,
  processing status and deletion flag.
- Document extraction status: `pending`, `complete`, `failed`; nonnegative
  content_length, measured in Unicode code points after extraction. Language is
  nullable when unknown. Text may be empty for pending/failed extraction.
- Chunks: unique `(document_id, chunk_index)`, zero-based nonnegative index,
  nonblank text, positive token_count, positive one-based page number when
  known. Offsets are zero-based, half-open Unicode code-point offsets into the
  document text; `0 <= start_offset < end_offset`. M2 uses lexical words and
  punctuation (long runs split every 32 characters); model tokenization is not
  yet involved. Exact chunk slices and overlap are covered by tests.
- Embeddings: positive dimension; nonblank model identity and version;
  `vector_index_id = chunk_id`. Metadata is present; vectors are not yet built.
- Collection names are nonblank and case-sensitive unique. Membership is
  unique by its composite key. Source-side lookups have a separate index.
- Job status: `pending`, `running`, `succeeded`, `failed`; attempts >= 0, initially
  0. Indexes cover source and `(status, created_at)`. A source may have multiple
  job records. M2 uses one durable job per imported source. Each claim increments
  attempts; the default maximum is three. Errors contain fixed public codes,
  not copied parser exceptions or content.

M2 needs no schema migration: the existing schema supports capture, extraction,
chunks and jobs. A successful ingestion atomically publishes a complete document,
all its chunks and a `succeeded` job. `sources.processing_status` returns to
`pending` because search indexing has not happened; `indexed_at` remains NULL.
Use job status / `ready_for_indexing` for M2 completion, not `processing_status`
alone. M3 must distinguish ingestion from retrieval-index work when extending
the jobs lifecycle. Extraction failures persist an empty failed document and
no chunks. Interrupted jobs exhausted during startup recovery may have no
document because extraction never completed.

## Timestamps, deletion and synchronization

Timestamps default to SQLite CURRENT_TIMESTAMP (UTC). Python model reads use
aware UTC datetimes; timezone-aware writes normalize to UTC and naive writes
are rejected. SQL values are UTC without an embedded offset. `updated_at` is
maintained by the ORM and by database triggers on sources, collections,
indexing_jobs and app_settings when the field was not explicitly changed.
Raw SQL callers are responsible for supplying UTC if overriding timestamps.
Timestamps are not a monotonic ordering or concurrency token.

Deleting a source cascades through its document, chunks, embedding metadata,
collection memberships and jobs. Deleting a collection removes only its
memberships; source content remains. These are database semantics only in M1/M2.
There is no file/vector deletion API yet, and logical database deletion does
not guarantee forensic erasure of disk pages, WAL, backups or SSD blocks.

FTS5 table, title/heading/chunk synchronization triggers, FAISS persistence and
startup reconciliation will be introduced together in M3. The M1 startup
FTS5 probe creates no persistent search table.
