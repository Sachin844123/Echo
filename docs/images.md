# OCR and image search

Import PNG and JPEG images from **Import**. To search their filenames or
recognized text, choose **Keywords** or **Hybrid** and filter by **Image**.
Choose **Images** to describe the subject, scene or layout you remember. ECHO
uses local CLIP to rank imported images by appearance. Open a result to see
its image and any recognized text.

## Set up on Windows

From the repository root, stop the backend before migrating. Install the
updated dependencies and provision the model folders that are missing:

```powershell
Set-Location C:\Projects\Echo
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-lock.txt
.\.venv\Scripts\python.exe scripts\prepare_image_models.py ocr
.\.venv\Scripts\python.exe scripts\prepare_image_models.py visual
Set-Location frontend
npm ci
npm run build
Set-Location ..\backend
..\.venv\Scripts\python.exe -m app migrate
..\.venv\Scripts\python.exe -m app serve
```

Open `http://127.0.0.1:8000/` to go straight to the workspace, or start it with
`Run-ECHO.bat`. Back up `.local` with the server stopped before upgrading your
library. The model commands preserve existing setup and refuse to overwrite
their destination. They download public assets during setup only. PyMuPDF
uses local Tesseract language data, and CLIP's approximately 605 MB model
loads on demand. [PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/ocr/index.html),
[CLIP weights](https://huggingface.co/openai/clip-vit-base-patch32/blob/bfc19449bc6f18c54292b85378cbccc3ad91a24e/model.safetensors).

English (`eng`) is the default. To use English and Hindi, prepare a separate
folder and set both variables in the terminal that starts ECHO:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_image_models.py ocr --languages eng+hin --destination .local\models\tessdata-eng-hin
$env:ECHO_OCR_DATA_DIR = (Resolve-Path .local\models\tessdata-eng-hin).Path
$env:ECHO_OCR_LANGUAGES = 'eng+hin'
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `ECHO_OCR_ENABLED` | `true` | Enable local recognition |
| `ECHO_OCR_DATA_DIR` | `.local/models/tessdata` | Installed language packs |
| `ECHO_OCR_LANGUAGES` | `eng` | Up to four three-letter language codes joined with `+` |
| `ECHO_OCR_DPI` | `200` | PDF OCR resolution from 100 to 300 |
| `ECHO_MAX_IMAGE_PIXELS` | `20000000` | Raster and PDF OCR render ceiling |
| `ECHO_VISUAL_MODEL_DIR` | `.local/models/clip-vit-base-patch32` | Local CLIP model |

## Existing imports and limits

Open an existing PDF or image in **Library** and choose **Reprocess** to apply
OCR settings to its stored copy. Reprocessing removes the source from search
until extraction finishes. **Sources** shows separate extraction, text indexing
and visual indexing jobs. Fix a missing model or language pack before retrying.
If OCR data is unavailable, images remain searchable by filename and visual
description once their respective indexes are ready. PDFs keep their native
text layer when present. A scan without text reports a setup error.

OCR accuracy depends on scan quality, orientation and language. Verify important
details against the original. Recognized PDF passages retain page references.
Image previews are authenticated, resized and re-encoded without original
metadata. Images embedded in DOCX do not go through OCR. Visual search covers
standalone imports and works best with short, concrete descriptions. Use OCR
to find small words in an image. The configured parser timeout also applies to
OCR. Large scans can take longer, and inference has no hard process memory quota.

## Compare search profiles

The dashboard defaults to `source_balanced`. Each text method considers up to
2,000 eligible chunks and contributes up to 50 distinct sources. Hybrid modes
combine keyword and semantic ranks per source through RRF. ECHO reuses existing
chunk vectors. Set `ECHO_RETRIEVAL_PROFILE=classic` to select the previous
chunk-first candidate policy and `ECHO_SPELLING_CORRECTION=false` to disable
spelling correction by default. The dashboard also allows a per-search override.
ECHO displays each correction and reports when it reaches the chunk scan cap.
`ECHO_CANDIDATE_SCAN_LIMIT` changes that cap.

Use the tuning split to choose the profile, correction option and weights.
Freeze those settings and OCR parameters before running the held-out test split.
The evaluation harness compares the four text retrieval methods. See the
[evaluation instructions](../evaluation/README.md).
