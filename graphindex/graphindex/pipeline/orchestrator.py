"""The indexing pipeline.

Implements the end-to-end flow and streams progress as events:

1. scan repo (honouring .gitignore / .graphignore)
2. parse files (tree-sitter) and build raw nodes + edges
3. resolve references (calls / inheritance / imports) -> edges + external nodes
4. compute degrees and flag hubs
5. embed nodes (Qwen3 / fallback) -> vector store
6. summarize + tag nodes (LFM2.5 / fallback)
7. persist to SQLite + FAISS
8. record health metrics

Each node is announced when discovered (gray) and updated as it advances:
parsed (yellow) -> embedded (blue) -> summarized (green); hubs go red,
unresolved references orange, and duplicate/dead-code flags add a purple
outline (the latter applied by the analysis layer).
"""

from __future__ import annotations

import time
import uuid

import numpy as np

from ..analysis.deadcode import flag_dead_code_graph
from ..analysis.duplicates import flag_duplicates
from ..chunking import embedding_text
from ..config import Config
from ..embedding import get_embedder
from ..graph.builder import build_file
from ..graph.model import Edge, Graph, Node, NodeKind, NodeState
from ..graph.resolver import resolve_references
from ..parsing.symbols import extract_symbols
from ..scanner.walker import RepoScanner, current_commit
from ..storage.db import GraphDB
from ..storage.vectors import VectorStore
from ..summarize import get_summarizer
from . import events as E
from .events import EventBus

_EMBEDDABLE = {NodeKind.FILE.value, NodeKind.CLASS.value, NodeKind.INTERFACE.value,
               NodeKind.FUNCTION.value, NodeKind.METHOD.value}
_SUMMARIZABLE = _EMBEDDABLE


