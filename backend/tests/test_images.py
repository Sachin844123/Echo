"""Tiny labelled TEST DATA; real OCR/CLIP checks are not research accuracy results."""

import io
import socket
import time

import numpy as np
import pymupdf
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.config import REPO_ROOT, Settings
from app.database.models import ImageEmbeddingRecord, IndexingJob
from app.embeddings.visual import VisualEncoder
from app.extraction.ocr import image_text
from app.extraction.parsers import extract_to_spool
from app.ingestion.errors import ImportFailure
from app.retrieval.errors import RetrievalFailure
from app.security.file_validation import detect_file
from test_retrieval import UnitEncoder


def test_image_bytes(format="PNG"):
    # A rasterized labelled TEST DATA page, containing no embedded text layer.
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=180)
        page.insert_text((30, 65), "TEST DATA ORCHID GUIDELINES", fontsize=24)
        page.insert_text((30, 110), "Solar field project instructions", fontsize=22)
        png = page.get_pixmap(dpi=150).tobytes("png")
    if format == "PNG":
        return png
    with Image.open(io.BytesIO(png)) as image:
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG")
        return output.getvalue()


test_image_bytes.__test__ = False


@pytest.fixture
def ocr_settings(settings):
    data = REPO_ROOT / ".local/models/tessdata"
    if not (data / "eng.traineddata").is_file():
        pytest.skip("Run scripts/prepare_image_models.py ocr for real offline OCR tests")
    return settings.model_copy(update={"ocr_enabled": True, "ocr_data_dir": data})


@pytest.mark.parametrize("suffix,format", [("png", "PNG"), ("jpg", "JPEG")])
def test_real_image_ocr_and_sniffing_offline(tmp_path, ocr_settings, monkeypatch, suffix, format):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("OCR attempted network access"))
    path = tmp_path / f"TEST-DATA.{suffix}"
    path.write_bytes(test_image_bytes(format))
    assert detect_file(path, path.name, ocr_settings) == "image"
    assert "ORCHID" in image_text(path, ocr_settings).upper()
    with pytest.raises(ImportFailure):
        detect_file(path, "TEST-DATA.jpg" if suffix == "png" else "TEST-DATA.png", ocr_settings)
    with pytest.raises(ImportFailure, match="image_limit"):
        detect_file(path, path.name, ocr_settings.model_copy(update={"max_image_pixels": 10000}))


def test_real_scanned_pdf_ocr_keeps_page_and_method(tmp_path, ocr_settings):
    path, output = tmp_path / "TEST-DATA.pdf", tmp_path / "TEST-DATA.jsonl"
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=180)
        page.insert_image(page.rect, stream=test_image_bytes())
        document.save(path)
    assert extract_to_spool(path, "pdf", output, ocr_settings) == "pymupdf_tesseract"
    import json
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert "ORCHID" in rows[0]["text"].upper()
    assert rows[0]["page_number"] == 1


def test_missing_or_disabled_ocr_and_malformed_images_fail_explicitly(tmp_path, settings):
    path = tmp_path / "TEST-DATA.png"
    path.write_bytes(test_image_bytes())
    with pytest.raises(ImportFailure, match="ocr_disabled"):
        image_text(path, settings)
    with pytest.raises(ImportFailure, match="ocr_unavailable"):
        image_text(path, settings.model_copy(update={"ocr_enabled": True, "ocr_data_dir": tmp_path / "absent"}))
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ImportFailure, match="invalid_image"):
        detect_file(path, path.name, settings)


@pytest.fixture(scope="module")
def visual_encoder():
    settings = Settings()
    if not (settings.visual_model_dir / "echo-model.json").is_file():
        pytest.skip("Run scripts/prepare_image_models.py visual for real local CLIP tests")
    return VisualEncoder(settings)


def test_real_visual_encoder_offline_normalization_and_reuse(tmp_path, visual_encoder, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("CLIP attempted network access"))
    path = tmp_path / "TEST-DATA.png"
    path.write_bytes(test_image_bytes())
    image = visual_encoder.encode_image(path)
    text = visual_encoder.encode_text("a page of printed text")
    assert image.shape == text.shape == (1, 512)
    np.testing.assert_allclose(np.linalg.norm(image, axis=1), [1], atol=1e-5)
    np.testing.assert_allclose(np.linalg.norm(text, axis=1), [1], atol=1e-5)
    model = visual_encoder._model
    np.testing.assert_allclose(text, visual_encoder.encode_text("a page of printed text"), atol=1e-5)
    assert model is visual_encoder._model
    with pytest.raises(RetrievalFailure, match="visual_query_too_long"):
        visual_encoder.encode_text("TEST DATA " * 100)


