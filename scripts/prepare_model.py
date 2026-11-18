"""Explicit SETUP-ONLY network download of pinned MiniLM files; never called by the API."""

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
from app.embeddings.local import MODEL_FILES

REPOSITORY = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="Pinned Hugging Face commit; omitted resolves the current commit once")
    parser.add_argument("--destination", type=Path, default=Settings.from_env().embedding_model_dir)
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists():
        parser.error("destination already exists; choose a new directory to preserve existing model files")
    with urllib.request.urlopen(f"https://huggingface.co/api/models/{REPOSITORY}", timeout=30) as response:
        revision = args.revision or json.load(response)["sha"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        parser.error("revision must be a 40-character commit hash")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".model-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        files = {}
        for name in MODEL_FILES:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(f"https://huggingface.co/{REPOSITORY}/resolve/{revision}/{name}", timeout=120) as response, target.open("wb") as stream:
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            with target.open("rb") as stream:
                files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        (staging / "echo-model.json").write_text(json.dumps({"name": REPOSITORY, "revision": revision, "files": files}, indent=2), encoding="utf-8")
        staging.replace(destination)
        print(f"Provisioned {REPOSITORY} at revision {revision}.")
    except BaseException:
        # Only this newly created, verified staging directory is eligible for cleanup.
        if staging.resolve().parent == destination.parent and staging.name.startswith(".model-"):
            shutil.rmtree(staging)
        raise


if __name__ == "__main__":
    main()
