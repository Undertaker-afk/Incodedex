"""Dead-code detection: definitions with no inbound references.

A function/method/class is flagged ``dead_code`` when nothing in the graph
calls, imports, references or inherits from it. To limit false positives we
exclude: entrypoints (``main``), dunder / test methods, exported-looking names,
and anything referenced by an unresolved external (best-effort). Flags add a
purple outline in the UI; this never deletes code.
"""

from __future__ import annotations

from ..graph.model import EdgeKind, Graph, NodeKind
from ..storage.db import GraphDB

_DEF = {NodeKind.FUNCTION.value, NodeKind.METHOD.value, NodeKind.CLASS.value,
        NodeKind.INTERFACE.value}
_INBOUND = {EdgeKind.CALLS.value, EdgeKind.IMPORTS.value,
            EdgeKind.REFERENCES.value, EdgeKind.INHERITS.value}
_KEEP_NAMES = {"main", "__init__", "__main__", "setup", "run", "handler",
               "index", "default"}


def _is_entrypointish(name: str) -> bool:
    if name in _KEEP_NAMES:
        return True
    if name.startswith("__") and name.endswith("__"):
        return True
    if name.startswith("test") or name.endswith("Test"):
        return True
    return False


def flag_dead_code_graph(graph: Graph) -> list[str]:
    """Flag dead-code nodes in an in-memory graph. Returns flagged ids."""
    inbound: dict[str, int] = {nid: 0 for nid in graph.nodes}
    for e in graph.edges.values():
        if e.kind in _INBOUND and e.dst in inbound:
            inbound[e.dst] += 1
    flagged = []
    for n in graph.nodes.values():
        if n.kind not in _DEF or _is_entrypointish(n.name):
            continue
        if inbound.get(n.id, 0) == 0:
            if "dead_code" not in n.flags:
                n.flags.append("dead_code")
            flagged.append(n.id)
    return flagged


def find_dead_code(db: GraphDB) -> list[dict]:
    """Query dead-code candidates from a persisted graph.

    Loads all inbound edge targets once (O(E)) instead of an edges_to() query
    per node (the previous N+1 pattern).
    """
    inbound_dsts = {e.dst for e in db.iter_edges() if e.kind in _INBOUND}
    out = []
    for n in db.iter_nodes():
        if n.kind not in _DEF or _is_entrypointish(n.name):
            continue
        if n.id not in inbound_dsts:
            out.append({"id": n.id, "name": n.name, "kind": n.kind,
                        "path": n.path, "line": n.start_line})
    return out
