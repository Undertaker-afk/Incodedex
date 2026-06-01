"""Flask + SocketIO application factory.

Serves the REST API (``routes.bp``), streams indexing events over SocketIO so
the WebUI grows node-by-node, and — when a built frontend is bundled in
``graphindex/frontend_dist/`` — serves the single-page app. The index run
executes in a background thread; its :class:`EventBus` is bridged to SocketIO.
"""

from __future__ import annotations

import threading
from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

from ..config import Config
from ..pipeline.events import IndexEvent
from ..pipeline.orchestrator import Indexer
from .routes import bp
from .state import AppState


def _resolve_frontend_dist() -> Path | None:
    """Locate the bundled React SPA ``dist/`` directory.

    Looks for ``frontend_dist/`` in the installed package via
    :mod:`importlib.resources` so it works after ``pip install`` (no source
    checkout required). Falls back to the source-tree path
    ``<repo>/frontend/dist`` for editable installs / dev runs.
    """
    # 1) Installed package: graphindex.frontend_dist  (package data)
    try:
        import importlib.resources as ilr
        ref = ilr.files("graphindex").joinpath("frontend_dist", "index.html")
        if ref.is_file():
            # `index.html` is at the root of the bundle; return the parent dir.
            return Path(str(ref.parent))
    except Exception:
        pass
    # 2) Source-tree fallback (editable install / dev): the layout has the
    # `frontend/` dir as a sibling of the `graphindex/` package dir.
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


_FRONTEND_DIST = _resolve_frontend_dist()


def create_app(cfg: Config):
    app = Flask(__name__, static_folder=None)
    CORS(app)
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        allow_upgrades=False,
        transports=["polling"],
    )

    state = AppState(cfg)
    app.config["GRAPHINDEX_STATE"] = state
    app.config["GRAPHINDEX_SOCKETIO"] = socketio

    # Bridge the event bus -> SocketIO. Indexing events go on "index_event";
    # extended_ask events (type starting with "ext_") also go on "ext_event".
    def _forward(evt: IndexEvent) -> None:
        d = evt.to_dict()
        if evt.type.startswith("ext_"):
            socketio.emit("ext_event", d)
        else:
            socketio.emit("index_event", d)

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
        socketio.emit("hello", {"indexing": state.indexing,
                                "repo": str(cfg.repo_path)})

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
