"""Build the graphindex wheel with the built React SPA bundled inside.

Steps:
1. Run ``npm run build`` in ``frontend/`` (no-op if ``dist/`` already up to date).
2. Copy ``frontend/dist/*`` into ``graphindex/frontend_dist/`` — this is the
   path the server looks up via importlib.resources after install.
3. ``python -m build --wheel`` (or ``setup.py sdist bdist_wheel`` fallback)
   from the repo root. The wheel is written to ``dist/``.

The bundled frontend inflates the wheel by ~1-3 MB (gzipped) — far smaller
than shipping a separate .msi asset.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
PACKAGE_FRONTEND_DIST = REPO_ROOT / "graphindex" / "frontend_dist"


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"[wheel] $ {' '.join(cmd)}   (cwd={cwd})")
    res = subprocess.run(cmd, cwd=cwd)
    if res.returncode != 0:
        raise SystemExit(f"command failed with code {res.returncode}: {' '.join(cmd)}")


def build_frontend(*, skip: bool) -> None:
    """Run ``npm run build`` unless ``--skip-frontend`` or dist is up to date."""
    if skip:
        print("[wheel] --skip-frontend: using existing frontend/dist/")
    elif not FRONTEND_DIST.exists() or not (FRONTEND_DIST / "index.html").exists():
        if not (FRONTEND_DIR / "node_modules").exists():
            print("[wheel] installing frontend deps (npm ci)…")
            _run(["npm", "ci"], cwd=FRONTEND_DIR)
        print("[wheel] building frontend (npm run build)…")
        _run(["npm", "run", "build"], cwd=FRONTEND_DIR)
    else:
        print(f"[wheel] using existing {FRONTEND_DIST}  (pass --rebuild-frontend to force)")
    if not (FRONTEND_DIST / "index.html").exists():
        raise SystemExit(
            f"frontend/dist/index.html not found after build. "
            f"Run `npm run build` in {FRONTEND_DIR}."
        )


def copy_frontend_into_package() -> None:
    """Mirror frontend/dist/ into graphindex/frontend_dist/."""
    if PACKAGE_FRONTEND_DIST.exists():
        shutil.rmtree(PACKAGE_FRONTEND_DIST)
    print(f"[wheel] copying {FRONTEND_DIST} -> {PACKAGE_FRONTEND_DIST}")
    shutil.copytree(FRONTEND_DIST, PACKAGE_FRONTEND_DIST)


def build_wheel(out_dir: Path) -> Path:
    """Build a wheel into ``out_dir`` and return the produced .whl path.

    Order of preference:
      1. ``python -m build --wheel``         (modern, recommended)
      2. ``python -m pip wheel .``           (works on any project with
                                              pyproject.toml, no `build` pkg)
      3. ``python -m setuptools``            (pyproject-only fallback)
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        ([sys.executable, "-m", "build", "--wheel", "--outdir", str(out_dir)], None),
        ([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(out_dir), "."], REPO_ROOT),
        ([sys.executable, "-m", "setuptools", "bdist_wheel"], None),
    ]
    last_err: SystemExit | None = None
    for cmd, cwd in candidates:
        try:
            _run(cmd, cwd=cwd or REPO_ROOT)
            break
        except SystemExit as e:
            last_err = e
            print(f"[wheel] {cmd[2]} failed; trying next option…")
    else:
        raise last_err or SystemExit("wheel build failed")
    wheels = sorted(out_dir.glob("graphindex-*.whl"))
    if not wheels:
        raise SystemExit(f"no graphindex-*.whl found in {out_dir} after build")
    wheel = wheels[-1]
    print(f"[wheel] produced: {wheel}  ({wheel.stat().st_size // 1024} KB)")
    return wheel


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "dist",
                   help="Where to write the .whl (default: <repo>/dist).")
    p.add_argument("--skip-frontend", action="store_true",
                   help="Don't run npm — assume frontend/dist is already built.")
    p.add_argument("--rebuild-frontend", action="store_true",
                   help="Force a fresh `npm run build` even if dist/ exists.")
    args = p.parse_args()
    args.out_dir = args.out_dir.resolve()

    build_frontend(skip=args.skip_frontend)
    copy_frontend_into_package()
    build_wheel(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
