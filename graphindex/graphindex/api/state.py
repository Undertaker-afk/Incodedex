"""Shared server state: DB, vectors, embedder, search engine, event bus.

Holds the singletons the API/sockets operate on and (re)builds the read-side
components after an index run so freshly indexed data is served immediately.
"""

from __future__ import annotations

import threading

from ..config import Config
from ..embedding import get_embedder
from ..pipeline.events import EventBus
from ..qa import AskEngine, ExtendedAsk, get_chat
from ..search import SearchEngine
from ..storage.db import GraphDB
from ..storage.vectors import VectorStore
from ..storage.compsrc import CompSrc


class AppState:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.ensure_dirs()
        self.bus = EventBus()
        self.index_lock = threading.Lock()
        self.ask_lock = threading.Lock()
        # Guards the ``reload`` swap so in-flight request threads (which read
        # ``self.db``/``self.vectors``) never see a half-rebuilt state.
        self._reload_lock = threading.Lock()
        self.indexing = False
        self.asking = False
        self.watcher = None
        self.last_extended = None
        self.compsrc = CompSrc(cfg.repo_path)
        self._open()

    def _build(self):
        """Construct a fresh set of read-side components. Pure: no self mutation."""
        db = GraphDB(self.cfg.db_path)
        dim = db.get_meta("embed_dim", self.cfg.embed_dim) or self.cfg.embed_dim
        vectors = VectorStore(self.cfg.vectors_path, dim)
        embedder = get_embedder(self.cfg)
        search_engine = SearchEngine(db, vectors, embedder)
        chat = get_chat(self.cfg)
        ask_engine = AskEngine(self.cfg, db, vectors, embedder, chat=chat)
        return db, vectors, embedder, search_engine, chat, ask_engine

    def _open(self) -> None:
        (self.db, self.vectors, self.embedder, self.search_engine,
         self.chat, self.ask_engine) = self._build()

    def build_extended(self, opts: dict, bus) -> ExtendedAsk:
        """Construct an ExtendedAsk orchestrator with caps from the request."""
        return ExtendedAsk(
            self.cfg, self.db, self.vectors, self.embedder, chat=self.chat, bus=bus,
            keyword_rounds=int(opts.get("keyword_rounds", 2)),
            keywords_per_round=int(opts.get("keywords_per_round", 4)),
            agents_per_round=int(opts.get("agents_per_round", 3)),
            max_rounds=int(opts.get("max_rounds", 10)),
        )

    def reload(self) -> None:
        """Re-open read components after an index run.

        Builds the new components first, then atomically swaps the public
        attributes and closes the *old* DB last. This way an in-flight request
        thread that already captured ``self.db`` keeps a valid connection until
        it finishes; new requests pick up the fresh state.
        """
        with self._reload_lock:
            try:
                new = self._build()
            except Exception:
                # If rebuild fails, keep the current state intact rather than
                # leaving the server with a closed/missing DB.
                raise
            old_db = self.db
            (self.db, self.vectors, self.embedder, self.search_engine,
             self.chat, self.ask_engine) = new
        # Delay closing the old connection so any concurrent read has a chance
        # to finish. SQLite connections are cheap; this is a best-effort grace
        # period rather than a hard sync point.
        try:
            threading.Timer(2.0, lambda: _safe_close(old_db)).start()
        except Exception:
            _safe_close(old_db)


def _safe_close(db) -> None:
    try:
        db.close()
    except Exception:
        pass
