"""Stable public error codes; parser exceptions never cross the boundary."""

ERRORS = {
    "invalid_filename": "Provide a plain filename without directory components.",
    "unsupported_type": "Supported formats are PDF, TXT, Markdown and DOCX.",
    "type_mismatch": "File contents do not match the filename extension.",
    "invalid_text": "Text must be valid UTF-8 or BOM-marked UTF-16 without binary control bytes.",
    "empty_file": "The imported file is empty.",
    "file_too_large": "The upload exceeds the configured size limit.",
    "invalid_docx": "The file is not a supported DOCX package.",
    "unsafe_archive": "The DOCX archive violates the safety limits.",
    "invalid_note": "Provide a nonblank title and text within the note limits.",
    "queue_full": "The ingestion queue is full; wait for pending work to finish.",
    "not_found": "The indexing job does not exist.",
    "retry_conflict": "Only failed jobs below the attempt limit can be retried.",
    "missing_file": "The stored input is missing or its path is invalid.",
    "input_changed": "The stored input no longer matches its captured hash.",
    "encrypted_pdf": "Password-protected PDFs are not supported.",
    "invalid_pdf": "The PDF could not be read.",
    "page_limit": "The PDF exceeds the configured page limit.",
    "text_limit": "Extracted text exceeds the configured character limit.",
    "no_extractable_text": "No text was extracted. Image-only documents require OCR, which is not enabled.",
    "extraction_timeout": "Extraction exceeded its configured time limit.",
    "extraction_failed": "The document parser failed; no partial result was published.",
    "interrupted": "The job was interrupted and exhausted its attempt limit.",
    "storage_error": "Local storage is unavailable; check free space and permissions.",
}


class ImportFailure(Exception):
    def __init__(self, code: str, status: int = 422):
        if code not in ERRORS:
            raise ValueError("unknown ingestion error code")
        self.code = code
        self.status = status
        super().__init__(code)
