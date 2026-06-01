"""Resolves which GGUF files to use and where they live on disk."""

from __future__ import annotations

from pathlib import Path

from ..config import ModelSpec


def local_model_path(models_dir: Path, spec: ModelSpec) -> Path:
    """Expected on-disk location for a model's GGUF file."""
    return models_dir / spec.repo_id.replace("/", "__") / spec.filename


def find_existing(models_dir: Path, spec: ModelSpec) -> Path | None:
    """Return a local GGUF for ``spec`` if one is already present.

    Tries the exact filename first, then any ``*.gguf`` under the model's
    cache directory (so a different quantization still works).
    """
    exact = local_model_path(models_dir, spec)
    if exact.exists():
        return exact
    cache_dir = models_dir / spec.repo_id.replace("/", "__")
    if cache_dir.exists():
        ggufs = sorted(cache_dir.glob("*.gguf"))
        if ggufs:
            return ggufs[0]
    return None
