"""Compressed/Cached Source storage for graphindex.

Provides a mechanism to store and retrieve full symbol source and file source
in a dedicated cache directory.
"""

from __future__ import annotations

import json
import os
import zlib
from pathlib import Path


class CompSrc:
    def __init__(self, root_dir: str | Path):
        self.root = Path(root_dir) / ".graphindex" / "compsrc"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, node_id: str) -> Path:
        return self.root / f"{node_id}.json.z"

    def store(self, node_id: str, code: str, summary: str = "", language: str = "") -> None:
        """Store compressed source + metadata for a node."""
        data = {
            "code": code,
            "summary": summary,
            "language": language
        }
        raw = json.dumps(data).encode("utf-8")
        compressed = zlib.compress(raw)
        self._path(node_id).write_bytes(compressed)

    def retrieve(self, node_id: str) -> dict | None:
        """Retrieve and decompress source for a node."""
        path = self._path(node_id)
        if not path.exists():
            return None
        try:
            compressed = path.read_bytes()
            raw = zlib.decompress(compressed)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def get_source_with_summary(self, node_id: str) -> str | None:
        """Retrieve source and inject summary as inline comments."""
        data = self.retrieve(node_id)
        if not data:
            return None

        code = data.get("code", "")
        summary = data.get("summary", "")
        lang = data.get("language", "").lower()

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
