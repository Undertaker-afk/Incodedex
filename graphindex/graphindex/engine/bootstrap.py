"""Autoinstall for the embedded llama.cpp runtime + GGUF model download.

``llama-cpp-python`` embeds llama.cpp directly into the Python process. We
prefer the project's prebuilt CPU wheels (no compiler needed); if those are not
reachable we fall back to a normal source build. GGUF weights are pulled from
the Hugging Face hub on first use and cached under ``config.models_dir``.

Every function here is best-effort and returns a status rather than raising,
so the pipeline can gracefully degrade to the deterministic fallback backend.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

from ..config import Config, ModelSpec
from .registry import find_existing, local_model_path

# Prebuilt CPU wheels published by the llama-cpp-python project.
_CPU_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/cpu"


def llama_installed() -> bool:
    try:
        importlib.import_module("llama_cpp")
        return True
    except Exception:
        return False


def install_llama(quiet: bool = True) -> bool:
    """Install ``llama-cpp-python`` (prebuilt wheel first, then source)."""
    if llama_installed():
        return True
    attempts = [
        [sys.executable, "-m", "pip", "install", "--extra-index-url",
         _CPU_WHEEL_INDEX, "llama-cpp-python"],
        [sys.executable, "-m", "pip", "install", "llama-cpp-python"],
    ]
    for cmd in attempts:
        if quiet:
            cmd.insert(4, "--quiet")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if res.returncode == 0 and llama_installed():
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return llama_installed()


def download_model(cfg: Config, spec: ModelSpec) -> Path | None:
    """Ensure ``spec``'s GGUF is on disk; download from HF if missing."""
    existing = find_existing(cfg.models_dir, spec)
    if existing:
        return existing
    if not cfg.auto_download:
        return None
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return None
    target_dir = local_model_path(cfg.models_dir, spec).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = hf_hub_download(
            repo_id=spec.repo_id, filename=spec.filename,
            local_dir=str(target_dir),
        )
        return Path(path)
    except Exception:
        # Try to discover an available GGUF in the repo (different quant).
        try:
            from huggingface_hub import list_repo_files
            files = list_repo_files(spec.repo_id)
            ggufs = [f for f in files if f.endswith(".gguf")]
            if ggufs:
                path = hf_hub_download(repo_id=spec.repo_id, filename=ggufs[0],
                                       local_dir=str(target_dir))
                return Path(path)
        except Exception:
            return None
    return None


def ensure_engine(cfg: Config) -> dict:
    """Best-effort: install runtime + download both models. Returns a status."""
    status = {"llama_installed": llama_installed(), "embed_model": None,
              "chat_model": None, "installed_now": False}
    if not status["llama_installed"] and cfg.auto_install:
        status["installed_now"] = install_llama()
        status["llama_installed"] = llama_installed()
    embed = download_model(cfg, cfg.embed_model)
    chat = download_model(cfg, cfg.chat_model)
    status["embed_model"] = str(embed) if embed else None
    status["chat_model"] = str(chat) if chat else None
    return status
