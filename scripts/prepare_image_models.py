"""Explicit setup-only downloads of OCR language data and safe CLIP weights."""

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings
from app.embeddings.visual import MODEL_FILES, MODEL_NAME

TESS_REVISION = "87416418657359cb625c412a48b6e1d6d41c29bd"
CLIP_REVISION = "bfc19449bc6f18c54292b85378cbccc3ad91a24e"
CLIP_SHA256 = "99d28a652e6ec46629ab7047a0ac82c69b1fe11e0ce672c43af65d3a9a3fc05d"


def prepare(destination, urls, descriptor):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("destination exists; preserve it and choose a new directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".image-model-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        hashes = {}
        for name, url in urls.items():
            with urllib.request.urlopen(url, timeout=120) as response, (staging / name).open("xb") as output:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > 650 * 1024 * 1024:
                        raise ValueError("model exceeds download limit")
                    output.write(block)
            with (staging / name).open("rb") as stream:
                hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            if name == "model.safetensors" and hashes[name] != CLIP_SHA256:
                raise ValueError("CLIP weight checksum mismatch")
        (staging / "echo-model.json").write_text(json.dumps({**descriptor, "files": hashes}, indent=2), encoding="utf-8")
        staging.replace(destination)
    finally:
        if staging.is_dir() and staging.resolve().parent == destination.parent and staging.name.startswith(".image-model-"):
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["ocr", "visual"])
    parser.add_argument("--languages", default="eng", help="Tesseract codes, e.g. eng+hin")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    settings = Settings(ocr_languages=args.languages)
    if args.kind == "ocr":
        urls = {f"{language}.traineddata": f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{TESS_REVISION}/{language}.traineddata"
                for language in settings.ocr_languages.split("+")}
        destination = args.destination or settings.ocr_data_dir
        descriptor = {"name": "tesseract-ocr/tessdata_fast", "revision": TESS_REVISION}
    else:
        urls = {name: f"https://huggingface.co/{MODEL_NAME}/resolve/{CLIP_REVISION}/{name}" for name in MODEL_FILES}
        destination = args.destination or settings.visual_model_dir
        descriptor = {"name": MODEL_NAME, "revision": CLIP_REVISION}
    try:
        prepare(destination, urls, descriptor)
        print("Local model data prepared. No runtime download is required.")
        return 0
    except Exception:
        print("Model setup failed. Check connectivity and use a new destination if it already exists.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
