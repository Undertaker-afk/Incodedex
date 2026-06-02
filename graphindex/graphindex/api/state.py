"""Shared server state: DB, vectors, embedder, search engine, event bus.

Holds the singletons the API/sockets operate on and (re)builds the read-side
components after an index run so freshly indexed data is served immediately.

The read-side components (db / vectors / embedder / search_engine / chat /
ask_engine) are exposed as a single immutable snapshot
(:class:`_ReadState`), referenced atomically by ``self._state``. Public
attributes ``db``, ``vectors``, ... proxy to the current snapshot via
``__getattr__``, so a request thread that captured one of them at the start
of a request keeps using a consistent set even if :meth:`reload` swaps in a
new snapshot mid-request.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..embedding import get_embedder
from ..pipeline.events import EventBus
from ..qa import AskEngine, ExtendedAsk, get_chat
from ..search import SearchEngine
from ..storage.db import GraphDB
from ..storage.vectors import VectorStore
from ..storage.compsrc import CompSrc


@dataclass(frozen=True)
class _ReadState:
    """Immutable bundle of read-side components built together."""
    db: GraphDB
    vectors: VectorStore
    embedder: Any
    search_engine: SearchEngine
    chat: Any
    ask_engine: AskEngine


class AppState:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.ensure_dirs()
        self.bus = EventBus()
        self.index_lock = threading.Lock()
        self.ask_lock = threading.Lock()
        # Guards the *swap* of self._state (writer-side only). Readers do not
        # take this lock; they capture self._state into a local snapshot
        # (which is just a pointer assignment — atomic under the GIL).
        self._reload_lock = threading.Lock()
        self.indexing = False
        self.asking = False
        self.watcher = None
        self.last_extended = None
        self.compsrc = CompSrc(cfg.repo_path)
        self._state: _ReadState = self._build()

    # ---- public attribute proxy ------------------------------------------
    def __getattr__(self, name: str) -> Any:
        # Only invoked for attributes not found on the instance — i.e. the
        # read-side fields, which live on the current snapshot. Note: each
        # access reads the *current* snapshot. Callers that need a consistent
        # view across multiple fields should call :meth:`snapshot` once.
        if name in _ReadState.__dataclass_fields__:
            return getattr(self._state, name)
        raise AttributeError(name)

    def snapshot(self) -> _ReadState:
        """Return the current read-side snapshot (consistent set of components)."""
        return self._state

    # ---- construction ----------------------------------------------------
    def _build(self) -> _ReadState:
        """Construct a fresh set of read-side components. Pure: no self mutation."""
        db = GraphDB(self.cfg.db_path)
        dim = db.get_meta("embed_dim", self.cfg.embed_dim) or self.cfg.embed_dim
        vectors = VectorStore(self.cfg.vectors_path, dim)
        embedder = get_embedder(self.cfg)
        search_engine = SearchEngine(db, vectors, embedder)
        chat = get_chat(self.cfg)
        ask_engine = AskEngine(self.cfg, db, vectors, embedder, chat=chat)
        return _ReadState(db=db, vectors=vectors, embedder=embedder,
                          search_engine=search_engine, chat=chat,
                          ask_engine=ask_engine)

    def ensure_chat(self):
        """Retry chat-model discovery and keep AskEngine wired to it."""
        if self.chat is None:
            self.chat = get_chat(self.cfg)
            self.ask_engine = AskEngine(self.cfg, self.db, self.vectors,
                                        self.embedder, chat=self.chat)
        return self.chat

    def build_extended(self, opts: dict, bus) -> ExtendedAsk:
        """Construct an ExtendedAsk orchestrator with caps from the request.

        Reads from a single snapshot to avoid mixing old + new components if
        a reload is racing this call.
        """
        snap = self._state
        return ExtendedAsk(
            self.cfg, snap.db, snap.vectors, snap.embedder, chat=snap.chat, bus=bus,
            keyword_rounds=int(opts.get("keyword_rounds", 2)),
            keywords_per_round=int(opts.get("keywords_per_round", 4)),
            agents_per_round=int(opts.get("agents_per_round", 3)),
            max_rounds=int(opts.get("max_rounds", 10)),
        )

    def reload(self) -> None:
        """Re-open read components after an index run.

        Builds the new snapshot OUTSIDE the swap lock (so request threads
        aren't blocked while we load the embedder / chat model), then takes
        the lock just to perform the atomic pointer swap and capture the
        old snapshot. The old DB connection is closed on a delayed daemon
        timer so any in-flight request that already captured it can finish.
        """
        new_state = self._build()           # heavy work, no lock
        with self._reload_lock:             # short critical section
            old_state = self._state
            self._state = new_state
        try:
            timer = threading.Timer(2.0, lambda: _safe_close(old_state.db))
            timer.daemon = True             # don't block interpreter shutdown
            timer.start()
        except Exception:
            _safe_close(old_state.db)


def _safe_close(db) -> None:
    try:
        db.close()
    except Exception:
        pass
