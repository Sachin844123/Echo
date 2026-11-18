"""Public retrieval failures contain fixed messages, never query or document text."""

MESSAGES = {
    "model_unavailable": "Provision the local embedding model before semantic indexing or search.",
    "model_mismatch": "Stored and configured model identities differ. Restore the matching model or explicitly rebuild the index.",
    "model_invalid": "The local model files failed validation.",
    "index_unavailable": "The vector index is unavailable; inspect indexing status or rebuild it.",
    "indexing_failed": "Indexing failed; extracted content was retained for retry.",
    "invalid_request": "The request or filter values are invalid.",
    "not_found": "The requested source or collection does not exist.",
    "conflict": "The requested name or membership conflicts with existing data.",
    "source_deleted": "The source has been deleted or is pending deletion.",
}


class RetrievalFailure(Exception):
    def __init__(self, code: str, status: int = 503):
        if code not in MESSAGES:
            raise ValueError("unknown retrieval error")
        self.code, self.status = code, status
        super().__init__(code)
