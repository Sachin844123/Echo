# Storage & Permissions

ECHO can automatically index files from folders you approve. The first visit
shows the storage permission dialog. You can also open **Storage** in the
sidebar or **Storage & Permissions** from Settings. No folder is scanned before
you save an access choice. Manual imports work with every choice.

| Access | Scope |
| --- | --- |
| All Accessible Local Files | Eligible content on the fixed Windows drives detected when you grant access |
| Personal Folders Only | Eligible Desktop, Documents, Downloads and Pictures known folders that resolve to fixed local drives |
| Selected Folders Only | Absolute local directory paths you enter, one per line |
| Deny Access | Manual imports only |

Copy an absolute folder path from File Explorer for selected folders or
exclusions. Exclusions must be inside approved roots. You can choose among
ECHO's supported formats. Save permission to confirm the scope and begin
indexing. Root paths, filters, consent and the paused or cancelled state persist
in the library database. Reapprove **All Accessible Local Files** after adding
a new fixed drive if you want ECHO to include it.

The Storage page shows approved folders, stored source-copy bytes, detected and
fully indexed file counts, pending jobs and scan errors. **Activity** provides
individual extraction and embedding job errors. Use **Pause** or **Cancel
indexing** to stop scanning and scheduling new automatic work. An ingestion
operation already in progress may finish. **Resume** and **Rescan** resume work
and check for changes accumulated while ECHO was stopped.

**Revoke and purge** clears permission, stops monitoring and hides sources that
have only automatic references. ECHO retries local deletion failures using its
existing cleanup jobs. Copies also present as manual imports remain searchable.
Deleting the whole library in Settings also clears active folder access. If you
delete a single source while its original remains in an approved folder, it can
return on a later scan. Exclude that folder or revoke access to stop reindexing.

## Windows setup

Stop the current server and back up `.local` before upgrading. From the repository
root, install the updated locked dependencies and rebuild the dashboard:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt -c backend\requirements-lock.txt
.\Run-ECHO.bat --build
```

The launcher applies database revision `0004_local_storage`. The storage worker
uses the existing parser, OCR, text embedding, visual embedding and hybrid
retrieval services. Model requirements remain as described in the
[OCR and image search guide](images.md) and [search guide](search.md).

## Boundaries and operation

- Files are read with the current OS account. The feature does not elevate access
  or change originals. It uses local storage and existing offline models.
- Directory scans use `os.scandir` and check exclusions before descending.
  Nested links, junctions, hard links, hidden/system files and cloud placeholders
  are excluded. Windows verifies the final path of each opened file before
  reading. Protected OS and app directories, common browser and credential
  locations, suspicious filenames, and recognizable key or credential text in
  plain text files are skipped. These checks cannot recognize arbitrary secrets
  embedded in otherwise eligible documents. Prefer selected folders when a drive
  contains a mix of sensitive and searchable files.
- Watchdog uses native Windows notifications. A bounded queue debounces changes
  and requests a scan on overflow. Periodic scans reconcile missed events and
  clean up deleted paths. Other platforms use periodic scans. Temporary sharing
  or permission errors are reported and checked again on a later scan.
- Metadata (size, modification time, file identity) identifies unchanged paths.
  Changed files are hashed and identical content shares one source and index
  entry. An edit that deliberately preserves all recorded metadata may not be
  detected. The supported ingestion process still batches embeddings with
  `ECHO_EMBEDDING_BATCH_SIZE`.
- Automatic tracking is capped at 10,000 paths and 2 GiB of aggregate tracked
  source size. Duplicate paths count toward the safety cap even when they share
  one physical copy. Indexes, extracted text and manual uploads use separate
  disk space. Existing per-file limits still apply.
- Folder controls and file lists use ECHO's authenticated loopback API. Folder
  paths are shown to the local user and stored in SQLite. Logs and public error
  details omit paths, file contents and credentials.

The [watchdog project](https://github.com/gorakhargosh/watchdog) documents its
Windows notification backend. The Windows SDK documents
[final-path validation by file handle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew).
