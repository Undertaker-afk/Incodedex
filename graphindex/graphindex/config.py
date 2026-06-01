"""Central configuration for graphindex.

All tunables live here so the rest of the package can stay declarative.
Configuration is resolved from (in order of precedence):

1. Explicit kwargs passed to :func:`load_config`.
2. Environment variables prefixed with ``GRAPHINDEX_``.
3. Built-in defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"GRAPHINDEX_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    val = _env(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    val = _env(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Model registry: the two models from the plan, exposed as GGUF repos.
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    """Identifies a GGUF model on the Hugging Face hub."""

    repo_id: str
    filename: str
    kind: str  # "embedding" | "chat"
    dim: int = 0  # embedding dimension (embedding models only)


# Defaults chosen per the approved plan. Filenames are best-effort and can be
# overridden via env vars; the engine bootstrap resolves the closest match.
DEFAULT_EMBED_MODEL = ModelSpec(
    repo_id=_env("EMBED_REPO", "Qwen/Qwen3-Embedding-0.6B-GGUF") or "Qwen/Qwen3-Embedding-0.6B-GGUF",
    filename=_env("EMBED_FILE", "Qwen3-Embedding-0.6B-Q8_0.gguf") or "Qwen3-Embedding-0.6B-Q8_0.gguf",
    kind="embedding",
    dim=_env_int("EMBED_DIM", 1024),
)

DEFAULT_CHAT_MODEL = ModelSpec(
    repo_id=_env("CHAT_REPO", "LiquidAI/LFM2.5-1.2B-Instruct-GGUF")
    or "LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
    filename=_env("CHAT_FILE", "LFM2.5-1.2B-Instruct-Q4_K_M.gguf")
    or "LFM2.5-1.2B-Instruct-Q4_K_M.gguf",
    kind="chat",
)


@dataclass
class Config:
    """Runtime configuration for an index session."""

    # Where the repository to index lives.
    repo_path: Path = field(default_factory=lambda: Path(_env("REPO_PATH", ".") or ".").resolve())

    # Where graphindex stores its artifacts (relative to repo unless absolute).
    data_dir_name: str = ".graphindex"

    # Model backend: "auto" picks llamacpp when available else fallback.
    backend: str = field(default_factory=lambda: _env("BACKEND", "auto") or "auto")
    engine_mode: str = field(default_factory=lambda: _env("ENGINE_MODE", "in_process") or "in_process")
    auto_install: bool = field(default_factory=lambda: _env_bool("AUTO_INSTALL", True))
    auto_download: bool = field(default_factory=lambda: _env_bool("AUTO_DOWNLOAD", True))

    embed_model: ModelSpec = field(default_factory=lambda: DEFAULT_EMBED_MODEL)
    chat_model: ModelSpec = field(default_factory=lambda: DEFAULT_CHAT_MODEL)

    # Embedding dimension used by the vector store (must match the embedder).
    embed_dim: int = field(default_factory=lambda: _env_int("EMBED_DIM", 1024))

    # Pipeline tuning.
    max_file_bytes: int = field(default_factory=lambda: _env_int("MAX_FILE_BYTES", 1_500_000))
    hub_degree_threshold: int = field(default_factory=lambda: _env_int("HUB_DEGREE", 8))
    duplicate_similarity: float = 0.92
    summary_max_tokens: int = field(default_factory=lambda: _env_int("SUMMARY_TOKENS", 96))
    embed_batch: int = field(default_factory=lambda: _env_int("EMBED_BATCH", 16))
    # llama.cpp threading. Capping is important: on high-core-count / cgroup
    # limited hosts, an unbounded batch threadpool spin-waits and stalls.
    n_threads: int = field(
        default_factory=lambda: _env_int("THREADS", min(os.cpu_count() or 4, 8)))
    n_threads_batch: int = field(
        default_factory=lambda: _env_int("THREADS_BATCH", min(os.cpu_count() or 4, 8)))

    # Server.
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0") or "0.0.0.0")
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))

    @property
    def data_dir(self) -> Path:
        return self.repo_path / self.data_dir_name

    @property
    def db_path(self) -> Path:
        return self.data_dir / "graph.db"

    @property
    def vectors_path(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def models_dir(self) -> Path:
        env = _env("MODELS_DIR")
        if env:
            return Path(env).expanduser()
        return Path.home() / ".cache" / "graphindex" / "models"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.vectors_path.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["repo_path"] = str(self.repo_path)
        return d


def load_config(repo_path: str | os.PathLike | None = None, **overrides: Any) -> Config:
    """Build a :class:`Config`, applying explicit overrides on top of env/defaults."""
    cfg = Config()
    if repo_path is not None:
        cfg.repo_path = Path(repo_path).resolve()
    for key, value in overrides.items():
        if value is None:
            continue
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    cfg.embed_dim = cfg.embed_model.dim or cfg.embed_dim
    return cfg
