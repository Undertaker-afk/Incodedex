"""Repository walker: produces file records with language + content hashing."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .ignore import IgnoreEngine

# Extension -> (language, tree-sitter grammar name). Driving table; add a row to
# support a new language.
LANGUAGE_TABLE: dict[str, tuple[str, str]] = {
    ".py": ("Python", "python"),
    ".pyi": ("Python", "python"),
    ".js": ("JavaScript", "javascript"),
    ".jsx": ("JavaScript", "javascript"),
    ".mjs": ("JavaScript", "javascript"),
    ".cjs": ("JavaScript", "javascript"),
    ".ts": ("TypeScript", "typescript"),
    ".tsx": ("TypeScript", "tsx"),
    ".go": ("Go", "go"),
    ".java": ("Java", "java"),
    ".rs": ("Rust", "rust"),
    ".rb": ("Ruby", "ruby"),
    ".c": ("C", "c"),
    ".h": ("C", "c"),
    ".cpp": ("C++", "cpp"),
    ".cc": ("C++", "cpp"),
    ".hpp": ("C++", "cpp"),
    ".cs": ("C#", "c_sharp"),
    ".php": ("PHP", "php"),
}


def detect_language(path: str) -> tuple[str, str]:
    ext = os.path.splitext(path)[1].lower()
    return LANGUAGE_TABLE.get(ext, ("", ""))


@dataclass
class FileRecord:
    rel_path: str
    abs_path: str
    language: str
    grammar: str
    size: int
    mtime: float
    sha: str


def hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def current_commit(repo_path: Path) -> str:
    """Return the current git commit SHA, or '' if not a git repo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


class RepoScanner:
    def __init__(self, repo_path: str | Path, max_file_bytes: int = 1_500_000):
        self.repo_path = Path(repo_path).resolve()
        self.max_file_bytes = max_file_bytes
        self.ignore = IgnoreEngine(self.repo_path)

    def scan(self, only_languages: bool = True):
        """Yield :class:`FileRecord` for each indexable file.

        ``only_languages`` restricts output to files with a known grammar.
        """
        for rel in self.ignore.walk():
            abs_path = self.repo_path / rel
            try:
                stat = abs_path.stat()
            except OSError:
                continue
            if stat.st_size > self.max_file_bytes:
                continue
            language, grammar = detect_language(rel)
            if only_languages and not grammar:
                continue
            try:
                data = abs_path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:1024]:  # binary guard
                continue
            yield FileRecord(
                rel_path=rel, abs_path=str(abs_path), language=language,
                grammar=grammar, size=stat.st_size, mtime=stat.st_mtime,
                sha=hash_bytes(data),
            )
