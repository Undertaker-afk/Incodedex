"""Deterministic, dependency-free embedding fallback.

Produces stable vectors via hashed bag-of-tokens plus character trigrams, with
sublinear term weighting and L2 normalization. This is not a learned model, but
it is deterministic and gives meaningful cosine similarity for code/text that
shares tokens — enough to exercise and test the full semantic-search pipeline
when the llama.cpp Qwen3 model is unavailable.
"""

from __future__ import annotations

import hashlib
import math
import re

import numpy as np

from .base import Embedder

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")


def _hash(token: str, dim: int) -> int:
    h = hashlib.md5(token.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "little") % dim


def _trigrams(token: str):
    t = f"#{token}#"
    for i in range(len(t) - 2):
        yield t[i:i + 3]


class HashingEmbedder(Embedder):
    name = "fallback-hashing"

    def __init__(self, dim: int = 512):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        mat = np.zeros((len(texts), self.dim), dtype="float32")
        for row, text in enumerate(texts):
            counts: dict[int, float] = {}
            tokens = _TOKEN.findall(text.lower())
            for tok in tokens:
                counts[_hash(tok, self.dim)] = counts.get(_hash(tok, self.dim), 0) + 1.0
                for tri in _trigrams(tok):
                    idx = _hash("3" + tri, self.dim)
                    counts[idx] = counts.get(idx, 0) + 0.3
            for idx, c in counts.items():
                mat[row, idx] = 1.0 + math.log(c)
            norm = np.linalg.norm(mat[row])
            if norm:
                mat[row] /= norm
        return mat
