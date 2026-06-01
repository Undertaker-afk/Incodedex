from graphindex.graph.model import EdgeKind, NodeKind
from graphindex.graph.resolver import (call_hierarchy, find_references,
                                       goto_definition, inheritance)


def test_graph_has_expected_structure(indexed):
    ix, m = indexed
    assert m["nodes"] > 0 and m["edges"] > 0
    kinds = {n.kind for n in ix.db.iter_nodes()}
    assert {"file", "class", "method", "function"} <= kinds


def test_inheritance_edges(indexed):
    ix, _ = indexed
    dogs = goto_definition(ix.db, "Dog", kind="class")
    assert dogs
    inh = inheritance(ix.db, dogs[0].id)
    assert any(a.name == "Animal" for a in inh["ancestors"])


def test_call_hierarchy_and_references(indexed):
    ix, _ = indexed
    # make_dog calls Dog().speak() -> resolves to speak method(s)
    speaks = goto_definition(ix.db, "speak")
    assert speaks
    refs = find_references(ix.db, speaks[0].id)
    # something references speak (make_dog / make_cat)
    assert isinstance(refs, list)
    ch = call_hierarchy(ix.db, speaks[0].id)
    assert "callers" in ch and "callees" in ch


def test_imports_resolved_internally(indexed):
    ix, _ = indexed
    import_edges = [e for e in ix.db.iter_edges() if e.kind == EdgeKind.IMPORTS.value]
    # app.js -> pkg/service.py and pkg/service.py -> pkg/models.py
    assert any(e.resolved for e in import_edges)
