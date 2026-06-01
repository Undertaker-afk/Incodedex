"""Shared server state: DB, vectors, embedder, search engine, event bus.

Holds the singletons the API/sockets operate on and (re)builds the read-side
components after an index run so freshly indexed data is served immediately.
"""

from __future__ import annotations

import threading

from ..config import Config
from ..embedding import get_embedder
from ..pipeline.events import EventBus
from ..qa import AskEngine, get_chat
from ..search import SearchEngine
from ..storage.db import GraphDB
from ..storage.vectors import VectorStore


class AppState:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.ensure_dirs()
        self.bus = EventBus()
        self.index_lock = threading.Lock()
        self.indexing = False
        self.watcher = None
        self._open()

    def _open(self) -> None:
        self.db = GraphDB(self.cfg.db_path)
        dim = self.db.get_meta("embed_dim", self.cfg.embed_dim) or self.cfg.embed_dim
        self.vectors = VectorStore(self.cfg.vectors_path, dim)
        # Embedder for query-time semantic search (lazy/real or fallback).
        self.embedder = get_embedder(self.cfg)
        self.search_engine = SearchEngine(self.db, self.vectors, self.embedder)
        # Chat model is loaded lazily on first ask; building the engine is cheap.
        self.ask_engine = AskEngine(self.cfg, self.db, self.vectors,
                                    self.embedder, chat=get_chat(self.cfg))

    def reload(self) -> None:
        """Re-open read components (call after an index run completes)."""
        try:
            self.db.close()
        except Exception:
            pass
        self._open()
