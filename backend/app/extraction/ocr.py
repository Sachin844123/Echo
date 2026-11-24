"""Offline Tesseract OCR through PyMuPDF, within the bounded parser subprocess."""

import math
from pathlib import Path

from app.core.config import Settings
from app.ingestion.errors import ImportFailure
from app.security.images import image_header


def ocr_status(settings: Settings) -> dict:
    languages = settings.ocr_languages.split("+")
    available = all((settings.ocr_data_dir / f"{language}.traineddata").is_file() for language in languages)
    return {"enabled": settings.ocr_enabled, "available": settings.ocr_enabled and available,
            "languages": languages, "dpi": settings.ocr_dpi,
            "error": "ocr_disabled" if not settings.ocr_enabled else (None if available else "ocr_unavailable")}


def require_ocr(settings: Settings) -> None:
    status = ocr_status(settings)
    if status["error"]:
        raise ImportFailure(status["error"])


def page_text(page, settings: Settings, *, full: bool = True) -> str:
    require_ocr(settings)
    # Bound the rendered page and image dimensions before native OCR allocation.
    width = math.ceil(page.rect.width * settings.ocr_dpi / 72)
    height = math.ceil(page.rect.height * settings.ocr_dpi / 72)
    if width < 1 or height < 1 or width * height > settings.max_image_pixels:
        raise ImportFailure("image_limit")
    if any(image[2] * image[3] > settings.max_image_pixels for image in page.get_images(full=True)):
        raise ImportFailure("image_limit")
    try:
        textpage = page.get_textpage_ocr(language=settings.ocr_languages, dpi=settings.ocr_dpi,
                                        full=full, tessdata=str(settings.ocr_data_dir))
        return page.get_text("text", textpage=textpage, sort=True)
    except Exception:
        raise ImportFailure("ocr_failed") from None


def image_pixmap(path: Path, settings: Settings):
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    image_header(path, settings.max_image_pixels)
    try:
        pixmap = pymupdf.Pixmap(str(path))
    except Exception:
        raise ImportFailure("invalid_image") from None
    if pixmap.width * pixmap.height > settings.max_image_pixels:
        raise ImportFailure("image_limit")
    return pixmap


def image_text(path: Path, settings: Settings) -> str:
    import pymupdf

    require_ocr(settings)
    pixmap = image_pixmap(path, settings)
    try:
        if pixmap.colorspace != pymupdf.csRGB:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        if pixmap.alpha:
            pixmap = pymupdf.Pixmap(pixmap, 0)
        data = pixmap.pdfocr_tobytes(language=settings.ocr_languages, tessdata=str(settings.ocr_data_dir))
        with pymupdf.open(stream=data, filetype="pdf") as document:
            return document[0].get_text("text", sort=True)
    except Exception:
        raise ImportFailure("ocr_failed") from None
