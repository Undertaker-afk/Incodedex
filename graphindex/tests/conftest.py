"""Shared pytest fixtures.

Tests run against the deterministic *fallback* backend so they're fast and
hermetic (no model download / GPU). The real llama.cpp path is exercised
separately in manual/integration runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from graphindex.config import load_config
from graphindex.pipeline import Indexer

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def sample_repo(tmp_path):
    dst = tmp_path / "repo"
    shutil.copytree(FIXTURE, dst)
    return dst


@pytest.fixture()
def cfg(sample_repo):
    return load_config(sample_repo, backend="fallback", embed_dim=256,
                       auto_install=False, auto_download=False)


@pytest.fixture()
def indexed(cfg):
    ix = Indexer(cfg, do_summarize=True, do_embed=True)
    metrics = ix.index()
    yield ix, metrics
    ix.db.close()
