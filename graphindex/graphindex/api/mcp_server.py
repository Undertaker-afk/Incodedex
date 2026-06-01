"""Model Context Protocol server exposing graphindex over stdio.

Lets MCP-aware agents (Claude, IDEs, etc.) query the index as tools:
``search_code``, ``get_node``, ``find_references``, ``call_hierarchy``,
``inheritance``, ``dead_code`` and ``stats``. Requires the optional ``mcp``
package (``pip install graphindex[mcp]``); imported lazily so the rest of the
app has no hard dependency on it.
"""

from __future__ import annotations

from ..analysis.deadcode import find_dead_code
from ..analysis.dependencies import dependency_graph
from ..analysis.languages import language_breakdown
from ..config import Config
from ..embedding import get_embedder
from ..graph.resolver import call_hierarchy, find_references, inheritance
from ..qa import AskEngine, get_chat
from ..search import SearchEngine, parse_query
from ..storage.db import GraphDB
from ..storage.vectors import VectorStore


def build_server(cfg: Config):
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "The 'mcp' package is required for the MCP server. "
            "Install it with: pip install graphindex[mcp]") from exc

    db = GraphDB(cfg.db_path)
    dim = db.get_meta("embed_dim", cfg.embed_dim) or cfg.embed_dim
    vectors = VectorStore(cfg.vectors_path, dim)
    embedder = get_embedder(cfg)
    engine = SearchEngine(db, vectors, embedder)
    ask_engine = AskEngine(cfg, db, vectors, embedder, chat=get_chat(cfg))

    mcp = FastMCP("graphindex")

    @mcp.tool()
    def search_code(query: str, regex: bool = False, semantic: bool = True,
                    fuzzy: bool = False, k: int = 20) -> list[dict]:
        """Search the indexed codebase (regex/semantic/fuzzy/filtered)."""
        q = parse_query(query, regex=regex, semantic=semantic, fuzzy=fuzzy, top_k=k)
        return [r.to_dict() for r in engine.search(q)]

    @mcp.tool()
    def ask_codebase(question: str, k: int = 8) -> dict:
        """Ask a natural-language question; returns a grounded answer with
        file/index references (RAG: rewrite -> retrieve -> read -> answer)."""
        return ask_engine.ask(question, k=k).to_dict()

    @mcp.tool()
    def get_node(node_id: str) -> dict:
        """Get a node's details by id."""
        n = db.get_node(node_id)
        return n.to_dict() if n else {"error": "not found"}

    @mcp.tool()
    def references(node_id: str) -> list[dict]:
        """Find all references to a symbol node."""
        return [x.to_dict() for x in find_references(db, node_id)]

    @mcp.tool()
    def calls(node_id: str) -> dict:
        """Call hierarchy (callers + callees) for a function/method node."""
        ch = call_hierarchy(db, node_id)
        return {"callers": [x.to_dict() for x in ch["callers"]],
                "callees": [x.to_dict() for x in ch["callees"]]}

    @mcp.tool()
    def class_hierarchy(node_id: str) -> dict:
        """Ancestors + descendants for a class/interface node."""
        inh = inheritance(db, node_id)
        return {"ancestors": [x.to_dict() for x in inh["ancestors"]],
                "descendants": [x.to_dict() for x in inh["descendants"]]}

    @mcp.tool()
    def dead_code() -> list[dict]:
        """List functions/classes with no inbound references."""
        return find_dead_code(db)

    @mcp.tool()
    def stats() -> dict:
        """Language breakdown + dependency summary."""
        return {"languages": language_breakdown(db),
                "dependencies": dependency_graph(db)}

    return mcp


def run(cfg: Config) -> None:
    build_server(cfg).run()
