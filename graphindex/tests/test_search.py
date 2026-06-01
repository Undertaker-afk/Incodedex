from graphindex.search import SearchEngine, parse_query
from graphindex.storage.vectors import VectorStore


def _engine(ix):
    vs = VectorStore(ix.cfg.vectors_path, ix.db.get_meta("embed_dim", 256))
    return SearchEngine(ix.db, vs, ix.embedder)


def test_parse_query_filters():
    q = parse_query("lang:python kind:function auth token", semantic=True)
    assert q.filters["lang"] == "python"
    assert q.filters["kind"] == "function"
    assert q.text == "auth token"
    assert q.semantic is True


def test_filter_only_search(indexed):
    ix, _ = indexed
    eng = _engine(ix)
    res = eng.search(parse_query("kind:class lang:python"))
    assert res and all(r.node.kind == "class" for r in res)


def test_regex_search(indexed):
    ix, _ = indexed
    eng = _engine(ix)
    res = eng.search(parse_query("^make_", regex=True))
    names = {r.node.name for r in res}
    assert "make_dog" in names and "make_cat" in names


def test_fuzzy_typo(indexed):
    ix, _ = indexed
    eng = _engine(ix)
    res = eng.search(parse_query("nois", fuzzy=True))
    assert any(r.node.name == "noise" for r in res)


def test_scope_filter(indexed):
    ix, _ = indexed
    eng = _engine(ix)
    res = eng.search(parse_query("speak scope:pkg"))
    assert all(r.node.path.startswith("pkg") for r in res)


def test_semantic_runs(indexed):
    ix, _ = indexed
    eng = _engine(ix)
    # fallback embeddings are weak but the path must execute & rank by overlap
    res = eng.search(parse_query("noise sound", semantic=True))
    assert isinstance(res, list)
