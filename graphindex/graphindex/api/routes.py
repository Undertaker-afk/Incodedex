"""REST API blueprint.

Endpoints (all under ``/api``):

* ``GET  /health``        – index health metrics
* ``GET  /graph``         – nodes + edges for the visualization (limited)
* ``GET  /node/<id>``     – node detail + code intelligence (defs/refs/calls/inheritance)
* ``GET  /search``        – regex / semantic / fuzzy / filtered / scoped search
* ``GET  /stats``         – languages, dependencies, dead code, duplicates
* ``POST /index``         – (re)build the index in the background (streams via WS)
* ``POST /prune``         – prune nodes for deleted files
* ``GET  /config``        – effective configuration / backend info
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..analysis.deadcode import find_dead_code
from ..analysis.dependencies import dependency_graph
from ..analysis.health import health_report
from ..analysis.languages import language_breakdown
from ..graph.model import NodeKind
from ..graph.resolver import (call_hierarchy, find_references, inheritance)
from ..search import parse_query

bp = Blueprint("api", __name__, url_prefix="/api")


def _state():
    return current_app.config["GRAPHINDEX_STATE"]


@bp.get("/health")
def health():
    return jsonify(health_report(_state().db))


@bp.get("/config")
def config():
    st = _state()
    return jsonify({
        "repo_path": str(st.cfg.repo_path),
        "backend": st.cfg.backend,
        "embedder": getattr(st.embedder, "name", "?"),
        "vector_backend": st.vectors.backend,
        "embed_dim": st.vectors.dim,
        "hub_degree_threshold": st.cfg.hub_degree_threshold,
    })


@bp.get("/graph")
def graph():
    st = _state()
    limit = int(request.args.get("limit", 4000))
    kind = request.args.get("kind")
    nodes = st.db.iter_nodes(kind=kind)[:limit]
    node_ids = {n.id for n in nodes}
    out_nodes = []
    for n in nodes:
        out_nodes.append({
            "id": n.id, "label": n.name, "kind": n.kind, "path": n.path,
            "language": n.language, "state": n.state, "degree": n.degree,
            "is_hub": n.degree >= st.cfg.hub_degree_threshold and n.kind != NodeKind.EXTERNAL.value,
            "flags": n.flags, "summary": n.summary, "tags": n.tags,
            "group": n.path or n.kind,
        })
    out_edges = []
    for e in st.db.iter_edges():
        if e.src in node_ids and e.dst in node_ids:
            out_edges.append({"id": e.id, "source": e.src, "target": e.dst,
                              "kind": e.kind, "resolved": e.resolved})
    return jsonify({"nodes": out_nodes, "edges": out_edges})


@bp.get("/node/<node_id>")
def node_detail(node_id):
    st = _state()
    n = st.db.get_node(node_id)
    if not n:
        return jsonify({"error": "not found"}), 404
    ch = call_hierarchy(st.db, node_id)
    inh = inheritance(st.db, node_id)
    refs = find_references(st.db, node_id)
    return jsonify({
        "node": n.to_dict(),
        "callers": [x.to_dict() for x in ch["callers"]],
        "callees": [x.to_dict() for x in ch["callees"]],
        "ancestors": [x.to_dict() for x in inh["ancestors"]],
        "descendants": [x.to_dict() for x in inh["descendants"]],
        "references": [x.to_dict() for x in refs],
    })


@bp.get("/search")
def search():
    st = _state()
    raw = request.args.get("q", "")
    q = parse_query(
        raw,
        regex=request.args.get("regex") == "true",
        semantic=request.args.get("semantic") == "true",
        fuzzy=request.args.get("fuzzy") == "true",
        case_sensitive=request.args.get("case") == "true",
        top_k=int(request.args.get("k", 25)),
    )
    results = st.search_engine.search(q)
    return jsonify({"query": raw, "count": len(results),
                    "results": [r.to_dict() for r in results]})


@bp.post("/ask")
def ask():
    """Grounded RAG: rewrite question -> retrieve -> read source -> answer."""
    st = _state()
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or request.args.get("q") or "").strip()
    if not question:
        return jsonify({"error": "question required"}), 400
    k = int(body.get("k", 8))
    answer = st.ask_engine.ask(question, k=k)
    return jsonify(answer.to_dict())


@bp.get("/stats")
def stats():
    st = _state()
    return jsonify({
        "languages": language_breakdown(st.db),
        "dependencies": dependency_graph(st.db),
        "dead_code": find_dead_code(st.db),
        "health": health_report(st.db),
    })


@bp.post("/index")
def index():
    st = _state()
    body = request.get_json(silent=True) or {}
    do_summarize = bool(body.get("summarize", True))
    do_embed = bool(body.get("embed", True))
    backend = body.get("backend")
    started = current_app.config["GRAPHINDEX_RUN_INDEX"](do_summarize, do_embed, backend)
    if not started:
        return jsonify({"status": "already_running"}), 409
    return jsonify({"status": "started"})


@bp.post("/prune")
def prune():
    from ..analysis.health import prune_deleted_files
    st = _state()
    res = prune_deleted_files(st.cfg, st.db, st.vectors)
    st.reload()
    return jsonify(res)
