"""Incremental document reading, executed only in the isolated parser process."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

from app.core.config import Settings
from app.extraction.ocr import image_pixmap, image_text, ocr_status, page_text
from app.ingestion.errors import ImportFailure
from app.processing.text import clean_text
from app.security.file_validation import text_encoding, validate_docx, validate_text

BLOCK_CHARS = 32768


def text_units(path: Path, markdown: bool) -> Iterator[tuple[str, int | None, str | None]]:
    heading = None
    line_start = True
    fence = None
    with path.open("r", encoding=text_encoding(path), errors="strict") as stream:
        while line := stream.readline(BLOCK_CHARS):
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\n")) if markdown and line_start else None
            if marker:
                run, tail = marker.groups()
                if fence is None:
                    fence = run
                elif run[0] == fence[0] and len(run) >= len(fence) and not tail.strip():
                    fence = None
            match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line) if markdown and line_start and fence is None else None
            if match:
                heading = clean_text(match[1])[:200]
            yield line, None, heading
            line_start = line.endswith("\n")


def pdf_units(path: Path, max_pages: int, settings: Settings | None = None,
              methods: set[str] | None = None) -> Iterator[tuple[str, int | None, str | None]]:
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    status = ocr_status(settings) if settings is not None else None
    try:
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ImportFailure("encrypted_pdf")
            if document.page_count > max_pages:
                raise ImportFailure("page_limit")
            for number in range(document.page_count):
                page = document.load_page(number)
                text = page.get_text("text", sort=True)
                has_text = bool(text.strip())
                has_images = bool(page.get_images()) if status and status["enabled"] else False
                if status and status["available"] and (has_images or not has_text):
                    text = page_text(page, settings, full=not bool(text.strip()))
                    if methods is not None:
                        methods.add("ocr")
                elif status and status["error"] == "ocr_unavailable" and has_images and methods is not None:
                    methods.add("ocr_unavailable")
                for start in range(0, len(text), BLOCK_CHARS):
                    yield text[start:start + BLOCK_CHARS], number + 1, None
    except (pymupdf.FileDataError, pymupdf.EmptyFileError):
        raise ImportFailure("invalid_pdf") from None


def docx_units(path: Path) -> Iterator[tuple[str, int | None, str | None]]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    heading = None

    def walk(container, depth=0):
        nonlocal heading
        if depth > 20:
            raise ImportFailure("invalid_docx")
        for block in container.iter_inner_content():
            if isinstance(block, Paragraph):
                if block.style is not None and block.style.name.startswith("Heading"):
                    heading = clean_text(block.text)[:200] or heading
                value = block.text + "\n"
                for start in range(0, len(value), BLOCK_CHARS):
                    yield value[start:start + BLOCK_CHARS], None, heading
            elif isinstance(block, Table):
                # Merged cells can appear repeatedly in row.cells; emit each XML cell once.
                seen = set()
                for row in block.rows:
                    for cell in row.cells:
                        if cell._tc not in seen:
                            seen.add(cell._tc)
                            yield from walk(cell, depth + 1)

    yield from walk(Document(path))


def extract_to_spool(path: Path, source_type: str, output: Path, settings: Settings,
                     title: str | None = None) -> str:
    methods: set[str] = set()
    if source_type in {"txt", "markdown", "note"}:
        encoding = validate_text(path)
        units = text_units(path, source_type == "markdown")
        method = "manual_note" if source_type == "note" else f"{encoding}_text"
    elif source_type == "pdf":
        units = pdf_units(path, settings.max_pdf_pages, settings, methods)
        method = "pymupdf_text"
    elif source_type == "image":
        status = ocr_status(settings)
        if status["available"]:
            value = image_text(path, settings)
            method = "tesseract_image" if value.strip() else "image_filename"
        else:
            image_pixmap(path, settings)  # Validate raster decoding before indexing metadata.
            value = ""
            method = "image_filename_" + status["error"]
        # A real filename remains searchable even when the image contains no text.
        # The extraction method explicitly distinguishes metadata from OCR output.
        units = [(value if value.strip() else (title or ""), 1, None)]
    elif source_type == "docx":
        validate_docx(path, settings.max_docx_expanded_bytes)
        units = docx_units(path)
        method = "python_docx"
    else:
        raise ImportFailure("unsupported_type")

    total = 0
    raw_total = 0
    buffer = ""
    metadata = None

    with output.open("x", encoding="utf-8", newline="\n") as stream:
        def flush():
            nonlocal buffer, total
            cleaned = clean_text(buffer)
            buffer = ""
            if not cleaned:
                return
            total += len(cleaned) + (2 if total else 0)
            if total > settings.max_extracted_chars:
                raise ImportFailure("text_limit")
            stream.write(json.dumps({"text": cleaned, "page_number": metadata[0], "heading": metadata[1]}, ensure_ascii=False) + "\n")

        for text, page, heading in units:
            raw_total += len(text)
            if raw_total > settings.max_extracted_chars * 4:
                raise ImportFailure("text_limit")
            # Never insert a paragraph boundary inside a word or Unicode sequence.
            safe_boundary = buffer[-1:].isspace() or text[:1].isspace()
            if metadata != (page, heading) or (len(buffer) >= BLOCK_CHARS and safe_boundary):
                flush()
            metadata = (page, heading)
            buffer += text
        flush()
    if total == 0:
        if source_type == "pdf" and "ocr_unavailable" in methods:
            raise ImportFailure("ocr_unavailable")
        raise ImportFailure("no_extractable_text")
    if "ocr" in methods:
        return "pymupdf_tesseract"
    if "ocr_unavailable" in methods:
        return "pymupdf_text_ocr_unavailable"
    return method
