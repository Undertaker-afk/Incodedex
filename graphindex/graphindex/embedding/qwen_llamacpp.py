"""Qwen3-Embedding-0.6B embedder backed by the in-process llama.cpp engine."""

from __future__ import annotations

import numpy as np

from ..config import Config
from ..engine.llama_engine import EngineUnavailable, LlamaEngine
from .base import Embedder


class QwenEmbedder(Embedder):
    name = "qwen3-embedding-0.6b"

    def __init__(self, cfg: Config, engine: LlamaEngine | None = None):
        self.cfg = cfg
        self.engine = engine or LlamaEngine(cfg)
        self.dim = cfg.embed_dim

    def available(self) -> bool:
        # Side-effect free: do not trigger a download here.
        if not LlamaEngine.runtime_available():
            return False
        return self.engine.local_embed_model() is not None

    def embed(self, texts: list[str]) -> np.ndarray:
        try:
            mat = self.engine.embed(texts)
        except EngineUnavailable as exc:  # pragma: no cover - defensive
            raise RuntimeError(str(exc)) from exc
        self.dim = mat.shape[1]
        return mat.astype("float32")
