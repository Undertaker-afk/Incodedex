"""Core graph data model: nodes, edges, and their enumerations.

Nodes represent files and code symbols; edges represent structural and
semantic relationships. These dataclasses are the lingua franca shared by the
parser, resolver, storage, search, and API layers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class NodeKind(str, Enum):
    REPO = "repo"
    DIRECTORY = "directory"
    FILE = "file"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"
    INTERFACE = "interface"
    EXTERNAL = "external"  # external package / unresolved import target


class EdgeKind(str, Enum):
    CONTAINS = "contains"      # file/dir contains symbol
    DEFINES = "defines"        # scope defines symbol
    IMPORTS = "imports"        # module imports another module/symbol
    CALLS = "calls"            # function calls function
    INHERITS = "inherits"      # class inherits base / implements interface
    REFERENCES = "references"  # symbol references another symbol
    SIMILAR = "similar"        # semantic similarity edge (embeddings)


class NodeState(str, Enum):
    """Lifecycle states streamed to the UI (drives node colour)."""

    DISCOVERED = "discovered"   # gray
    PARSED = "parsed"           # yellow
    EMBEDDED = "embedded"       # blue
    SUMMARIZED = "summarized"   # green
    HUB = "hub"                 # red (high degree)
    UNRESOLVED = "unresolved"   # orange


# Colour map mirrored on the frontend; kept here as the single source of truth.
STATE_COLORS = {
    NodeState.DISCOVERED: "#9aa0a6",
    NodeState.PARSED: "#f2c744",
    NodeState.EMBEDDED: "#4f8ff7",
    NodeState.SUMMARIZED: "#3fb950",
    NodeState.HUB: "#f85149",
    NodeState.UNRESOLVED: "#f0883e",
}
WARNING_OUTLINE = "#a371f7"  # purple outline for duplicate / dead-code flags


def make_node_id(kind: str, path: str, name: str = "", line: int = 0) -> str:
    """Deterministic, collision-resistant node id."""
    raw = f"{kind}|{path}|{name}|{line}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class Node:
    id: str
    kind: str
    name: str
    path: str                       # repo-relative file path
    language: str = ""
    start_line: int = 0
    end_line: int = 0
    signature: str = ""             # e.g. def foo(a, b) / class Bar(Base)
    params: str = ""                # full parameter setup, e.g. "(a: int, b=2)"
    search_string: str = ""         # canonical searchable text used for embedding
    type_hint: str = ""             # resolved type (for type disambiguation)
    code: str = ""                  # raw symbol source (not always persisted)
    summary: str = ""               # LFM2.5 summary
    tags: list[str] = field(default_factory=list)
    state: str = NodeState.DISCOVERED.value
    degree: int = 0
    flags: list[str] = field(default_factory=list)  # e.g. ["dead_code", "duplicate"]
    commit: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    weight: float = 1.0
    resolved: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.src}->{self.dst}:{self.kind}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d


@dataclass
class Graph:
    """In-memory graph container used during a build."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)

    def add_node(self, node: Node) -> Node:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        return existing

    def add_edge(self, edge: Edge) -> Edge:
        self.edges[edge.id] = edge
        return edge

    def compute_degrees(self) -> None:
        for n in self.nodes.values():
            n.degree = 0
        for e in self.edges.values():
            if e.src in self.nodes:
                self.nodes[e.src].degree += 1
            if e.dst in self.nodes:
                self.nodes[e.dst].degree += 1

    def __len__(self) -> int:
        return len(self.nodes)
