"""Tests for fixes applied from the PR review."""

import numpy as np
import pytest

from graphindex.config import load_config
from graphindex.embedding import get_embedder
from graphindex.embedding.fallback import HashingEmbedder
from graphindex.storage.vectors import VectorStore


def test_vectorstore_get_vector_and_o1(tmp_path):
    vs = VectorStore(tmp_path / "v", dim=4)
    vs.add("a", [1, 0, 0, 0])
    vs.add("b", [0, 1, 0, 0])
    assert vs.get_vector("a") is not None
    assert vs.get_vector("missing") is None
    # updating an existing id must not duplicate
    vs.add("a", [0, 0, 1, 0])
    assert len(vs) == 2


def test_vectorstore_dimension_mismatch_starts_fresh(tmp_path):
    p = tmp_path / "v"
    vs = VectorStore(p, dim=4)
    vs.add("a", [1, 0, 0, 0]); vs.save()
    # reopen with a different dim -> must not be left half-initialized
    vs2 = VectorStore(p, dim=8)
    assert len(vs2) == 0
    assert vs2._matrix.shape == (0, 8)
    vs2.add("x", np.ones(8, dtype="float32"))  # must not raise
    assert len(vs2) == 1


def test_fallback_embedder_rejects_bad_dim():
    with pytest.raises(ValueError):
        HashingEmbedder(0)


def test_unknown_backend_raises(tmp_path):
    cfg = load_config(tmp_path, backend="llama_cpp_typo")
    with pytest.raises(ValueError):
        get_embedder(cfg)


def test_path_filter_is_substring_not_scope():
    from graphindex.search import parse_query
    q = parse_query("foo path:models")
    assert q.filters["path"] == "models"
    assert q.scope == ""        # path: must NOT set the directory-prefix scope


def test_api_rejects_bad_numeric_params(cfg):
    from graphindex.pipeline import Indexer
    from graphindex.api.server import create_app
    ix = Indexer(cfg); ix.index(); ix.db.close()
    app, _ = create_app(cfg)
    app.testing = True
    c = app.test_client()
    assert c.get("/api/search?q=x&k=abc").status_code == 400
    assert c.get("/api/graph?limit=notanint").status_code == 400
    # valid still works
    assert c.get("/api/search?q=make&fuzzy=true&k=5").status_code == 200


def test_dead_code_single_pass_matches(indexed):
    from graphindex.analysis.deadcode import find_dead_code
    dead = {d["name"] for d in find_dead_code(indexed[0].db)}
    assert "unused_helper" in dead
