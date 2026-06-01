"""Tools the investigation agents use to read the index and source code.

These are deliberately *compact*: they return only what an agent needs to reason,
which is the whole point of graphindex — let a coding agent understand a codebase
by reading tiny structured excerpts instead of whole files, saving tokens.
"""

from __future__ import annotations

from pathlib import Path

from ..graph.model import EdgeKind
from ..graph.resolver import call_hierarchy, find_references, inheritance
from ..search import SearchEngine, parse_query


def _node_brief(n) -> dict:
    return {"id": n.id, "kind": n.kind, "name": n.name, "path": n.path,
            "line": n.start_line, "signature": n.signature, "params": n.params,
            "summary": n.summary, "tags": n.tags}


class AgentTools:
    """Read-only access to the graph index + source, used by agents."""

    def __init__(self, cfg, db, vectors, embedder):
        self.cfg = cfg
        self.db = db
        self.search_engine = SearchEngine(db, vectors, embedder)
        self.files_read = 0
        self.nodes_inspected = 0
        self.source_bytes = 0  # bytes of source the index let us avoid resending

    def search(self, query: str, mode: str = "hybrid", k: int = 6) -> list[dict]:
        modes = {"semantic": dict(semantic=True), "regex": dict(regex=True),
                 "fuzzy": dict(fuzzy=True), "text": {},
                 "hybrid": dict(semantic=True, fuzzy=True)}.get(
                     mode, dict(semantic=True, fuzzy=True))
        q = parse_query(query, top_k=k, **modes)
        out = []
        for r in self.search_engine.search(q):
            self.nodes_inspected += 1
            d = _node_brief(r.node)
            d["score"] = round(r.score, 3)
            out.append(d)
        return out

    def structure(self, node_id: str) -> dict:
        """A node plus its graph neighborhood (callers/callees/inherits/refs)."""
        n = self.db.get_node(node_id)
        if not n:
            return {"error": "not found", "id": node_id}
        self.nodes_inspected += 1
        ch = call_hierarchy(self.db, node_id)
        inh = inheritance(self.db, node_id)
        refs = find_references(self.db, node_id)
        imports = [self.db.get_node(e.dst) for e in self.db.edges_from(node_id, EdgeKind.IMPORTS.value)]
        brief = _node_brief(n)
        brief.update({
            "callers": [_node_brief(x) for x in ch["callers"][:8]],
            "callees": [_node_brief(x) for x in ch["callees"][:8]],
            "inherits_from": [_node_brief(x) for x in inh["ancestors"][:8]],
            "subclasses": [_node_brief(x) for x in inh["descendants"][:8]],
            "referenced_by": [_node_brief(x) for x in refs[:8]],
            "imports": [_node_brief(x) for x in imports if x][:8],
        })
        return brief

    def read_source(self, path: str, start: int = 1, end: int | None = None,
                    max_lines: int = 60) -> dict:
        full = self.cfg.repo_path / path
        try:
            lines = full.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return {"error": "cannot read", "path": path}
        self.files_read += 1
        s = max(0, (start or 1) - 1)
        e = min(len(lines), (end or s + max_lines), s + max_lines)
        text = "\n".join(lines[s:e])
        self.source_bytes += len(text)
        return {"path": path, "start": s + 1, "end": e, "code": text}
