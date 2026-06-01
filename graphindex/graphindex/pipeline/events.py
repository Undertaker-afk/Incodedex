"""Event bus for streaming indexing progress to subscribers (WebUI, CLI).

The orchestrator emits small JSON-serializable events as it works. Subscribers
register callbacks; the Flask/SocketIO layer forwards them to the browser so the
graph grows node-by-node and recolours as each node advances through its
lifecycle (discovered → parsed → embedded → summarized; hub/unresolved/warning).
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


# Event types emitted by the pipeline.
NODE_ADD = "node_add"          # a node first appears (gray)
NODE_UPDATE = "node_update"    # state/colour/flags change
EDGE_ADD = "edge_add"          # a new edge between two nodes
PHASE = "phase"                # pipeline phase change (scan/parse/...)
STATS = "stats"                # rolling counters / health metrics
LOG = "log"                    # human-readable log line
DONE = "done"                  # indexing complete
NODE_REMOVE = "node_remove"    # pruning removed a node


@dataclass
class IndexEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.payload}


class EventBus:
    """Thread-safe fan-out of :class:`IndexEvent` to registered callbacks."""

    def __init__(self) -> None:
        self._subs: list[Callable[[IndexEvent], None]] = []
        self._lock = threading.Lock()
        self.history: list[dict[str, Any]] = []
        self.keep_history = False

    def subscribe(self, cb: Callable[[IndexEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subs.append(cb)

        def _unsub() -> None:
            with self._lock:
                if cb in self._subs:
                    self._subs.remove(cb)

        return _unsub

    def emit(self, type_: str, **payload: Any) -> None:
        evt = IndexEvent(type=type_, payload=payload)
        if self.keep_history:
            self.history.append(evt.to_dict())
        with self._lock:
            subs = list(self._subs)
        for cb in subs:
            try:
                cb(evt)
            except Exception:
                # a misbehaving subscriber must never break indexing
                pass
