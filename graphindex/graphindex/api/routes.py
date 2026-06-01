"""REST API blueprint.

Endpoints (all under ``/api``):

* ``GET  /health``        – index health metrics
* ``GET  /graph``         – nodes + edges for the visualization (limited)
* ``GET  /node/<id>``     – node detail + code intelligence (defs/refs/calls/inheritance)
* ``GET  /node/<id>/source`` – cached source code with inline summary
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


class BadParam(ValueError):
    """Raised for invalid request params -> mapped to HTTP 400."""


def _parse_int(name, raw, default, min_v, max_v):
    """Parse + clamp an int request param; raise BadParam on bad input."""
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BadParam(f"{name} must be an integer")
    return max(min_v, min(max_v, value))


def _parse_bool(raw, default=True):
    """Parse a JSON/string boolean flag, honouring 'false'/'0'/'no'."""
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@bp.errorhandler(BadParam)
def _bad_param(e):
    return jsonify({"error": str(e)}), 400


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
    limit = _parse_int("limit", request.args.get("limit"), 4000, 1, 50000)
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


@bp.get("/node/<node_id>/source")
def node_source(node_id):
    st = _state()
    try:
        source = st.compsrc.get_source_with_summary(node_id)
    except ValueError:
        return jsonify({"error": "invalid node id"}), 400

    if source is None:
        # Fallback to DB node code if exists
        n = st.db.get_node(node_id)
        if n and n.code:
            source = n.code
        elif n and n.kind == NodeKind.FILE.value and n.path:
            # File nodes never carry an inline `code` payload. If the compsrc
            # cache wasn't populated for them (e.g. the index was built before
            # files were added to the cache), read the file from disk as a
            # last resort so the editor still has something to show.
            try:
                repo_root = st.cfg.repo_path
                on_disk = (repo_root / n.path).resolve()
                repo_root_resolved = repo_root.resolve()
                if (repo_root_resolved in on_disk.parents
                        or on_disk == repo_root_resolved) and on_disk.is_file():
                    source = on_disk.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                source = None

    if source is None:
        return jsonify({"error": "source not found"}), 404

    return jsonify({"source": source})


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
        top_k=_parse_int("k", request.args.get("k"), 25, 1, 200),
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
    k = _parse_int("k", body.get("k"), 8, 1, 200)
    answer = st.ask_engine.ask(question, k=k)
    return jsonify(answer.to_dict())


@bp.post("/extended_ask")
def extended_ask():
    """Run the multi-agent investigation in the background; stream via WS.

    Body: {question, keyword_rounds<=4, keywords_per_round<=8,
           agents_per_round<=3, max_rounds<=10}. Progress streams on the
    "ext_event" socket channel; the final result is the "ext_done" event and
    is also retrievable from GET /api/extended_ask/last.
    """
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question required"}), 400
    started = current_app.config["GRAPHINDEX_RUN_EXTENDED"](question, body)
    if not started:
        return jsonify({"status": "already_running"}), 409
    return jsonify({"status": "started"})


@bp.get("/extended_ask/last")
def extended_ask_last():
    st = _state()
    return jsonify({"asking": st.asking, "result": st.last_extended})


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
    do_summarize = _parse_bool(body.get("summarize"), True)
    do_embed = _parse_bool(body.get("embed"), True)
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
