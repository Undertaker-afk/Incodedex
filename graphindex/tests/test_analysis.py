from graphindex.analysis.deadcode import find_dead_code
from graphindex.analysis.dependencies import dependency_graph
from graphindex.analysis.health import prune_deleted_files
from graphindex.analysis.languages import language_breakdown


def test_duplicates_flagged(indexed):
    ix, _ = indexed
    flagged = {n.name for n in ix.db.iter_nodes() if "duplicate" in n.flags}
    assert {"duplicate_a", "duplicate_b"} <= flagged


def test_dead_code_detection(indexed):
    ix, _ = indexed
    dead = {d["name"] for d in find_dead_code(ix.db)}
    assert "unused_helper" in dead


def test_language_breakdown(indexed):
    ix, _ = indexed
    lb = language_breakdown(ix.db)
    assert lb["files_by_language"].get("Python", 0) >= 2
    assert "JavaScript" in lb["files_by_language"]


def test_dependency_graph_internal(indexed):
    ix, _ = indexed
    dg = dependency_graph(ix.db)
    targets = {e["target"] for e in dg["internal_edges"]}
    assert "pkg/models.py" in targets


def test_prune_deleted_files(indexed):
    ix, _ = indexed
    # delete a file from disk then prune
    (ix.cfg.repo_path / "app.js").unlink()
    before = ix.db.count_nodes()
    res = prune_deleted_files(ix.cfg, ix.db, ix.vectors)
    assert "app.js" in res["removed_files"]
    assert ix.db.count_nodes() < before
