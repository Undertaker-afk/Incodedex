"""Reference resolution + code-intelligence queries.

Build time: :func:`resolve_references` turns by-name raw references (calls,
inheritance, imports) into concrete graph edges, creating ``external`` nodes
for things that resolve outside the repo (stdlib / third-party) and marking
unresolved references.

Query time (operating on a populated :class:`GraphDB`):
* :func:`goto_definition` – resolve a name/symbol to its defining node(s)
* :func:`find_references` – every node that references a symbol
* :func:`call_hierarchy` – callers (parents) and callees (children)
* :func:`inheritance` – ancestors and descendants of a class/interface
* :func:`resolve_type` – disambiguate identical names by kind/type
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..storage.db import GraphDB
from .builder import RawRef
from .model import Edge, EdgeKind, Graph, Node, NodeKind, NodeState, make_node_id

_DEF_KINDS = {NodeKind.FUNCTION.value, NodeKind.METHOD.value,
              NodeKind.CLASS.value, NodeKind.INTERFACE.value}
_CLASS_KINDS = {NodeKind.CLASS.value, NodeKind.INTERFACE.value}
_MAX_CANDIDATES = 4  # cap fan-out for ambiguous names


@dataclass
class ResolveStats:
    calls_resolved: int = 0
    calls_unresolved: int = 0
    inherits_resolved: int = 0
    imports_internal: int = 0
    imports_external: int = 0
    external_nodes: list[Node] = field(default_factory=list)
    unresolved_node_ids: set[str] = field(default_factory=set)


def _module_path_candidates(path: str) -> list[str]:
    """Dotted/spec forms a file path could be imported as."""
    no_ext = path.rsplit(".", 1)[0]
    dotted = no_ext.replace("/", ".")
    base = no_ext.rsplit("/", 1)[-1]
    return [dotted, no_ext, base]


def resolve_references(graph: Graph, refs: list[RawRef]) -> ResolveStats:
    """Resolve raw references against ``graph`` in place, adding edges/nodes."""
    stats = ResolveStats()

    # name -> definition node ids
    name_index: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        if node.kind in _DEF_KINDS:
            name_index.setdefault(node.name, []).append(node.id)

    # module spec -> file node id (for internal import resolution)
    module_index: dict[str, str] = {}
    file_by_path: dict[str, str] = {}
    for node in graph.nodes.values():
        if node.kind == NodeKind.FILE.value:
            file_by_path[node.path] = node.id
            for cand in _module_path_candidates(node.path):
                module_index.setdefault(cand, node.id)

    external_by_name: dict[str, str] = {}

    def get_external(name: str) -> str:
        if name in external_by_name:
            return external_by_name[name]
        ext = Node(id=make_node_id(NodeKind.EXTERNAL.value, "external", name),
                   kind=NodeKind.EXTERNAL.value, name=name, path="<external>",
                   state=NodeState.UNRESOLVED.value)
        graph.add_node(ext)
        stats.external_nodes.append(ext)
        external_by_name[name] = ext.id
        return ext.id

    for ref in refs:
        if ref.src_id not in graph.nodes:
            continue
        src = graph.nodes[ref.src_id]

        if ref.kind == "call":
            targets = name_index.get(ref.name, [])
            targets = _prefer_same_file(targets, graph, src.path)
            if targets:
                for dst in targets[:_MAX_CANDIDATES]:
                    if dst != ref.src_id:
                        graph.add_edge(Edge(src=ref.src_id, dst=dst,
                                            kind=EdgeKind.CALLS.value))
                stats.calls_resolved += 1
            else:
                stats.calls_unresolved += 1

        elif ref.kind == "inherit":
            targets = [t for t in name_index.get(ref.name, [])
                       if graph.nodes[t].kind in _CLASS_KINDS]
            if targets:
                for dst in targets[:_MAX_CANDIDATES]:
                    graph.add_edge(Edge(src=ref.src_id, dst=dst,
                                        kind=EdgeKind.INHERITS.value))
                stats.inherits_resolved += 1
            else:
                dst = get_external(ref.name)
                graph.add_edge(Edge(src=ref.src_id, dst=dst,
                                    kind=EdgeKind.INHERITS.value, resolved=False))
                stats.unresolved_node_ids.add(dst)

        elif ref.kind == "import":
            internal = None
            if ref.name.startswith("."):  # python relative import
                internal = _resolve_relative(ref.name, src.path, file_by_path)
            if internal is None:
                internal = _match_module(ref.name, module_index)
            if internal:
                graph.add_edge(Edge(src=ref.src_id, dst=internal,
                                    kind=EdgeKind.IMPORTS.value))
                stats.imports_internal += 1
            else:
                dst = get_external(ref.name)
                graph.add_edge(Edge(src=ref.src_id, dst=dst,
                                    kind=EdgeKind.IMPORTS.value, resolved=False))
                stats.imports_external += 1
                stats.unresolved_node_ids.add(dst)

    return stats


def _prefer_same_file(targets: list[str], graph: Graph, path: str) -> list[str]:
    if len(targets) <= 1:
        return targets
    same = [t for t in targets if graph.nodes[t].path == path]
    return same or targets


def _resolve_relative(module: str, src_path: str, file_by_path: dict[str, str]
                      ) -> str | None:
    """Resolve a Python relative import (``.`` / ``..pkg.mod``) to a file node."""
    dots = len(module) - len(module.lstrip("."))
    name = module[dots:]
    src_dir = src_path.split("/")[:-1]
    up = dots - 1  # one dot = current package
    base = src_dir[: len(src_dir) - up] if up <= len(src_dir) else None
    if base is None:
        return None
    suffix = name.split(".") if name else []
    target = base + suffix
    stem = "/".join(target)
    for cand in (f"{stem}.py", f"{stem}/__init__.py",
                 "/".join(base) + "/__init__.py"):
        if cand in file_by_path:
            return file_by_path[cand]
    return None


def _match_module(module: str, module_index: dict[str, str]) -> str | None:
    if module in module_index:
        return module_index[module]
    # try suffix matches: "pkg.mod" where file is "a/pkg/mod.py"
    norm = module.lstrip(".").replace("/", ".")
    for spec, node_id in module_index.items():
        if spec == norm or spec.endswith("." + norm) or norm.endswith("." + spec):
            return node_id
    last = module.replace("/", ".").rsplit(".", 1)[-1]
    return module_index.get(last)


# ---------------------------------------------------------------------------
# Query-time code intelligence (operates on a populated GraphDB)
# ---------------------------------------------------------------------------

def goto_definition(db: GraphDB, name: str, kind: str | None = None,
                    type_hint: str | None = None) -> list[Node]:
    """Resolve ``name`` to its defining node(s), optionally filtered by kind/type."""
    matches = [n for n in db.iter_nodes()
               if n.name == name and n.kind in _DEF_KINDS]
    if kind:
        matches = [n for n in matches if n.kind == kind]
    if type_hint:
        matches = [n for n in matches if n.type_hint == type_hint]
    return matches


def find_references(db: GraphDB, node_id: str) -> list[Node]:
    """Every node that calls/imports/inherits/references the given node."""
    seen: dict[str, Node] = {}
    for edge in db.edges_to(node_id):
        if edge.kind in {EdgeKind.CALLS.value, EdgeKind.IMPORTS.value,
                         EdgeKind.INHERITS.value, EdgeKind.REFERENCES.value}:
            src = db.get_node(edge.src)
            if src:
                seen[src.id] = src
    return list(seen.values())


def call_hierarchy(db: GraphDB, node_id: str) -> dict[str, list[Node]]:
    """Return callers (incoming CALLS) and callees (outgoing CALLS)."""
    callers = [db.get_node(e.src) for e in db.edges_to(node_id, EdgeKind.CALLS.value)]
    callees = [db.get_node(e.dst) for e in db.edges_from(node_id, EdgeKind.CALLS.value)]
    return {
        "callers": [n for n in callers if n],
        "callees": [n for n in callees if n],
    }


def inheritance(db: GraphDB, node_id: str) -> dict[str, list[Node]]:
    """Ancestors (this -> base via INHERITS) and descendants (subclasses)."""
    def _ascend(nid: str, acc: dict[str, Node], depth: int = 0) -> None:
        if depth > 20:
            return
        for e in db.edges_from(nid, EdgeKind.INHERITS.value):
            base = db.get_node(e.dst)
            if base and base.id not in acc:
                acc[base.id] = base
                _ascend(base.id, acc, depth + 1)

    def _descend(nid: str, acc: dict[str, Node], depth: int = 0) -> None:
        if depth > 20:
            return
        for e in db.edges_to(nid, EdgeKind.INHERITS.value):
            sub = db.get_node(e.src)
            if sub and sub.id not in acc:
                acc[sub.id] = sub
                _descend(sub.id, acc, depth + 1)

    ancestors: dict[str, Node] = {}
    descendants: dict[str, Node] = {}
    _ascend(node_id, ancestors)
    _descend(node_id, descendants)
    return {"ancestors": list(ancestors.values()),
            "descendants": list(descendants.values())}


def resolve_type(db: GraphDB, name: str) -> list[Node]:
    """Disambiguate identical names, grouping by kind + type_hint + path."""
    nodes = [n for n in db.iter_nodes() if n.name == name]
    nodes.sort(key=lambda n: (n.kind, n.type_hint, n.path, n.start_line))
    return nodes
