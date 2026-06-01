import pytest

from graphindex.api.server import create_app


@pytest.fixture()
def client(cfg):
    # index first so the API has data
    from graphindex.pipeline import Indexer
    ix = Indexer(cfg)
    ix.index()
    ix.db.close()
    app, _socketio = create_app(cfg)
    app.testing = True
    return app.test_client()


def test_config_endpoint(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert "backend" in r.get_json()


def test_graph_endpoint(client):
    data = client.get("/api/graph").get_json()
    assert data["nodes"] and data["edges"]
    sample = data["nodes"][0]
    assert {"id", "label", "kind", "state"} <= set(sample)


def test_search_endpoint(client):
    data = client.get("/api/search?q=^make_&regex=true").get_json()
    assert data["count"] >= 1
    assert any(r["name"].startswith("make_") for r in data["results"])


def test_node_detail_endpoint(client):
    nodes = client.get("/api/graph").get_json()["nodes"]
    cls = next(n for n in nodes if n["kind"] == "class")
    detail = client.get(f"/api/node/{cls['id']}").get_json()
    assert detail["node"]["id"] == cls["id"]
    assert "callers" in detail and "ancestors" in detail


def test_stats_endpoint(client):
    data = client.get("/api/stats").get_json()
    assert "languages" in data and "dependencies" in data and "dead_code" in data


def test_node_source_symbol(client):
    """Symbol nodes always carry inline `code`, so the endpoint must succeed."""
    nodes = client.get("/api/graph").get_json()["nodes"]
    sym = next(n for n in nodes if n["kind"] in {"function", "method", "class"})
    r = client.get(f"/api/node/{sym['id']}/source")
    assert r.status_code == 200
    assert r.get_json()["source"]


def test_node_source_file_with_empty_compsrc(client, cfg, monkeypatch):
    """File nodes have no inline `code`; the endpoint must fall back to disk
    when the compsrc cache is empty (e.g. a stale index from before file bodies
    were being cached)."""
    nodes = client.get("/api/graph").get_json()["nodes"]
    f = next(n for n in nodes if n["kind"] == "file")
    # Wipe the compsrc cache for this id and clear any in-memory batch.
    from graphindex.api.state import AppState
    app = client.application
    state: AppState = app.config["GRAPHINDEX_STATE"]
    p = state.compsrc._path(f["id"])
    if p.exists():
        p.unlink()
    state.compsrc._batch.pop(f["id"], None)

    r = client.get(f"/api/node/{f['id']}/source")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()["source"]
    assert body and body != "source not found"
    # The body should look like the on-disk file (not a "not found" stub).
    on_disk = (cfg.repo_path / f["path"]).read_text(encoding="utf-8", errors="replace")
    assert body.strip() == on_disk.strip()


def test_node_source_unknown_returns_404(client):
    r = client.get("/api/node/does-not-exist/source")
    assert r.status_code == 404
