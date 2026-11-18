# Schema — revision 0002_retrieval

M4 and M5 change no application tables or migrations. Evaluation creates a separate
database at each new run's `corpus/echo.sqlite3` using this same schema. Its
versioned dataset/report JSON contracts are documented in the evaluation guide.
M5 context hints and weights are request/configuration data, not persisted rows.
Existing source titles, chunk headings and collection memberships supply signals.

All required values are NOT NULL unless marked nullable below. Integer entity
IDs use SQLite AUTOINCREMENT so deleted IDs cannot be reassigned. This matters
when external vector state is stale. All foreign keys use ON DELETE
CASCADE and have a leading index (including unique/primary indexes).

| Table | Columns and purpose |
| --- | --- |
| sources | id; source_type; title; original_url (nullable); file_path (nullable); mime_type; unique content_hash; captured_at; indexed_at (nullable); processing_status; is_deleted; created_at; updated_at |
| documents | id; unique source_id FK; extracted_text; language (nullable); extraction_method; extraction_status; content_length; created_at |
| chunks | id; document_id FK; chunk_index; chunk_text; token_count; page_number (nullable); heading (nullable); start_offset; end_offset; created_at |
| embedding_records | id; unique chunk_id FK; model_name; model_version; unique vector_index_id; dimension; content_hash; created_at |
| collections | id; unique name; description (nullable); created_at; updated_at |
| collection_items | composite PK (collection_id FK, source_id FK); created_at |
| indexing_jobs | id; source_id FK; stage; status; attempts; error (nullable); created_at; updated_at |
| chunk_fts | FTS5 virtual table: chunk_text, title, heading; rowid equals chunk ID |
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
  `is_deleted` is restricted to 0 or 1; 1 is a durable pending-deletion tombstone,
  not evidence of completed cleanup. Source indexes cover captured time, type + captured time,
  processing status and deletion flag.
- Document extraction status: `pending`, `complete`, `failed`; nonnegative
  content_length, measured in Unicode code points after extraction. Language is
  nullable when unknown. Text may be empty for pending/failed extraction.
- Chunks: unique `(document_id, chunk_index)`, zero-based nonnegative index,
  nonblank text, positive token_count, positive one-based page number when
  known. Offsets are zero-based, half-open Unicode code-point offsets into the
  document text; `0 <= start_offset < end_offset`. M2 uses lexical words and
  punctuation (long runs split every 32 characters). MiniLM uses separate bounded
  WordPiece windows when embedding. Exact chunk slices and overlap are tested.
- Embeddings: positive dimension; nonblank model identity and version;
  `vector_index_id = chunk_id`. `content_hash` is the SHA-256 of chunk text;
  legacy empty hashes are invalidated during reconciliation. Model version is
  a fingerprint of the verified model files and pooling policy. Vectors live in
  FAISS, never as SQL BLOBs.
- Collection names are nonblank and case-sensitive unique. Membership is
  unique by its composite key. Source-side lookups have a separate index.
- Job status: `pending`, `running`, `succeeded`, `failed`; attempts >= 0, initially
  0. Stage is constrained to `ingestion` or `indexing`, defaulting to ingestion.
  Indexes cover source, `(status, created_at)` and `(stage, status)`. A source has
  separate ingestion/indexing jobs and may receive later repair jobs. Each claim increments
  attempts; the default maximum is three. Errors contain fixed public codes,
  not copied parser exceptions or content.

M2 required no schema change. M3 migration preserves existing rows, assigns old
jobs to the ingestion stage and backfills FTS. Successful ingestion atomically
publishes document/chunks/FTS, marks the ingestion job succeeded and queues an
indexing job. Source status remains pending until indexing starts, then becomes
indexed with a UTC `indexed_at` only after FAISS persistence and metadata commit.
Extraction failure leaves an empty failed document; indexing failure retains
completed extraction and keyword entries. Startup queues existing M2 documents
for embeddings. Failed indexing attempts are not automatically reset forever.

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
memberships; source content remains. The M3 deletion service coordinates these
cascades with owned-file and FAISS cleanup. Logical database deletion does
not guarantee forensic erasure of disk pages, WAL, backups or SSD blocks.

FTS5 uses `unicode61 remove_diacritics 2`. Chunk insert/update/delete triggers
synchronize text and headings; source-title and document-source triggers keep
title metadata current. Chunk-text edits invalidate embedding records. Startup
checks FTS integrity, trigger SQL and content against chunks/documents/sources,
then verifies vector IDs, model metadata and chunk hashes. Missing/corrupt derived
state is repaired from durable normalized data. Virtual-table shadow tables are
managed by SQLite and excluded from ORM autogeneration. See [search](search.md).
