"""Content-based detection with bounded text and OOXML validation."""

import re
import stat
import unicodedata
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from app.core.config import Settings
from app.ingestion.errors import ImportFailure
from app.security.images import image_header

MIMES = {
    "pdf": "application/pdf", "txt": "text/plain", "markdown": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "note": "text/plain",
}
EXTENSIONS = {".pdf": "pdf", ".txt": "txt", ".md": "markdown", ".markdown": "markdown", ".docx": "docx",
              ".png": "image", ".jpg": "image", ".jpeg": "image"}
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def safe_filename(value: str) -> str:
    name = unicodedata.normalize("NFKC", value)
    if not name or len(name) > 240 or any(c in name for c in "/\\:") or any(ord(c) < 32 for c in name):
        raise ImportFailure("invalid_filename", 400)
    name = re.sub(r'[<>"|?*]', "_", name).strip().rstrip(". ")
    if not name or name.startswith(".") or Path(name).suffix.lower() not in EXTENSIONS:
        raise ImportFailure("unsupported_type", 415)
    if Path(name).stem.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name


def text_encoding(path: Path) -> str:
    with path.open("rb") as stream:
        prefix = stream.read(4)
    if prefix.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        raise ImportFailure("invalid_text", 415)
    if prefix.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    return "utf-8-sig"


def validate_text(path: Path) -> str:
    encoding = text_encoding(path)
    try:
        with path.open("r", encoding=encoding, errors="strict") as stream:
            while block := stream.read(65536):
                if any((ord(c) < 32 and c not in "\t\r\n\f") or 0x7F <= ord(c) <= 0x9F for c in block):
                    raise ImportFailure("invalid_text", 415)
    except UnicodeError:
        raise ImportFailure("invalid_text", 415) from None
    return encoding


def validate_docx(path: Path, expanded_limit: int) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if len(entries) > 2048 or len(names) != len(entries):
                raise ImportFailure("unsafe_archive", 415)
            if not {"[Content_Types].xml", "word/document.xml", "_rels/.rels"} <= names:
                raise ImportFailure("invalid_docx", 415)
            if sum(entry.file_size for entry in entries) > expanded_limit:
                raise ImportFailure("unsafe_archive", 415)
            for entry in entries:
                name = entry.filename
                if (PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                        or "\\" in name or ":" in name or entry.flag_bits & 1
                        or stat.S_ISLNK(entry.external_attr >> 16)
                        or entry.file_size > max(entry.compress_size, 1) * 1000
                        or "vbaproject" in name.lower()):
                    raise ImportFailure("unsafe_archive", 415)
                # Do not allow DTD/entity expansion in any XML part. Stream and check CRC.
                if name.endswith((".xml", ".rels")):
                    tail = b""
                    with archive.open(entry) as part:
                        while block := part.read(65536):
                            scan = (tail + block).upper().replace(b"\x00", b"")
                            if b"<!DOCTYPE" in scan or b"<!ENTITY" in scan:
                                raise ImportFailure("unsafe_archive", 415)
                            tail = block[-32:]
            content = archive.getinfo("[Content_Types].xml")
            if content.file_size > 1024 * 1024:
                raise ImportFailure("unsafe_archive", 415)
            root = ElementTree.fromstring(archive.read(content))
            if not any(node.attrib.get("PartName") == "/word/document.xml" and
                       node.attrib.get("ContentType") == DOCX_CONTENT_TYPE for node in root):
                raise ImportFailure("invalid_docx", 415)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, NotImplementedError, EOFError, zlib.error):
        raise ImportFailure("invalid_docx", 415) from None


def detect_file(path: Path, filename: str, settings: Settings) -> str:
    size = path.stat().st_size
    if size == 0:
        raise ImportFailure("empty_file")
    if size > settings.max_upload_bytes:
        raise ImportFailure("file_too_large", 413)
    expected = EXTENSIONS[Path(safe_filename(filename)).suffix.lower()]
    if expected == "image":
        mime, _, _ = image_header(path, settings.max_image_pixels)
        expected_mime = "image/png" if Path(filename).suffix.lower() == ".png" else "image/jpeg"
        if mime != expected_mime:
            raise ImportFailure("type_mismatch", 415)
        return "image"
    with path.open("rb") as stream:
        prefix = stream.read(8)
    if prefix.startswith(b"%PDF-"):
        detected = "pdf"
    elif prefix.startswith(b"PK\x03\x04"):
        validate_docx(path, settings.max_docx_expanded_bytes)
        detected = "docx"
    else:
        validate_text(path)
        detected = expected if expected in {"txt", "markdown"} else "txt"
    if detected != expected:
        raise ImportFailure("type_mismatch", 415)
    return detected
