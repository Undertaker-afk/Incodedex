"""Embedding backends (Qwen3 via llama.cpp, deterministic fallback)."""

from __future__ import annotations

from ..config import Config
from .base import Embedder
from .fallback import HashingEmbedder


def get_embedder(cfg: Config, engine=None) -> Embedder:
    """Pick the embedding backend per config.

    ``auto`` uses the llama.cpp Qwen3 embedder when the runtime + GGUF are
    available, otherwise the deterministic hashing fallback so the pipeline
    always runs.
    """
    backend = cfg.backend
    if backend == "hf":
        from .hf_inference import HFEmbedder
        return HFEmbedder(cfg)
    if backend in ("auto", "llamacpp"):
        try:
            from .qwen_llamacpp import QwenEmbedder
            emb = QwenEmbedder(cfg, engine=engine)
            if emb.available():
                return emb
            if backend == "llamacpp":
                # explicitly requested but unavailable -> still return it so the
                # error surfaces on first use rather than silently degrading
                return emb
        except Exception:
            if backend == "llamacpp":
                raise
    return HashingEmbedder(cfg.embed_dim)
