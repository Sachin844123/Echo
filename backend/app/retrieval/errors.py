"""Public retrieval failures contain fixed messages, never query or document text."""

MESSAGES = {
    "visual_disabled": "Visual image indexing and search are disabled in server settings.",
    "visual_model_unavailable": "Prepare the local CLIP model before visual image indexing or search.",
    "visual_query_too_long": "Use a shorter visual description (CLIP supports at most 77 tokens).",
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
