"""App-owned random paths; uploaded names are never filesystem paths."""

import re
import uuid
from pathlib import Path

from app.ingestion.errors import ImportFailure

OWNED_IMPORT = re.compile(r"[0-9a-f]{32}\.(pdf|txt|md|docx|image)")
OWNED_STAGE = re.compile(r"[0-9a-f]{32}\.(part|jsonl)")


class FileStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir.resolve()
        self.imports = self.root / "imports"
        self.staging = self.root / "staging"

    def prepare(self) -> None:
        for folder in (self.imports, self.staging):
            if folder.is_symlink() or folder.resolve().parent != self.root:
                raise ImportFailure("storage_error", 503)
            folder.mkdir(parents=True, exist_ok=True)

    def new_stage(self, suffix: str = "part") -> Path:
        if suffix not in {"part", "jsonl"}:
            raise ValueError("invalid staging suffix")
        return self.staging / f"{uuid.uuid4().hex}.{suffix}"

    def adopt(self, staged: Path, source_type: str) -> str:
        suffix = {"pdf": "pdf", "docx": "docx", "markdown": "md", "txt": "txt", "note": "txt", "image": "image"}[source_type]
        relative = f"imports/{uuid.uuid4().hex}.{suffix}"
        staged.replace(self.resolve(relative))
        return relative

    def resolve(self, relative: str) -> Path:
        parts = relative.split("/")
        if len(parts) != 2 or parts[0] != "imports" or not OWNED_IMPORT.fullmatch(parts[1]):
            raise ImportFailure("missing_file")
        path = self.root / "imports" / parts[1]
        if path.is_symlink() or path.resolve().parent != self.imports:
            raise ImportFailure("missing_file")
        return path

    def remove(self, relative: str) -> None:
        self.resolve(relative).unlink(missing_ok=True)

    def recover_orphans(self, referenced: set[str]) -> None:
        """Only at startup under the exclusive instance lock, before accepting uploads."""
        for path in self.staging.iterdir():
            if OWNED_STAGE.fullmatch(path.name) and not path.is_symlink() and path.is_file():
                path.unlink()
        for path in self.imports.iterdir():
            relative = f"imports/{path.name}"
            if OWNED_IMPORT.fullmatch(path.name) and relative not in referenced and not path.is_symlink() and path.is_file():
                path.unlink()
