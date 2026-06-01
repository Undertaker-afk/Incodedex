"""Incremental watcher: re-index changed files and prune deleted ones.

Uses ``watchdog`` to observe the repo. Events are debounced (coalesced over a
short window) and filtered through the same ignore rules as a full scan. On
each flush it re-indexes the changed files (``Indexer.index(only_changed=...)``)
and prunes any files that disappeared, emitting the same event stream the WebUI
consumes so the live graph updates in place.
"""

from __future__ import annotations

import os
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..analysis.health import prune_deleted_files
from ..config import Config
from ..pipeline.events import EventBus
from ..pipeline.orchestrator import Indexer
from ..scanner.ignore import IgnoreEngine
from ..scanner.walker import detect_language


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "RepoWatcher"):
        self.w = watcher

    def on_any_event(self, event):
        if event.is_directory:
            return
        self.w._enqueue(event.src_path)
        dest = getattr(event, "dest_path", None)
        if dest:
            self.w._enqueue(dest)


class RepoWatcher:
    def __init__(self, cfg: Config, bus: EventBus | None = None,
                 debounce: float = 1.0, do_summarize: bool = False):
        self.cfg = cfg
        self.bus = bus or EventBus()
        self.debounce = debounce
        self.do_summarize = do_summarize
        self.ignore = IgnoreEngine(cfg.repo_path)
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._observer: Observer | None = None

    def _enqueue(self, abs_path: str) -> None:
        try:
            rel = os.path.relpath(abs_path, self.cfg.repo_path)
        except ValueError:
            return
        rel = rel.replace("\\", "/")
        if self.ignore.is_ignored(rel):
            return
        if not detect_language(rel)[1]:
            return
        with self._lock:
            self._pending.add(rel)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            changed = sorted(self._pending)
            self._pending.clear()
        if not changed:
            return
        self.bus.emit("log", message=f"Incremental update: {len(changed)} file(s)")
        indexer = Indexer(self.cfg, bus=self.bus, do_summarize=self.do_summarize)
        # 1) Handle deletions from the changed set FIRST so node_remove events are
        #    emitted (a blanket prune first would delete the rows, leaving the
        #    explicit loop nothing to report and the UI graph stale).
        existing = [c for c in changed if (self.cfg.repo_path / c).exists()]
        for path in changed:
            if not (self.cfg.repo_path / path).exists():
                ids = indexer.db.delete_file(path)
                indexer.vectors.remove(set(ids))
                for nid in ids:
                    self.bus.emit("node_remove", id=nid)
        # 2) Catch any other files deleted outside the changed set.
        prune_deleted_files(self.cfg, indexer.db, indexer.vectors)
        if existing:
            indexer.index(only_changed=existing)
        indexer.db.close()

    def start(self) -> None:
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.cfg.repo_path), recursive=True)
        self._observer.start()
        self.bus.emit("log", message="Watching for changes…")

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
