"""Embedder interface."""

from __future__ import annotations

import abc

import numpy as np


class Embedder(abc.ABC):
    name: str = "embedder"
    dim: int = 0

    @abc.abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) float32 matrix for ``texts``."""

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def available(self) -> bool:  # pragma: no cover - overridden where relevant
        return True
