"""Private subprocess protocol: stdin configuration; stdout contains only status."""

import hashlib
import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.extraction.parsers import extract_to_spool
from app.ingestion.errors import ImportFailure


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        path = Path(request["input"])
        if not path.is_file():
            raise ImportFailure("missing_file")
        with path.open("rb") as stream:
            actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual_hash != request["content_hash"]:
            raise ImportFailure("input_changed")
        settings = Settings(**request["limits"])
        if path.stat().st_size > settings.max_upload_bytes:
            raise ImportFailure("file_too_large")
        method = extract_to_spool(path, request["source_type"], Path(request["output"]), settings, request.get("title"))
        print(json.dumps({"method": method}))
        return 0
    except ImportFailure as error:
        print(json.dumps({"error": error.code}))
        return 1
    except Exception:
        # No parser messages, tracebacks or filenames escape into server output.
        print(json.dumps({"error": "extraction_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
