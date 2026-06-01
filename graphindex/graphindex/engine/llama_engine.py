"""In-process llama.cpp engine wrapping ``llama-cpp-python``.

Loads the embedding model (Qwen3-Embedding-0.6B) and the chat model
(LFM2.5-1.2B-Instruct) as GGUFs and exposes ``embed`` / ``chat``. Both models
are loaded lazily so importing this module is cheap and the rest of the system
works without the heavy runtime present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..config import Config
from . import bootstrap
from .registry import find_existing


class EngineUnavailable(RuntimeError):
    """Raised when the llama.cpp runtime or required GGUFs are missing."""


class LlamaEngine:
    def __init__(self, cfg: Config, auto: bool = False):
        self.cfg = cfg
        self._embed_model: Any | None = None
        self._chat_model: Any | None = None
        self._embed_dim: int | None = None
        # Heavy installs/downloads only happen when explicitly requested
        # (auto=True), never as an implicit side effect of "auto" backend.
        if auto and cfg.auto_install and not bootstrap.llama_installed():
            bootstrap.install_llama()

    def local_embed_model(self) -> Path | None:
        """Locate an already-downloaded embedding GGUF without downloading."""
        return find_existing(self.cfg.models_dir, self.cfg.embed_model)

    def local_chat_model(self) -> Path | None:
        """Locate an already-downloaded chat GGUF without downloading."""
        return find_existing(self.cfg.models_dir, self.cfg.chat_model)

    # -- availability -----------------------------------------------------
    @staticmethod
    def runtime_available() -> bool:
        return bootstrap.llama_installed()

    def embed_model_path(self) -> Path | None:
        path = find_existing(self.cfg.models_dir, self.cfg.embed_model)
        if path is None and self.cfg.auto_download:
            path = bootstrap.download_model(self.cfg, self.cfg.embed_model)
        return path

    def chat_model_path(self) -> Path | None:
        path = find_existing(self.cfg.models_dir, self.cfg.chat_model)
        if path is None and self.cfg.auto_download:
            path = bootstrap.download_model(self.cfg, self.cfg.chat_model)
        return path

    # -- lazy loaders -----------------------------------------------------
    def _load_embed(self) -> Any:
        if self._embed_model is not None:
            return self._embed_model
        if not bootstrap.llama_installed():
            raise EngineUnavailable("llama-cpp-python not installed")
        path = self.embed_model_path()
        if path is None:
            raise EngineUnavailable("embedding GGUF not available")
        from llama_cpp import Llama, LLAMA_POOLING_TYPE_LAST
        self._embed_model = Llama(
            model_path=str(path), embedding=True, n_ctx=2048, n_batch=512,
            n_threads=self.cfg.n_threads, n_threads_batch=self.cfg.n_threads_batch,
            pooling_type=LLAMA_POOLING_TYPE_LAST, verbose=False,
        )
        return self._embed_model

    def _load_chat(self) -> Any:
        if self._chat_model is not None:
            return self._chat_model
        if not bootstrap.llama_installed():
            raise EngineUnavailable("llama-cpp-python not installed")
        path = self.chat_model_path()
        if path is None:
            raise EngineUnavailable("chat GGUF not available")
        from llama_cpp import Llama
        self._chat_model = Llama(
            model_path=str(path), n_ctx=4096, n_threads=self.cfg.n_threads,
            n_threads_batch=self.cfg.n_threads_batch, verbose=False,
        )
        return self._chat_model

    # -- inference --------------------------------------------------------
    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._load_embed()
        out = model.create_embedding(texts)
        vecs = [np.asarray(item["embedding"], dtype="float32")
                for item in out["data"]]
        # Some builds return token-level embeddings (2D); mean-pool them.
        pooled = []
        for v in vecs:
            if v.ndim == 2:
                v = v.mean(axis=0)
            pooled.append(v.astype("float32"))
        mat = np.vstack(pooled)
        self._embed_dim = mat.shape[1]
        return mat

    @property
    def embed_dim(self) -> int:
        if self._embed_dim is None:
            try:
                self.embed(["dimension probe"])
            except EngineUnavailable:
                return self.cfg.embed_dim
        return self._embed_dim or self.cfg.embed_dim

    def chat(self, system: str, user: str, max_tokens: int = 128,
             temperature: float = 0.2) -> str:
        model = self._load_chat()
        out = model.create_chat_completion(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=temperature,
        )
        return out["choices"][0]["message"]["content"].strip()
