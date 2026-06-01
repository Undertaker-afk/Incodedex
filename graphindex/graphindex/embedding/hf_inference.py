"""Embedder backed by huggingface_hub InferenceClient (feature_extraction)."""

from __future__ import annotations

import numpy as np

from ..config import Config
from ..engine.hf_client import HFInferenceEngine
from .base import Embedder


class HFEmbedder(Embedder):
    name = "hf-inference-feature-extraction"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.engine = HFInferenceEngine(cfg)
        self.dim = cfg.embed_dim

    def available(self) -> bool:
        return self.engine.available()

    def embed(self, texts: list[str]) -> np.ndarray:
        mat = self.engine.embed(texts).astype("float32")
        self.dim = mat.shape[1]
        return mat
