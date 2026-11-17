"""Tiny hostile/synthetic TEST DATA; no user files are read."""

import io
import zipfile

import pytest
from docx import Document

from app.ingestion.errors import ImportFailure
from app.security.file_validation import detect_file, safe_filename, validate_docx


@pytest.mark.parametrize("name", ["../test.txt", "..\\test.txt", "C:\\test.txt", "/test.txt", "\\\\server\\test.txt", "x.txt:stream", "x\x00.txt", ".txt", "test.exe"])
def test_filename_rejects_paths_and_unsupported_types(name):
    with pytest.raises(ImportFailure):
        safe_filename(name)


def test_filename_sanitization():
    assert safe_filename('TEST <DATA>.txt') == "TEST _DATA_.txt"
    assert safe_filename("CON.txt") == "_CON.txt"
    assert safe_filename(" TEST DATA.md ") == "TEST DATA.md"


@pytest.mark.parametrize("data,name,code", [
    (b"", "empty.txt", "empty_file"), (b"TEST DATA", "fake.pdf", "type_mismatch"),
    (b"%PDF-1.7 TEST DATA", "fake.txt", "type_mismatch"),
    (b"\x89PNG\r\n\x1a\n", "fake.txt", "invalid_text"),
    (b"hello\x00there", "binary.md", "invalid_text"),
    (b"\xff\xfe\x00\x00x\x00\x00\x00", "utf32.txt", "invalid_text"),
])
def test_content_sniffing_rejects_mislabeled_binary(settings, tmp_path, data, name, code):
    path = tmp_path / "input.part"
    path.write_bytes(data)
    with pytest.raises(ImportFailure) as error:
        detect_file(path, name, settings)
    assert error.value.code == code


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_text_encoding_support(settings, tmp_path, encoding):
    path = tmp_path / "input.part"
    path.write_bytes("TEST DATA café हिन्दी".encode(encoding))
    assert detect_file(path, "test.md", settings) == "markdown"


def docx_bytes():
    document = Document()
    document.add_paragraph("TEST DATA fixture")
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def test_docx_is_structurally_detected(settings, tmp_path):
    path = tmp_path / "input.part"
    path.write_bytes(docx_bytes())
    assert detect_file(path, "test.docx", settings) == "docx"
    with pytest.raises(ImportFailure, match="type_mismatch"):
        detect_file(path, "test.txt", settings)


@pytest.mark.parametrize("extra,content", [
    ("../outside.xml", b"test"), ("word/vbaProject.bin", b"test"),
    ("word/evil.xml", b'<!DOCTYPE x [<!ENTITY payload "test">]><x/>'),
    ("word/huge.xml", b"a" * 2_000_000),
])
def test_archive_safety(settings, tmp_path, extra, content):
    path = tmp_path / "input.docx"
    path.write_bytes(docx_bytes())
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(extra, content)
    with pytest.raises(ImportFailure, match="unsafe_archive"):
        validate_docx(path, settings.max_docx_expanded_bytes)


def test_zip_is_not_automatically_docx(settings, tmp_path):
    path = tmp_path / "input.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("TEST DATA.txt", "TEST DATA")
    with pytest.raises(ImportFailure, match="invalid_docx"):
        detect_file(path, "test.docx", settings)


def test_docx_expansion_limit(tmp_path):
    path = tmp_path / "input.docx"
    path.write_bytes(docx_bytes())
    with pytest.raises(ImportFailure, match="unsafe_archive"):
        validate_docx(path, 1024)
