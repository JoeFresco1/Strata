from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


EXCLUDED_PARTS = {
    ".git", ".venv", ".runtime", ".local", ".codex", ".tmp-playwright",
    ".pytest_cache", "__pycache__", "node_modules", "dist", "data", "exports",
}


def release_files() -> list[Path]:
    """Return portable source files while excluding local state and generated assets."""
    files = []
    for source in ROOT.rglob("*"):
        relative = source.relative_to(ROOT)
        if not source.is_file() or any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if source.name == ".env" or source.suffix in {".log", ".pyc"}:
            continue
        files.append(source)
    return files


def main() -> None:
    """Create a clean downloadable self-hosted release archive."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    DIST.mkdir(exist_ok=True)
    archive = DIST / f"strata-{args.version}-self-hosted.zip"
    staging = DIST / f"strata-{args.version}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    for source in release_files():
        destination = staging / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for source in staging.rglob("*"):
            if source.is_file():
                bundle.write(source, Path(staging.name) / source.relative_to(staging))
    shutil.rmtree(staging)
    print(archive)


if __name__ == "__main__":
    main()