class Indexer:
    def __init__(self, cfg: Config, bus: EventBus | None = None,
                 embedder=None, summarizer=None, do_summarize: bool = True,
                 do_embed: bool = True):
        self.cfg = cfg
        self.bus = bus or EventBus()
        self.cfg.ensure_dirs()
        self.db = GraphDB(cfg.db_path)
        self.embedder = embedder if embedder is not None else get_embedder(cfg)
        self.dim = getattr(self.embedder, "dim", cfg.embed_dim) or cfg.embed_dim
        self.vectors = VectorStore(cfg.vectors_path, self.dim)
        self.summarizer = summarizer if summarizer is not None else get_summarizer(cfg)
        self.do_summarize = do_summarize
        self.do_embed = do_embed
        self.commit = current_commit(cfg.repo_path)

    # -- helpers ----------------------------------------------------------
    def _emit_node_add(self, node: Node) -> None:
        self.bus.emit(E.NODE_ADD, id=node.id, label=node.name, kind=node.kind,
                      path=node.path, language=node.language, state=node.state,
                      group=node.path or node.kind)

    def _emit_node_update(self, node: Node) -> None:
        self.bus.emit(E.NODE_UPDATE, id=node.id, state=node.state,
                      degree=node.degree, is_hub=node.degree >= self.cfg.hub_degree_threshold,
                      flags=node.flags, summary=node.summary, tags=node.tags)

    def _emit_edge(self, edge: Edge) -> None:
        self.bus.emit(E.EDGE_ADD, id=edge.id, source=edge.src, target=edge.dst,
                      kind=edge.kind, resolved=edge.resolved)

    # -- main entrypoint --------------------------------------------------
    def index(self, only_changed: list[str] | None = None) -> dict:
        run_id = uuid.uuid4().hex[:12]
        t0 = time.time()
        graph = Graph()
        all_refs = []
        errors = 0
        scanner = RepoScanner(self.cfg.repo_path, self.cfg.max_file_bytes)

        # ---- phase 1+2: scan & parse ----
        self.bus.emit(E.PHASE, phase="scan", message="Scanning repository")
        files = list(scanner.scan())
        if only_changed is not None:
            changed = set(only_changed)
            files = [f for f in files if f.rel_path in changed]
        self.bus.emit(E.LOG, message=f"Discovered {len(files)} source files")

        self.bus.emit(E.PHASE, phase="parse", message="Parsing & building graph")
        for rec in files:
            try:
                source = open(rec.abs_path, "rb").read()
                parsed = extract_symbols(rec.grammar, source)
            except Exception:
                errors += 1
                continue
            fb = build_file(rec, parsed, commit=self.commit)
            # announce discovered (gray), then mark parsed (yellow)
            for n in fb.nodes:
                graph.add_node(n)
                self._emit_node_add(n)
            for n in fb.nodes:
                # canonical searchable text (also the embedding input) — stored
                if n.kind in _EMBEDDABLE:
                    n.search_string = embedding_text(n)
                n.state = NodeState.PARSED.value
                self._emit_node_update(n)
            for e in fb.edges:
                graph.add_edge(e)
                self._emit_edge(e)
            all_refs.extend(fb.refs)
            self.db.upsert_file(rec.rel_path, rec.language, rec.size, rec.mtime,
                                rec.sha, self.commit)

        # ---- phase 3: resolve references ----
        self.bus.emit(E.PHASE, phase="resolve", message="Resolving references")
        stats = resolve_references(graph, all_refs)
        for ext in stats.external_nodes:
            self._emit_node_add(ext)
            self._emit_node_update(ext)
        for e in graph.edges.values():
            self._emit_edge(e)

        # ---- phase 4: degrees & hubs ----
        graph.compute_degrees()
        for n in graph.nodes.values():
            if n.degree >= self.cfg.hub_degree_threshold and n.kind != NodeKind.EXTERNAL.value:
                if NodeState.UNRESOLVED.value != n.state:
                    pass  # keep lifecycle state; hub flagged via degree in UI
            self._emit_node_update(n)

        # ---- phase 5: embed ----
        embeddable = [n for n in graph.nodes.values() if n.kind in _EMBEDDABLE]
        if self.do_embed and embeddable:
            self.bus.emit(E.PHASE, phase="embed", message="Embedding nodes")
            self._embed_nodes(embeddable)

        # ---- phase 6: summarize ----
        summarizable = [n for n in graph.nodes.values() if n.kind in _SUMMARIZABLE]
        if self.do_summarize and summarizable:
            self.bus.emit(E.PHASE, phase="summarize", message="Summarizing & tagging")
            for n in summarizable:
                try:
                    summary, tags = self.summarizer.summarize(n)
                    n.summary, n.tags = summary, tags
                except Exception:
                    errors += 1
                n.state = NodeState.SUMMARIZED.value
                self._emit_node_update(n)

        # ---- analysis overlays: duplicates + dead code (purple outline) ----
        self.bus.emit(E.PHASE, phase="analyze", message="Detecting duplicates & dead code")
        try:
            flag_duplicates(graph, self.vectors, self.cfg.duplicate_similarity)
        except Exception:
            pass
        try:
            flag_dead_code_graph(graph)
        except Exception:
            pass
        for n in graph.nodes.values():
            if n.flags:
                self._emit_node_update(n)

        # ---- phase 7: persist ----
        self.bus.emit(E.PHASE, phase="persist", message="Persisting graph")
        self.db.upsert_nodes(graph.nodes.values())
        self.db.upsert_edges(graph.edges.values())
        self.vectors.save()

        # ---- phase 8: health ----
        elapsed = time.time() - t0
        n_nodes, n_edges = len(graph.nodes), len(graph.edges)
        metrics = {
            "elapsed_sec": round(elapsed, 3),
            "files": len(files),
            "nodes": n_nodes,
            "edges": n_edges,
            "nodes_per_sec": round(n_nodes / elapsed, 1) if elapsed else 0,
            "errors": errors,
            "calls_resolved": stats.calls_resolved,
            "calls_unresolved": stats.calls_unresolved,
            "imports_external": stats.imports_external,
            "embedder": getattr(self.embedder, "name", "?"),
            "summarizer": getattr(self.summarizer, "name", "?"),
            "vector_backend": self.vectors.backend,
        }
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                self.db.record_health(run_id, k, v)
        self.db.set_meta("last_run", {"run_id": run_id, "commit": self.commit, **metrics})
        self.db.set_meta("embed_dim", self.dim)
        self.bus.emit(E.STATS, **metrics)
        self.bus.emit(E.DONE, run_id=run_id, **metrics)
        return metrics

    # -- embedding --------------------------------------------------------
    def _embed_nodes(self, nodes: list[Node]) -> None:
        batch = max(1, self.cfg.embed_batch)
        for i in range(0, len(nodes), batch):
            chunk = nodes[i:i + batch]
            texts = [n.search_string or embedding_text(n) for n in chunk]
            try:
                mat = self.embedder.embed(texts)
            except Exception:
                continue
            for n, vec in zip(chunk, mat):
                self.vectors.add(n.id, np.asarray(vec, dtype="float32"))
                n.state = NodeState.EMBEDDED.value
                self._emit_node_update(n)
