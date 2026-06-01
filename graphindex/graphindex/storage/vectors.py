"""Vector store for semantic search.

Uses FAISS (``IndexFlatIP`` over L2-normalized vectors == cosine similarity)
when available, and transparently falls back to a pure-NumPy brute-force index
so the system works even where FAISS cannot be installed. Vectors and their id
mapping are persisted to ``vectors_path`` and reloaded on startup.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:  # optional acceleration
    import faiss  # type: ignore

    _HAS_FAISS = True
except Exception:  # pragma: no cover - faiss not installed
    faiss = None  # type: ignore
    _HAS_FAISS = False


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class VectorStore:
    def __init__(self, path: str | Path, dim: int):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self.ids: list[str] = []
        self._id_set: set[str] = set()
        self._matrix: np.ndarray = np.zeros((0, dim), dtype="float32")
        self._index = faiss.IndexFlatIP(dim) if _HAS_FAISS else None
        self.backend = "faiss" if _HAS_FAISS else "numpy"
        self._load()

    # -- persistence ------------------------------------------------------
    @property
    def _ids_file(self) -> Path:
        return self.path / "ids.json"

    @property
    def _vec_file(self) -> Path:
        return self.path / "vectors.npy"

    def _load(self) -> None:
        if self._ids_file.exists() and self._vec_file.exists():
            try:
                self.ids = json.loads(self._ids_file.read_text())
                self._id_set = set(self.ids)
                mat = np.load(self._vec_file)
                if mat.shape[1] != self.dim and mat.size:
                    return  # dimension mismatch -> start fresh
                self._matrix = mat.astype("float32")
                if self._index is not None and len(self.ids):
                    self._index.add(self._matrix)
            except Exception:
                self.ids, self._id_set = [], set()
                self._matrix = np.zeros((0, self.dim), dtype="float32")

    def save(self) -> None:
        self._ids_file.write_text(json.dumps(self.ids))
        np.save(self._vec_file, self._matrix)

    # -- mutation ---------------------------------------------------------
    def add(self, node_id: str, vector: np.ndarray | list[float]) -> None:
        vec = _normalize(np.asarray(vector, dtype="float32").reshape(1, -1))
        if node_id in self._id_set:
            idx = self.ids.index(node_id)
            self._matrix[idx] = vec[0]
            self._rebuild_faiss()
            return
        self.ids.append(node_id)
        self._id_set.add(node_id)
        self._matrix = np.vstack([self._matrix, vec]) if self._matrix.size else vec
        if self._index is not None:
            self._index.add(vec)

    def remove(self, node_ids: set[str]) -> None:
        if not node_ids:
            return
        keep = [i for i, nid in enumerate(self.ids) if nid not in node_ids]
        self.ids = [self.ids[i] for i in keep]
        self._id_set = set(self.ids)
        self._matrix = self._matrix[keep] if keep else np.zeros((0, self.dim), dtype="float32")
        self._rebuild_faiss()

    def _rebuild_faiss(self) -> None:
        if self._index is None:
            return
        self._index.reset()
        if len(self.ids):
            self._index.add(self._matrix)

    # -- query ------------------------------------------------------------
    def search(self, vector: np.ndarray | list[float], top_k: int = 20
               ) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        q = _normalize(np.asarray(vector, dtype="float32").reshape(1, -1))
        k = min(top_k, len(self.ids))
        if self._index is not None:
            scores, idxs = self._index.search(q, k)
            return [(self.ids[i], float(s)) for i, s in zip(idxs[0], scores[0]) if i >= 0]
        sims = (self._matrix @ q[0])
        order = np.argsort(-sims)[:k]
        return [(self.ids[i], float(sims[i])) for i in order]

    def __len__(self) -> int:
        return len(self.ids)
