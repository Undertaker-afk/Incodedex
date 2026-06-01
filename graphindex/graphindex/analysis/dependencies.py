"""Dependency graphing: internal (file->file) and external (file->package)."""

from __future__ import annotations

from collections import Counter, defaultdict

from ..graph.model import EdgeKind, NodeKind
from ..storage.db import GraphDB


def dependency_graph(db: GraphDB) -> dict:
    nodes = {n.id: n for n in db.iter_nodes()}
    internal_edges = []
    external_counter: Counter = Counter()
    fan_out: defaultdict = defaultdict(set)
    fan_in: defaultdict = defaultdict(set)

    for e in db.iter_edges():
        if e.kind != EdgeKind.IMPORTS.value:
            continue
        src = nodes.get(e.src)
        dst = nodes.get(e.dst)
        if not src or not dst:
            continue
        if dst.kind == NodeKind.EXTERNAL.value:
            external_counter[dst.name] += 1
        elif dst.kind == NodeKind.FILE.value and src.kind == NodeKind.FILE.value:
            internal_edges.append({"source": src.path, "target": dst.path})
            fan_out[src.path].add(dst.path)
            fan_in[dst.path].add(src.path)

    most_depended = sorted(fan_in.items(), key=lambda kv: -len(kv[1]))[:10]
    return {
        "internal_edges": internal_edges,
        "external_packages": dict(external_counter.most_common()),
        "most_depended_on": [{"path": p, "dependents": len(s)} for p, s in most_depended],
        "internal_dependency_count": len(internal_edges),
        "external_package_count": len(external_counter),
    }
