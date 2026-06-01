"""Turn parsed files into graph nodes + edges and collect raw references.

This produces *intra-file* structure immediately (file contains symbol, scope
defines symbol) and records cross-file *raw references* (calls, inheritance,
imports) by name. The :mod:`graphindex.graph.resolver` later turns those raw
references into resolved edges against the global symbol index.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..parsing.symbols import ParsedFile
from ..scanner.walker import FileRecord
from .model import Edge, EdgeKind, Node, NodeKind, make_node_id


@dataclass
class RawRef:
    """An unresolved, by-name reference emitted during graph build."""

    src_id: str
    name: str
    kind: str  # "call" | "inherit" | "import"
    extra: dict = field(default_factory=dict)


@dataclass
class FileBuild:
    file_node: Node
    nodes: list[Node]
    edges: list[Edge]
    refs: list[RawRef]


def build_file(record: FileRecord, parsed: ParsedFile, commit: str = "") -> FileBuild:
    nodes: list[Node] = []
    edges: list[Edge] = []
    refs: list[RawRef] = []

    file_node = Node(
        id=make_node_id(NodeKind.FILE.value, record.rel_path),
        kind=NodeKind.FILE.value,
        name=record.rel_path.rsplit("/", 1)[-1],
        path=record.rel_path,
        language=record.language,
        start_line=1,
        signature=record.rel_path,
        commit=commit,
        extra={"size": record.size},
    )
    nodes.append(file_node)

    # Map qualified symbol name -> node id within this file for parent linkage.
    qual_to_id: dict[str, str] = {}

    for sym in parsed.symbols:
        node_id = make_node_id(sym.kind, record.rel_path, sym.qualified_name, sym.start_line)
        qual_to_id[sym.qualified_name] = node_id
        node = Node(
            id=node_id,
            kind=sym.kind,
            name=sym.name,
            path=record.rel_path,
            language=record.language,
            start_line=sym.start_line,
            end_line=sym.end_line,
            signature=sym.signature,
            params=sym.params,
            code=sym.code,
            commit=commit,
            extra={"qualified_name": sym.qualified_name},
        )
        nodes.append(node)

        # containment / definition edges
        parent_id = qual_to_id.get(sym.parent) if sym.parent else None
        if parent_id:
            edges.append(Edge(src=parent_id, dst=node_id, kind=EdgeKind.DEFINES.value))
        else:
            edges.append(Edge(src=file_node.id, dst=node_id, kind=EdgeKind.CONTAINS.value))

        # raw references for later resolution
        for callee in sym.calls:
            refs.append(RawRef(src_id=node_id, name=callee, kind="call"))
        for base in sym.bases:
            refs.append(RawRef(src_id=node_id, name=base, kind="inherit"))

    # imports are attributed to the file node
    for imp in parsed.imports:
        for mod in imp.modules:
            refs.append(RawRef(src_id=file_node.id, name=mod, kind="import",
                               extra={"raw": imp.raw}))

    return FileBuild(file_node=file_node, nodes=nodes, edges=edges, refs=refs)
