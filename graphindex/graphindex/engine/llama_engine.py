"""In-process llama.cpp engine wrapping ``llama-cpp-python``.

Loads the embedding model (Qwen3-Embedding-0.6B) and the chat model
(LFM2.5-1.2B-Instruct) as GGUFs and exposes ``embed`` / ``chat``. Both models
are loaded lazily so importing this module is cheap and the rest of the system
works without the heavy runtime present.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Config
from . import bootstrap
from .registry import find_existing


# Module-level set that keeps references to all loaded llama_cpp.Llama
# instances. The library's __del__ calls llama_free which can segfault on
# Windows during interpreter shutdown (STATUS_ILLEGAL_INSTRUCTION,
# 0xc000001d) with some wheels/CPU combinations. Pinning the instances
# here prevents their refcount from reaching zero, so __del__ never runs
# and the process can exit cleanly.
_LIVE_MODELS: set = set()


def _pin(model) -> None:
    _LIVE_MODELS.add(model)


def unpin_all() -> int:
    """Drop references to pinned models. Returns the number released."""
    n = len(_LIVE_MODELS)
    _LIVE_MODELS.clear()
    return n


class EngineUnavailable(RuntimeError):
    """Raised when the llama.cpp runtime or required GGUFs are missing."""


# ---------------------------------------------------------------------------
# Custom log callback for the underlying llama.cpp C library.
#
# llama-cpp-python installs its own callback at import time that prints every
# log line to stderr. That means a benign warning like
#   "llama_context: n_ctx_seq (2048) < n_ctx_train (32768) ..."
# shows up once per ``Llama(...)`` instance we create (embed + chat) and clutters
# the output. We replace the callback with one that:
#
#   * dedupes identical messages within a process (so each warning prints at
#     most once per run);
#   * honours ``GRAPHINDEX_LLAMA_LOG`` (silent|error|warn|info|debug);
#   * drops a small built-in list of known-noisy warnings unless
#     ``GRAPHINDEX_LLAMA_LOG_SUPPRESS=0`` is set.
# ---------------------------------------------------------------------------

# GGML log levels: 0 NONE, 1 INFO, 2 WARN, 3 ERROR, 4 DEBUG, 5 CONT
# The numbering is inverted: DEBUG (4) is the most verbose, ERROR (3) is the
# most severe normal level. We map a user-friendly level name to the set of
# GGML levels that are allowed through.
_LLAMA_LEVEL_ALLOWS: dict[str, set[int]] = {
    "silent": set(),                       # nothing
    "error": {3},                          # errors only
    "warn": {2, 3},                        # + warnings
    "info": {1, 2, 3},                     # + info
    "debug": {1, 2, 3, 4},                 # + verbose debug
    "none": {3, 4},                        # alias: errors + debug (matches the
                                           # behaviour llama-cpp uses for
                                           # verbose=False on older builds)
}

# Substrings of messages that are noise on this project. We default-suppress
# them and let users opt back in with GRAPHINDEX_LLAMA_LOG_SUPPRESS=0.
_BENIGN_PATTERNS: tuple[str, ...] = (
    "n_ctx_seq (",
    "n_ctx_per_seq (",
    "llama_context: n_ctx",
)

_LLAMA_LOG_INSTALLED = False
_LLAMA_LOG_SEEN: set[str] = set()
_LLAMA_LOG_LEVEL = (
    os.environ.get("GRAPHINDEX_LLAMA_LOG", "error").strip().lower() or "error"
)
_LLAMA_LOG_ALLOWED = _LLAMA_LEVEL_ALLOWS.get(
    _LLAMA_LOG_LEVEL, _LLAMA_LEVEL_ALLOWS["error"]
)
_LLAMA_LOG_SUPPRESS_BENIGN = os.environ.get(
    "GRAPHINDEX_LLAMA_LOG_SUPPRESS", "1"
).strip().lower() not in ("", "0", "false", "no", "off")


def _llama_log_should_emit(level: int, msg: str) -> bool:
    if level not in _LLAMA_LOG_ALLOWED:
        return False
    if _LLAMA_LOG_SUPPRESS_BENIGN and any(p in msg for p in _BENIGN_PATTERNS):
        return False
    return True


def _llama_log_emit(msg: str) -> None:
    sys.stderr.write(msg)
    sys.stderr.flush()


def _llama_log_callback(level: int, text, user_data) -> None:
    if not text:
        return
    msg = text.decode("utf-8", errors="replace") if isinstance(text, (bytes, bytearray)) else str(text)
    if not _llama_log_should_emit(level, msg):
        return
    if level != 5:
        # Dedup only complete messages; multi-line continuations are fine to
        # repeat since they are the tail of an already-emitted block.
        key = hashlib.md5(msg.encode("utf-8", errors="replace")).hexdigest()
        if key in _LLAMA_LOG_SEEN:
            return
        _LLAMA_LOG_SEEN.add(key)
    _llama_log_emit(msg)


def install_llama_log_filter() -> None:
    """Install :func:`_llama_log_callback` as the global llama.cpp log handler.

    Safe to call multiple times and a no-op when ``llama_cpp`` is unavailable.
    Also silences the Python ``llama-cpp-python`` logger that the default
    callback uses, so anything that bypasses the C callback (e.g. warnings from
    the Python wrapper) is quiet too.
    """
    global _LLAMA_LOG_INSTALLED
    if _LLAMA_LOG_INSTALLED:
        return
    try:
        import llama_cpp
    except Exception:
        return
    try:
        cb = llama_cpp.llama_log_callback(_llama_log_callback)
        llama_cpp.llama_log_set(cb, ctypes.c_void_p(0))
    except Exception:
        return
    try:
        logging.getLogger("llama-cpp-python").setLevel(
            logging.CRITICAL if _LLAMA_LOG_LEVEL == "silent" else logging.ERROR
        )
    except Exception:
        pass
    _LLAMA_LOG_INSTALLED = True


# Install on import so the filter is in place before the first ``Llama(...)``
# is constructed anywhere in the process.
# install_llama_log_filter()


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
        # install_llama_log_filter()
        from llama_cpp import Llama, LLAMA_POOLING_TYPE_LAST
        self._embed_model = Llama(
            model_path=str(path), embedding=True, n_ctx=2048, n_batch=512,
            n_threads=self.cfg.n_threads, n_threads_batch=self.cfg.n_threads_batch,
            pooling_type=LLAMA_POOLING_TYPE_LAST, verbose=False,
        )
        _pin(self._embed_model)
        return self._embed_model

    def _load_chat(self) -> Any:
        if self._chat_model is not None:
            return self._chat_model
        if not bootstrap.llama_installed():
            raise EngineUnavailable("llama-cpp-python not installed")
        path = self.chat_model_path()
        if path is None:
            raise EngineUnavailable("chat GGUF not available")
        # install_llama_log_filter()
        from llama_cpp import Llama
        self._chat_model = Llama(
            model_path=str(path), n_ctx=4096, n_threads=self.cfg.n_threads,
            n_threads_batch=self.cfg.n_threads_batch, verbose=False,
        )
        _pin(self._chat_model)
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
