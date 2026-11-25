"""Install and launch ECHO from an extracted or cloned repository."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import venv
from contextlib import closing
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENVIRONMENT = ROOT / ".venv"
MINILM_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


class SetupError(Exception):
    """A setup failure with an actionable message safe to print."""


def run(label: str, command: list[str | Path], *, cwd: Path = ROOT) -> None:
    print(f"\n{label}", flush=True)
    try:
        subprocess.run([str(item) for item in command], cwd=cwd, check=True)
    except subprocess.CalledProcessError as error:
        raise SetupError(f"{label} failed (exit {error.returncode}). See the output above.") from None


def check_prerequisites() -> str:
    if sys.version_info < (3, 11):
        raise SetupError("ECHO requires Python 3.11 or newer. Python 3.12 is recommended.")
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute("CREATE VIRTUAL TABLE setup_check USING fts5(content)")
    except sqlite3.Error:
        raise SetupError("Install a Python build with SQLite FTS5 support and retry.") from None

    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise SetupError("Install Node.js 22.12 or newer with npm, open a new terminal, and retry.")
    result = subprocess.run(
        [node, "-p", "process.versions.node"], capture_output=True, text=True, check=False,
    )
    try:
        version = tuple(map(int, result.stdout.strip().split(".")))
    except ValueError:
        version = ()
    if result.returncode or version < (22, 12):
        raise SetupError("Update Node.js to 22.12 or newer and retry.")
    return npm


def prepare_models(python: Path) -> None:
    from app.core.config import Settings
    from app.embeddings.local import LocalEncoder
    from app.embeddings.visual import VisualEncoder
    from app.extraction.ocr import ocr_status
    from app.retrieval.errors import RetrievalFailure
    from prepare_model import REPOSITORY

    try:
        settings = Settings.from_env()
    except ValueError:
        raise SetupError("Review the ECHO environment settings in README.md and retry.") from None

    # The existing downloaders stage writes and refuse to overwrite any destination.
    if not settings.embedding_model_dir.exists() and settings.embedding_model_name == REPOSITORY:
        run("Downloading the MiniLM text model", [
            python, ROOT / "scripts" / "prepare_model.py",
            "--revision", MINILM_REVISION, "--destination", settings.embedding_model_dir,
        ], cwd=BACKEND)
    try:
        LocalEncoder(settings).identity
    except RetrievalFailure:
        raise SetupError("The configured text model is missing or invalid. See the model setup in README.md.") from None
    print("Text model verified.", flush=True)

    if settings.ocr_enabled:
        if not settings.ocr_data_dir.exists():
            run("Downloading OCR language data", [
                python, ROOT / "scripts" / "prepare_image_models.py", "ocr",
                "--languages", settings.ocr_languages, "--destination", settings.ocr_data_dir,
            ], cwd=BACKEND)
        if not ocr_status(settings)["available"]:
            raise SetupError("The existing OCR directory lacks a configured language. See docs/images.md.")
        print("OCR language data is ready.", flush=True)

    if settings.visual_indexing_enabled:
        if not settings.visual_model_dir.exists():
            run("Downloading the CLIP image model", [
                python, ROOT / "scripts" / "prepare_image_models.py",
                "visual", "--destination", settings.visual_model_dir,
            ], cwd=BACKEND)
        try:
            VisualEncoder(settings).identity
        except RetrievalFailure:
            raise SetupError("The configured image model is missing or invalid. See docs/images.md.") from None
        print("Image model verified.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-models", action="store_true", help="skip provisioning local models")
    parser.add_argument("--no-launch", action="store_true", help="prepare the workspace and exit")
    args = parser.parse_args()

    setup_lock = None
    try:
        npm = check_prerequisites()
        sys.path.insert(0, str(BACKEND))
        from app.storage.instance_lock import InstanceLock

        setup_dir = ROOT / ".local"
        setup_dir.mkdir(exist_ok=True)
        setup_lock = InstanceLock(setup_dir / "setup.lock")
        try:
            setup_lock.acquire()
        except RuntimeError:
            raise SetupError("Another setup is running for this checkout.") from None

        python = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if Path(sys.prefix).resolve() != ENVIRONMENT.resolve():
            config = ENVIRONMENT / "pyvenv.cfg"
            if python.is_file() != config.is_file():
                raise SetupError("The existing .venv is incomplete or from another OS. Move it aside and retry.")
            if not python.is_file():
                print("Creating the ECHO Python environment ...", flush=True)
                venv.EnvBuilder().create(ENVIRONMENT)
            setup_lock.release()
            return subprocess.call([str(python), __file__, *sys.argv[1:]], cwd=BACKEND)

        print("Setup uses your package registries and public model hosts. ECHO runs locally afterward.", flush=True)
        if find_spec("pip") is None:
            try:
                run("Preparing pip", [python, "-m", "ensurepip"])
            except SetupError:
                raise SetupError("Enable your Python installation's venv and ensurepip support, then rerun setup.") from None
        run("Installing Python dependencies", [
            python, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
            "-r", BACKEND / "requirements-dev.txt", "-c", BACKEND / "requirements-lock.txt",
        ])
        run("Checking Python dependencies", [python, "-m", "pip", "check"])
        run("Installing dashboard dependencies", [npm, "ci", "--include=dev", "--no-audit", "--no-fund"], cwd=FRONTEND)
        run("Building the dashboard", [npm, "run", "build"], cwd=FRONTEND)
        if not args.skip_models:
            # Match the backend working directory for relative environment settings.
            os.chdir(BACKEND)
            prepare_models(python)

        if args.no_launch:
            run("Initializing the workspace database", [python, "-m", "app", "migrate"], cwd=BACKEND)
            print("\nECHO setup is complete.", flush=True)
        else:
            run("Starting ECHO", [python, "-m", "app", "launch"], cwd=BACKEND)
        return 0
    except SetupError as error:
        print(f"ECHO setup: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print("ECHO setup could not run a tool. Check available disk space, permissions, and installed runtimes.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nECHO setup stopped.", file=sys.stderr)
        return 130
    finally:
        if setup_lock is not None:
            setup_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
