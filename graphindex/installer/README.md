# graphindex Windows MSI installer

This directory builds a Windows `.msi` that installs graphindex end-to-end:
self-contained Python 3.11, the graphindex wheel with the real LLM stack
(`[llama,faiss,mcp]` extras), the built React SPA, and a `graphindex` shim
on the system `PATH` so the user can `cd` into any repo and type
`graphindex index .` from a fresh `cmd`.

## End-user install

After the MSI is produced (typically by a CI release), the user:

1. Double-clicks `graphindex-0.1.0.msi` (admin required for per-machine install).
2. Accepts the UAC prompt.
3. Clicks through WiX's minimal UI (license, install dir, confirm).
4. Opens a new `cmd` or `PowerShell` (must be new — old shells still have
   the old `PATH`), `cd` into their codebase, and runs:

    ```
    graphindex setup .
    graphindex index .
    graphindex serve . --watch
    ```

5. Opens <http://localhost:8000/> for the WebUI.

`graphindex setup` is the only step that needs internet — it downloads
the ~1.2 GB of GGUF models to `%LOCALAPPDATA%\graphindex\models\`.

## Building the MSI

### Prerequisites (build machine only)

| Tool | Version | Why |
|------|---------|-----|
| Python | 3.10-3.12 | Runs the build scripts and `npm`/`build` orchestration. |
| Node.js | ≥ 18 | Builds the React SPA (`npm run build`). |
| WiX Toolset | 3.14+ | Compiles `graphindex.wxs` into the `.msi`. |
| .NET Framework | 4.5+ | WiX runtime. Pre-installed on Windows 10+. |

Install WiX from <https://wixtoolset.org/releases/>. The default path
the orchestrator looks for is
`C:\Program Files (x86)\WiX Toolset v3.14\bin\`; override with
`--wix-dir PATH` if you installed it elsewhere.

### One-command build

From the repo root:

```powershell
python -m installer.build_msi
```

That's it. The full pipeline runs end-to-end:

1. `download_python.py`    — fetches Python 3.11.9 embeddable (~10 MB)
                              into `build/python/`.
2. `build_graphindex_wheel.py` — `npm ci && npm run build` in
                              `frontend/`, mirrors `frontend/dist/` into
                              `graphindex/frontend_dist/`, then
                              `python -m build --wheel` writes
                              `dist/graphindex-0.1.0-*.whl`.
3. `stage.py`               — extracts the embeddable into the staging
                              tree, `pip install` the wheel **with**
                              `[llama,faiss,mcp]` extras into the embedded
                              Python, drops a `graphindex.bat` shim and a
                              `LICENSE.txt`.
4. WiX `heat dir`          — harvests the embedded `python/` tree into
                              a WiX fragment.
5. WiX `candle` + `light`  — compiles `installer/graphindex.wxs` and
                              the harvest fragment into
                              `dist/graphindex.msi`.

The final MSI is `dist/graphindex.msi` (typically 250-400 MB — the
llama-cpp-python wheel, transformers, etc. add up; the GGUF models are
NOT bundled, they download on first `graphindex setup`).

### Knobs

```powershell
# Skip the npm build (use existing frontend/dist):
python -m installer.build_msi --skip-frontend

# Skip the Python download (use build/python/ from a previous run):
python -m installer.build_msi --skip-download

# Don't bundle the LLM extras (smaller MSI, but the user gets the
# fallback backend only and must `pip install llama-cpp-python` later):
python -m installer.build_msi --extras ""

# Use a non-default WiX install:
python -m installer.build_msi --wix-dir "D:\tools\wix314\bin"
```

### Testing the MSI

```powershell
# Install silently (no UI), all users, default install dir
msiexec /i dist\graphindex.msi /qn /l*v install.log

# Verify the command works from a new shell
cmd /c "where graphindex && graphindex --version"

# Uninstall cleanly
msiexec /x dist\graphindex.msi /qn
```

### CI release workflow

A minimal GitHub Actions job (Windows runner):

```yaml
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
  with: { python-version: "3.11" }
- uses: actions/setup-node@v4
  with: { node-version: "20" }
- run: choco install wixtoolset --version=3.14.0
- run: python -m installer.build_msi
- uses: actions/upload-artifact@v4
  with:
    name: graphindex-msi
    path: dist/graphindex.msi
```

The artifact `graphindex-msi` is what users download.

The full production workflow is at
`.github/workflows/build-msi.yml`. It runs on:

| Trigger | Behavior |
|---------|----------|
| `push` to `main` | Build the MSI, upload as artifact (no release). |
| `push` of `v*` tag | Build the MSI, upload as artifact **and** attach to a GitHub Release for that tag. |
| `pull_request` to `main` | Build the MSI to validate the pipeline (artifact download, no release). |
| Manual `workflow_dispatch` | Build with a custom `--extras` value, default `llama,faiss,mcp`. |

A pre-release flag is auto-set for tags containing `-rc`, `-beta`, or
`-alpha` so the GitHub Release is marked as pre-release.

## What ships where in the install

```
C:\Program Files\graphindex\
  graphindex.bat                    on PATH
  python\
    python.exe                      3.11.9
    python311.dll
    python311.zip
    Lib\site-packages\graphindex\   the wheel's payload
        ...all deps from [llama,faiss,mcp]...
        cli.py
        api\
        frontend_dist\              React SPA (served by Flask)
    Scripts\graphindex.exe          console-script shim
  frontend_dist\                    copy of the SPA (for self-documentation
                                    and so the user can find it in Explorer)
  LICENSE.txt
```

`graphindex` model files (downloaded by `graphindex setup`):
`%LOCALAPPDATA%\graphindex\models\` — **not** wiped by uninstaller.

`graphindex` indexes (per repo): `<repo>\.graphindex\` — also not wiped
by uninstaller, since the user wants their indexes to survive an upgrade.
