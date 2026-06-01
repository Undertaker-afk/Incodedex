"""Assemble the MSI staging tree under ``<staging>/``.

Layout (everything goes under ``<staging>/Program Files/graphindex/``):

    python/                        — extracted Python 3.11 embeddable
        python.exe
        python311.dll
        python311.zip
        ...
        Lib/                      — site-packages after `pip install`
        Scripts/graphindex.exe    — console-script entry point
        graphindex.pth            — adds Lib/site-packages to sys.path
        LICENSE.txt
    frontend_dist/                 — React SPA (copied from wheel; not strictly
                                     needed here because the wheel ships it,
                                     but a sibling copy makes the install self
                                     documenting and lets WiX advertise it)
    LICENSE.txt
    graphindex.bat                 — PATH shim (delegates to python/graphindex.exe)
    graphindex-mcp.json            — example MCP client config (Claude Desktop etc.)

The WiX source (``graphindex.wxs``) references this directory tree. After
WiX builds the MSI, the user runs it and gets:

    C:\\Program Files\\graphindex\\
        python\\python.exe
        python\\Scripts\\graphindex.exe
        graphindex.bat           <-- on PATH (Start Menu shortcut added too)
        LICENSE.txt

Adding ``C:\\Program Files\\graphindex`` to the user's ``PATH`` is handled
by the WiX ``<Property Id="WixShellExec"...>`` custom action at install
end, then ``graphindex`` works from any new cmd / PowerShell.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _patch_python_pth(python_dir: Path) -> None:
    """Enable site-packages in the embeddable's ``python311._pth``.

    The Python 3.11 embeddable ships with ``#import site`` commented out,
    which means pip (and everything else) installed into ``Lib\\site-packages``
    is invisible. Uncomment it and add ``Lib\\site-packages`` as an extra
    path entry. Don't touch the existing entries (python311.zip, ``.``,
    python3x.zip) — removing them breaks stdlib discovery.
    """
    pth = python_dir / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    if not pth.exists():
        print(f"[stage] (no {pth.name} found; skipping _pth patch)")
        return
    original = pth.read_text(encoding="utf-8")
    lines = original.splitlines()

    # 1) uncomment `#import site` / `# import site`
    new_lines: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("#") and "import site" in stripped:
            # uncomment
            new_lines.append(stripped.lstrip("#").strip())
        else:
            new_lines.append(ln)

    # 2) ensure `Lib\site-packages` is listed
    have_sitepkgs = any(l.strip().lower().replace("\\", "/") == "lib/site-packages"
                        for l in new_lines)
    if not have_sitepkgs:
        new_lines.append("Lib\\site-packages")

    new_text = "\n".join(new_lines) + ("\n" if not new_lines[-1].endswith("\n") else "")
    if new_text != original:
        print(f"[stage] patching {pth.name} (enable site-packages)")
        pth.write_text(new_text, encoding="utf-8")


def stage_python(*, src_dir: Path, dst_dir: Path) -> None:
    """Copy the extracted embeddable Python into the staging tree."""
    if not (src_dir / "python.exe").is_file():
        raise SystemExit(
            f"{src_dir} doesn't look like an extracted Python embeddable "
            f"(no python.exe). Run download_python.py first."
        )
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    print(f"[stage] python: {src_dir} -> {dst_dir}")
    shutil.copytree(src_dir, dst_dir)
    _patch_python_pth(dst_dir)


def install_graphindex_into_python(
    *, python_exe: Path, wheel: Path, extra_extras: list[str]
) -> None:
    """``pip install`` the graphindex wheel (and extras) into the embeddable.

    The Python 3.11 embeddable distribution does NOT include ``ensurepip``,
    so we bootstrap pip by downloading the official ``get-pip.py`` and
    invoking it. The wheel itself is a local file so the rest of the
    install is offline.
    """
    import urllib.request
    import tempfile

    # Step 1: bootstrap pip via get-pip.py.
    with tempfile.TemporaryDirectory() as td:
        get_pip = Path(td) / "get-pip.py"
        print(f"[stage] downloading get-pip.py to bootstrap pip…")
        urllib.request.urlretrieve(
            "https://bootstrap.pypa.io/get-pip.py", get_pip)
        print(f"[stage] installing pip into {python_exe}")
        subprocess.run(
            [str(python_exe), str(get_pip), "--no-warn-script-location",
             "--disable-pip-version-check"],
            check=True,
        )

    # Step 2: install the wheel. Extras come from the wheel's own metadata
    # (pyproject.toml), so we use the [extras] form.
    extras = ",".join(extra_extras) if extra_extras else ""
    spec = f"{wheel}[{extras}]" if extras else str(wheel)
    print(f"[stage] pip install {spec}")
    subprocess.run(
        [str(python_exe), "-m", "pip", "install", "--no-warn-script-location",
         "--disable-pip-version-check", spec],
        check=True,
    )


def write_shim(*, shim_path: Path, python_dir: Path) -> None:
    """Write a `graphindex.bat` that delegates to ``python\\Scripts\\graphindex.exe``."""
    content = (
        '@echo off\r\n'
        # %~dp0 = directory of this .bat
        f'"{python_dir.name}\\python.exe" "%~dp0{python_dir.name}\\Scripts\\graphindex.exe" %*\r\n'
    )
    print(f"[stage] writing {shim_path}")
    shim_path.write_text(content, encoding="utf-8")


def copy_extra(*, src: Path, dst: Path, label: str) -> None:
    print(f"[stage] {label}: {src} -> {dst}")
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--staging-dir", type=Path, required=True,
                   help="Output staging directory (will be created).")
    p.add_argument("--python-dir", type=Path, required=True,
                   help="Directory containing the extracted Python embeddable.")
    p.add_argument("--wheel", type=Path, required=True,
                   help="graphindex .whl to install into the embedded Python.")
    p.add_argument("--extras", default="llama,faiss,mcp",
                   help="Comma-separated pip extras to install (default: llama,faiss,mcp). "
                        "Pass an empty string after '=' like --extras= to install no extras.")
    p.add_argument("--frontend-dist", type=Path, default=None,
                   help="Optional path to frontend/dist/ to copy alongside python/.")
    args = p.parse_args()

    staging = args.staging_dir
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    install_root = staging / "Program Files" / "graphindex"
    install_root.mkdir(parents=True)
    python_dir = install_root / "python"
    stage_python(src_dir=args.python_dir, dst_dir=python_dir)
    install_graphindex_into_python(
        python_exe=python_dir / "python.exe",
        wheel=args.wheel,
        extra_extras=[e.strip() for e in args.extras.split(",") if e.strip()],
    )
    write_shim(shim_path=install_root / "graphindex.bat", python_dir=python_dir)

    if args.frontend_dist and args.frontend_dist.exists():
        copy_extra(
            src=args.frontend_dist,
            dst=install_root / "frontend_dist",
            label="frontend_dist",
        )

    # License (from the repo root, if present) — required for a professional
    # installer and the WiX ARPHELPLINK/ARPCOMMENTS props below.
    for license_name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        lic = REPO_ROOT / license_name
        if lic.exists():
            copy_extra(src=lic, dst=install_root / "LICENSE.txt", label="LICENSE")
            break

    print(f"\n[stage] done. Staging tree at: {install_root}")
    print("[stage] tree:")
    for p in sorted(install_root.rglob("*")):
        rel = p.relative_to(install_root)
        size = p.stat().st_size if p.is_file() else 0
        marker = "/" if p.is_dir() else ""
        print(f"  {rel}{marker}  ({size // 1024} KB)" if p.is_file() else f"  {rel}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
