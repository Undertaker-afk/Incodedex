"""Compressed/Cached Source storage for graphindex.

Provides a mechanism to store and retrieve full symbol source and file source
in a dedicated cache directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zlib
from pathlib import Path

log = logging.getLogger(__name__)


class CompSrc:
    def __init__(self, root_dir: str | Path):
        self.root = Path(root_dir) / ".graphindex" / "compsrc"
        self._batch: dict[str, dict] = {}

    def _safe_id(self, node_id: str) -> str:
        """Sanitize node_id to prevent path traversal and malformed keys."""
        # node_id is typically a hex string from make_node_id, but we hash it
        # to be absolutely certain it's a safe filename.
        return hashlib.sha256(node_id.encode("utf-8")).hexdigest()

    def _path(self, node_id: str) -> Path:
        return self.root / f"{self._safe_id(node_id)}.json.z"

    def store(self, node_id: str, code: str | None, summary: str = "", language: str = "") -> None:
        """Store compressed source + metadata for a node."""
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "code": code or "",
            "summary": summary,
            "language": language
        }
        raw = json.dumps(data).encode("utf-8")
        compressed = zlib.compress(raw)
        try:
            self._path(node_id).write_bytes(compressed)
        except OSError as exc:
            log.warning("compsrc.store failed for %s: %s", node_id, exc)

    def add_to_batch(self, node_id: str, code: str | None, summary: str = "", language: str = "") -> None:
        """Buffer a node for batch storage."""
        self._batch[node_id] = {
            "code": code or "",
            "summary": summary,
            "language": language
        }

    def flush_batch(self) -> None:
        """Write all buffered nodes to disk."""
        if not self._batch:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        for node_id, data in self._batch.items():
            raw = json.dumps(data).encode("utf-8")
            compressed = zlib.compress(raw)
            try:
                self._path(node_id).write_bytes(compressed)
            except OSError as exc:
                log.warning("compsrc.flush_batch failed for %s: %s", node_id, exc)
                continue
        self._batch.clear()

    def retrieve(self, node_id: str) -> dict | None:
        """Retrieve and decompress source for a node."""
        try:
            path = self._path(node_id)
            if not path.exists():
                return None
            compressed = path.read_bytes()
            raw = zlib.decompress(compressed)
            return json.loads(raw.decode("utf-8"))
        except (OSError, zlib.error, json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.warning("compsrc.retrieve failed for %s: %s", node_id, exc)
            return None

    def get_source_with_summary(self, node_id: str) -> str | None:
        """Retrieve source and inject summary as inline comments."""
        data = self.retrieve(node_id)
        if not data:
            return None

        code = data.get("code") or ""
        summary = data.get("summary") or ""
        lang = (data.get("language") or "").lower()

        if not summary:
            return code

        # Basic comment prefix based on language
        prefix = "//"
        if lang in {"python", "ruby", "bash", "perl", "yaml", "dockerfile", "julia", "elixir"}:
            prefix = "#"
        elif lang in {"sql", "haskell", "lua", "elm"}:
            prefix = "--"
        elif lang in {"clojure"}:
            prefix = ";"

        commented_summary = "\n".join([f"{prefix} {line}" for line in summary.splitlines()])
        return f"{commented_summary}\n\n{code}"

    def prune_stale(self, active_node_ids: set[str]) -> int:
        """Delete cached files that are not in the active set. Returns count deleted."""
        if not self.root.exists():
            return 0

        safe_active_ids = {self._safe_id(nid) for nid in active_node_ids}
        deleted = 0
        for p in self.root.glob("*.json.z"):
            safe_id = p.name.split(".")[0]
            if safe_id not in safe_active_ids:
                try:
                    p.unlink()
                    deleted += 1
                except OSError as exc:
                    log.warning("compsrc.prune_stale: %s: %s", p, exc)
        return deleted
