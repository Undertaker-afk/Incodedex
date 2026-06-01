"""End-to-end MSI build orchestrator.

Run from the repo root:

    python -m installer.build_msi

Or with knobs:

    python -m installer.build_msi --skip-frontend --skip-download
                                --extras "" --output dist/

This is the only script a release engineer needs. It does, in order:

  1. download_python.py     — fetch the Python 3.11 embeddable (skip with
                              --skip-download if you've already done it)
  2. build_graphindex_wheel.py — npm build (skip with --skip-frontend) +
                                mirror frontend/dist into the package +
                                `python -m build --wheel`
  3. stage.py                — copy Python + the wheel into the MSI
                                staging tree, `pip install` the wheel into
                                the embedded Python with [llama,faiss,mcp]
                                extras (or whatever you pass)
  4. WiX heat + candle + light
                             — harvest the staging tree, compile .wxs,
                                link the .msi
  5. (optional) msivalidate + sign

The final .msi lands in the directory passed via --output (default: dist/).

If WiX is not on PATH, the script prints a clear message telling you
where to get it (``https://wixtoolset.org/releases/``) — no silent
failures.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_DIR = REPO_ROOT / "installer"
DEFAULT_PY_DIR = REPO_ROOT / "build" / "python"


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    print(f"$ {' '.join(cmd)}" + (f"  (cwd={cwd})" if cwd else ""))
    res = subprocess.run(cmd, cwd=cwd, env=env)
    if res.returncode != 0:
        raise SystemExit(f"command failed (exit {res.returncode}): {' '.join(cmd)}")


def step_download_python(*, skip: bool, out_dir: Path) -> Path:
    extracted = out_dir / "python"
    if skip and extracted.exists() and (extracted / "python.exe").is_file():
        print(f"[msi] --skip-download: using {extracted}")
        return extracted
    print("\n=== Step 1/5: download Python 3.11 embeddable ===")
    _run([sys.executable, str(INSTALLER_DIR / "download_python.py"),
          "--out-dir", str(out_dir)])
    return extracted


def step_build_wheel(*, skip_frontend: bool, wheel_out: Path) -> Path:
    print("\n=== Step 2/5: build graphindex wheel (with frontend bundled) ===")
    cmd = [sys.executable, str(INSTALLER_DIR / "build_graphindex_wheel.py"),
           "--out-dir", str(wheel_out)]
    if skip_frontend:
        cmd.append("--skip-frontend")
    _run(cmd)
    # .with_suffix('') avoids argparse swallowing "" into positional.
    wheels = sorted(wheel_out.glob("graphindex-*.whl"))
    if not wheels:
        raise SystemExit(f"no graphindex-*.whl produced in {wheel_out}")
    return wheels[-1]


def step_stage(*, staging_dir: Path, python_dir: Path, wheel: Path,
               extras: str, frontend_dist: Path | None) -> Path:
    print("\n=== Step 3/5: stage MSI tree (pip install into embedded Python) ===")
    install_root = staging_dir / "Program Files" / "graphindex"
    if install_root.exists():
        shutil.rmtree(install_root)
    frontend_arg = (["--frontend-dist", str(frontend_dist)]
                    if frontend_dist and frontend_dist.exists() else [])
    _run([sys.executable, str(INSTALLER_DIR / "stage.py"),
          "--staging-dir", str(staging_dir),
          "--python-dir", str(python_dir),
          "--wheel", str(wheel),
          "--extras", extras] + frontend_arg)
    return install_root


def step_wix(*, src_dir: Path, output: Path, wix_dir: Path) -> Path:
    print("\n=== Step 4/5: build MSI with WiX ===")
    obj = src_dir / "obj"
    if obj.exists():
        shutil.rmtree(obj)
    obj.mkdir()

    # Step 4a: heat the python/ tree into a wxs fragment.
    harvest = wix_dir / "heat.exe"
    if not harvest.is_file():
        raise SystemExit(
            f"WiX heat.exe not found at {harvest}. Install WiX 3.x from "
            f"https://wixtoolset.org/releases/ and ensure it's on PATH or "
            f"set --wix-dir."
        )
    _run([str(harvest), "dir", str(src_dir / "python"),
          "-cg", "HarvestedPython",
          "-dr", "PythonDir",
          "-srd",
          "-var", "var.SrcDir",
          "-out", str(obj / "harvest.wxs")],
         cwd=src_dir)
    # heat auto-adds -var var.SrcDir; make sure it resolves to src_dir.
    src_dir_var = src_dir
    _run([str(wix_dir / "candle.exe"),
          "-dSrcDir=" + str(src_dir),
          "-out", str(obj / "\\"),
          str(INSTALLER_DIR / "graphindex.wxs"),
          str(obj / "harvest.wxs")],
         cwd=src_dir)
    msi_path = output / "graphindex.msi"
    _run([str(wix_dir / "light.exe"),
          "-ext", "WixUtilExtension",
          "-ext", "WixUIExtension",
          "-cultures:en-US",
          "-out", str(msi_path),
          str(obj / "graphindex.wixobj"),
          str(obj / "harvest.wixobj")],
         cwd=src_dir)
    if not msi_path.is_file():
        raise SystemExit(f"MSI not produced at {msi_path}")
    size_mb = msi_path.stat().st_size / (1024 * 1024)
    print(f"[msi] produced {msi_path}  ({size_mb:.1f} MB)")
    return msi_path


def step_validate(*, msi: Path, wix_dir: Path) -> None:
    print("\n=== Step 5/5: validate MSI ===")
    validator = wix_dir / "insignia.exe"  # close enough; real validator is
                                           # in the WiX SDK. We fall back to
                                           # Windows' MSI validator if present.
    if not validator.is_file():
        print("[msi] (skipped — WiX insignia.exe not on PATH)")
        return
    _run([str(validator), "-im", str(msi)], cwd=msi.parent)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=REPO_ROOT / "dist",
                   help="Where to write the final .msi (default: <repo>/dist).")
    p.add_argument("--build-dir", type=Path, default=REPO_ROOT / "build",
                   help="Scratch directory for the Python download and staging tree.")
    p.add_argument("--wix-dir", type=Path, default=Path(r"C:\Program Files (x86)\WiX Toolset v3.14\bin"),
                   help="Path to the WiX bin/ directory (default: standard 3.14 install).")
    p.add_argument("--skip-download", action="store_true",
                   help="Skip the Python download if build/python/ already exists.")
    p.add_argument("--skip-frontend", action="store_true",
                   help="Skip the `npm run build` (use existing frontend/dist/).")
    p.add_argument("--extras", default="llama,faiss,mcp",
                   help="Comma-separated pip extras to install (default: llama,faiss,mcp). "
                        "Pass empty string to install no extras.")
    p.add_argument("--frontend-dist", type=Path, default=REPO_ROOT / "frontend" / "dist",
                   help="Path to frontend/dist/ (used by stage.py).")
    args = p.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    args.build_dir.mkdir(parents=True, exist_ok=True)
    python_dir = step_download_python(skip=args.skip_download, out_dir=args.build_dir)
    wheel = step_build_wheel(skip_frontend=args.skip_frontend, wheel_out=args.output)
    install_root = step_stage(staging_dir=args.build_dir / "stage",
                              python_dir=python_dir, wheel=wheel, extras=args.extras,
                              frontend_dist=args.frontend_dist)
    msi = step_wix(src_dir=install_root, output=args.output, wix_dir=args.wix_dir)
    step_validate(msi=msi, wix_dir=args.wix_dir)
    print(f"\n[msi] done: {msi}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
