"""Ignore-rule engine combining ``.gitignore`` and a custom ``.graphignore``.

Both files use full gitignore semantics (via :mod:`pathspec`), including ``!``
negation, directory-only patterns, and nested ignore files. ``.graphignore``
is layered *after* ``.gitignore`` so a project can re-include (``!path``) files
that git ignores, or exclude extra files from the graph specifically.

A handful of always-ignored directories (``.git``, the graphindex data dir,
virtualenvs, ``node_modules``) are baked in so we never index our own output.
"""

from __future__ import annotations

import os
from pathlib import Path

import pathspec

# Directories we never descend into, regardless of ignore files.
ALWAYS_IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".graphindex", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".venv", "venv", "node_modules", ".idea", ".vscode",
    "dist", "build", ".next", ".cache", "target",
}


def _read_patterns(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


class IgnoreEngine:
    """Resolves whether a repo-relative path should be skipped."""

    def __init__(self, root: Path, extra_patterns: list[str] | None = None):
        self.root = Path(root).resolve()
        patterns: list[str] = []
        # Order matters: gitignore first, graphignore second (can override).
        for fname in (".gitignore", ".graphignore"):
            patterns.extend(_read_patterns(self.root / fname))
        if extra_patterns:
            patterns.extend(extra_patterns)
        # "gitignore" factory (newer pathspec); fall back to legacy name.
        try:
            self.spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        except (ValueError, KeyError):
            self.spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
        # A separate spec containing only graphignore for introspection/tests.
        self.graphignore_present = (self.root / ".graphignore").exists()

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        parts = Path(rel_path).parts
        if any(p in ALWAYS_IGNORE_DIRS for p in parts):
            return True
        candidate = rel_path
        if is_dir and not candidate.endswith("/"):
            candidate += "/"
        return self.spec.match_file(candidate)

    def walk(self):
        """Yield repo-relative file paths that survive the ignore rules."""
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = os.path.relpath(dirpath, self.root)
            rel_dir = "" if rel_dir == "." else rel_dir
            # Prune ignored directories in-place for speed.
            kept = []
            for d in dirnames:
                rel = os.path.join(rel_dir, d) if rel_dir else d
                if not self.is_ignored(rel, is_dir=True):
                    kept.append(d)
            dirnames[:] = kept
            for f in filenames:
                rel = os.path.join(rel_dir, f) if rel_dir else f
                if not self.is_ignored(rel, is_dir=False):
                    yield rel.replace(os.sep, "/")
