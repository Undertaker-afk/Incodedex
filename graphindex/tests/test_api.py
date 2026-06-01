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