def test_image_import_ocr_visual_preview_reprocess_and_deletion(client, app, auth, ocr_settings, visual_encoder):
    service, search = app.state.ingestion, app.state.search
    service.settings = ocr_settings
    search.encoder = UnitEncoder()
    search.visual.encoder = visual_encoder
    search.reconcile()
    response = client.post('/api/v1/imports/files?filename=TEST-DATA-orchid.png',
        headers={**auth, 'Content-Type': 'application/octet-stream'}, content=test_image_bytes())
    assert response.status_code == 202
    source_id = response.json()['source_id']

    def wait_indexed():
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            with service.sessions() as session:
                pending = session.scalar(select(func.count()).select_from(IndexingJob).where(
                    IndexingJob.source_id == source_id, IndexingJob.status.in_(['pending', 'running'])))
            if not pending:
                break
            time.sleep(.05)
        assert client.get(f'/api/v1/sources/{source_id}', headers=auth).json()['processing_status'] == 'indexed'

    wait_indexed()
    for mode, query in [('keyword', 'orchid'), ('hybrid', 'orchid'), ('visual', 'a page of printed text')]:
        result = client.post('/api/v1/search', headers=auth, json={'query': query, 'mode': mode, 'source_types': ['image']})
        assert result.status_code == 200
        assert result.json()['results'][0]['source_id'] == source_id
    assert client.get(f'/api/v1/sources/{source_id}/image').status_code == 401
    preview = client.get(f'/api/v1/sources/{source_id}/image', headers=auth)
    assert preview.headers['content-type'] == 'image/png'
    assert preview.headers['cache-control'] == 'no-store'
    assert preview.content.startswith(b'\x89PNG')
    assert client.get(f'/api/v1/sources/{source_id}/document', headers=auth).json()['extraction_method'] == 'tesseract_image'
    assert client.post(f'/api/v1/sources/{source_id}/reprocess', headers=auth).status_code == 202
    wait_indexed()
    assert search.visual.vectors.ids == {source_id}
    search.reconcile()
    assert search.visual.vectors.ids == {source_id}
    assert client.delete(f'/api/v1/sources/{source_id}', headers=auth).status_code == 200
    assert not search.visual.vectors.ids
    with service.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ImageEmbeddingRecord)) == 0
    assert client.get(f'/api/v1/sources/{source_id}/image', headers=auth).status_code == 404


def test_blank_image_uses_real_filename_metadata(tmp_path, ocr_settings):
    path, output = tmp_path / 'TEST-DATA.png', tmp_path / 'TEST-DATA.jsonl'
    Image.new('RGB', (200, 200), 'white').save(path)
    method = extract_to_spool(path, 'image', output, ocr_settings, 'TEST DATA blank image')
    assert method == 'image_filename'
    assert 'TEST DATA blank image' in output.read_text()


def test_missing_language_data_keeps_native_pdf_text_and_image_filename(tmp_path, settings):
    settings = settings.model_copy(update={'ocr_enabled': True, 'ocr_data_dir': tmp_path / 'absent'})
    pdf = tmp_path / 'TEST-DATA-mixed.pdf'
    raster = test_image_bytes()
    with pymupdf.open() as doc:
        doc.new_page()
        page = doc.new_page()
        page.insert_text((40, 50), 'TEST DATA digital text')
        page.insert_image(pymupdf.Rect(40, 80, 400, 200), stream=raster)
        doc.save(pdf)
    out = tmp_path / 'TEST-DATA-pdf.jsonl'
    assert extract_to_spool(pdf, 'pdf', out, settings) == 'pymupdf_text_ocr_unavailable'
    assert 'TEST DATA digital text' in out.read_text()
    image = tmp_path / 'TEST-DATA.png'
    image.write_bytes(raster)
    out = tmp_path / 'TEST-DATA-image.jsonl'
    assert extract_to_spool(image, 'image', out, settings, 'TEST DATA original title') == 'image_filename_ocr_unavailable'
    assert 'TEST DATA original title' in out.read_text()
