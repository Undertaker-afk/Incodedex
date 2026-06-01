"""Flask + SocketIO application factory.

Serves the REST API (``routes.bp``), streams indexing events over SocketIO so
the WebUI grows node-by-node, and — when a built frontend is present in
``frontend/dist`` — serves the single-page app. The index run executes in a
background thread; its :class:`EventBus` is bridged to SocketIO.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

log = logging.getLogger(__name__)

from ..config import Config
from ..pipeline.events import IndexEvent
from ..pipeline.orchestrator import Indexer
from .routes import bp
from .state import AppState

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# Event coalescing: cap the number of events forwarded to SocketIO subscribers
# in any single batch, and the minimum interval between batches. Without this,
# a full re-index of a large repo will flood the message queue and the browser.
_BATCH_INTERVAL = 0.05      # seconds
_BATCH_MAX_EVENTS = 500     # events per emit


def create_app(cfg: Config):
    app = Flask(__name__, static_folder=None)
    CORS(app)
    # ``async_mode="threading"`` + the plain Werkzeug dev server does not handle
    # WebSocket transport reliably (causes the "write() before start_response"
    # 500s seen in production logs). ``allow_upgrades=False`` blocks the
    # polling -> websocket *upgrade*, and the connect handler below rejects any
    # client that arrives directly on the websocket transport so engine.io
    # never enters that broken code path. Long-polling is fully functional.
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                        allow_upgrades=False)

    state = AppState(cfg)
    app.config["GRAPHINDEX_STATE"] = state
    app.config["GRAPHINDEX_SOCKETIO"] = socketio

    # Bridge the event bus -> SocketIO with coalescing so a fast indexer cannot
    # flood the WS channel / the browser. Events are buffered and flushed by a
    # single background dispatcher thread at most every ``_BATCH_INTERVAL``.
    pending_index: list[dict] = []
    pending_ext: list[dict] = []
    pending_lock = threading.Lock()
    flush_event = threading.Event()

    def _forward(evt: IndexEvent) -> None:
        d = evt.to_dict()
        with pending_lock:
            bucket = pending_ext if evt.type.startswith("ext_") else pending_index
            bucket.append(d)
            # cap unbounded growth if the dispatcher falls behind
            if len(bucket) > _BATCH_MAX_EVENTS * 20:
                del bucket[:-_BATCH_MAX_EVENTS * 10]
        flush_event.set()

    def _dispatcher() -> None:
        # The dispatcher MUST keep running for the lifetime of the server.
        # A single uncaught exception from socketio.emit() (e.g. transient
        # network / client-disconnect / library error) would otherwise kill
        # the thread and silently stop forwarding all future events.
        while True:
            try:
                flush_event.wait()
                flush_event.clear()
                time.sleep(_BATCH_INTERVAL)  # coalesce a burst
                with pending_lock:
                    idx_batch = pending_index[:_BATCH_MAX_EVENTS]
                    del pending_index[:len(idx_batch)]
                    ext_batch = pending_ext[:_BATCH_MAX_EVENTS]
                    del pending_ext[:len(ext_batch)]
                    more = bool(pending_index or pending_ext)
                for d in idx_batch:
                    try:
                        socketio.emit("index_event", d)
                    except Exception as exc:
                        log.warning("socketio.emit(index_event) failed: %s", exc)
                for d in ext_batch:
                    try:
                        socketio.emit("ext_event", d)
                    except Exception as exc:
                        log.warning("socketio.emit(ext_event) failed: %s", exc)
                if more:
                    flush_event.set()  # keep draining
            except Exception as exc:
                log.exception("socketio dispatcher loop error: %s", exc)
                time.sleep(1.0)  # avoid hot-spin on a repeating failure

    threading.Thread(target=_dispatcher, daemon=True,
                     name="socketio-dispatcher").start()
    state.bus.subscribe(_forward)

    # Background extended_ask runner (single-flight).
    def run_extended(question: str, opts: dict) -> bool:
        if not state.ask_lock.acquire(blocking=False):
            return False

        def _job():
            try:
                state.asking = True
                eng = state.build_extended(opts, state.bus)
                state.last_extended = eng.run(question).to_dict()
            finally:
                state.asking = False
                state.ask_lock.release()

        try:
            threading.Thread(target=_job, daemon=True).start()
        except Exception:
            state.ask_lock.release()
            raise
        return True

    app.config["GRAPHINDEX_RUN_EXTENDED"] = run_extended

    # Background index runner (single-flight).
    def run_index(do_summarize=True, do_embed=True, backend=None) -> bool:
        if not state.index_lock.acquire(blocking=False):
            return False

        def _job():
            try:
                state.indexing = True
                run_cfg = cfg
                if backend:
                    run_cfg = Config(**{**cfg.__dict__})
                    run_cfg.backend = backend
                indexer = Indexer(run_cfg, bus=state.bus, compsrc=state.compsrc,
                                  do_summarize=do_summarize, do_embed=do_embed)
                indexer.index()
                indexer.db.close()
                state.reload()
            finally:
                state.indexing = False
                state.index_lock.release()

        try:
            threading.Thread(target=_job, daemon=True).start()
        except Exception:
            state.index_lock.release()
            raise
        return True

    app.config["GRAPHINDEX_RUN_INDEX"] = run_index
    app.register_blueprint(bp)

    @socketio.on("connect")
    def _on_connect():
        # Reject any client that arrived on the websocket transport directly
        # (i.e. without going through polling first). ``allow_upgrades=False``
        # already disables polling -> ws upgrades; this guard closes the
        # remaining hole where a client whose transports list starts with
        # 'websocket' would still hit the broken Werkzeug WS path.
        from flask import request as _flask_request
        try:
            transport = _flask_request.args.get("transport", "")
        except Exception:
            transport = ""
        if transport == "websocket":
            return False  # engine.io interprets False as "reject connection"
        socketio.emit("hello", {"indexing": state.indexing,
                                "repo": str(cfg.repo_path)})
        return None

    # ---- frontend (SPA) ----
    @app.get("/")
    def _index_html():
        if (_FRONTEND_DIST / "index.html").exists():
            return send_from_directory(_FRONTEND_DIST, "index.html")
        return ("graphindex API is running. Build the frontend (frontend/) or "
                "use the REST API under /api.", 200)

    @app.get("/<path:path>")
    def _assets(path):
        target = _FRONTEND_DIST / path
        if target.exists():
            return send_from_directory(_FRONTEND_DIST, path)
        if (_FRONTEND_DIST / "index.html").exists():
            return send_from_directory(_FRONTEND_DIST, "index.html")
        return ("Not found", 404)

    return app, socketio
