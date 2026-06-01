"""Download the Python 3.11 Windows embeddable zip for the MSI stage.

The embeddable distribution is a self-contained Python interpreter
(~10 MB) that does NOT need an installer or admin rights to use. The
MSI bundles it into ``<install>/python/`` and points a ``graphindex.bat``
shim at it.

We pin to 3.11 because the project's ``requires-python=">=3.10,<3.13"``
includes it and 3.11 is the most-compatible Windows version (no free-
threaded edge cases, widest wheel coverage for tree-sitter et al.).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

# python.org has a redirector for the latest patch of each minor.
# Pin to a specific build so the MSI build is reproducible.
PYTHON_VERSION = "3.11.9"
EMBEDDABLE_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(out: Path, *, force: bool = False) -> Path:
    """Download (or reuse) the embeddable zip at ``out``. Returns the path."""
    if out.exists() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[python] downloading {EMBEDDABLE_URL}")
    print(f"[python]       -> {out}")
    tmp = out.with_suffix(out.suffix + ".part")
    urllib.request.urlretrieve(EMBEDDABLE_URL, tmp)
    tmp.replace(out)
    print(f"[python] sha256: {sha256(out)}")
    return out


def extract(zip_path: Path, target: Path, *, force: bool = False) -> Path:
    """Extract the embeddable zip into ``target``. Returns ``target``."""
    if target.exists() and (target / "python.exe").is_file() and not force:
        return target
    target.mkdir(parents=True, exist_ok=True)
    print(f"[python] extracting {zip_path.name} -> {target}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)
    # Sanity check: the embeddable has a python.exe at the root.
    if not (target / "python.exe").is_file():
        raise RuntimeError(
            f"Extracted Python at {target} is missing python.exe — "
            f"the downloaded archive is not the expected embeddable layout."
        )
    print(f"[python] ready: {target / 'python.exe'}")
    return target


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path, required=True,
                   help="Where to put python.zip and python/ (extracted).")
    p.add_argument("--force", action="store_true",
                   help="Re-download / re-extract even if files exist.")
    args = p.parse_args()

    zip_path = args.out_dir / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    extracted = args.out_dir / "python"

    download(zip_path, force=args.force)
    extract(zip_path, extracted, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
