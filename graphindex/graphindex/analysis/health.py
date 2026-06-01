"""Index health metrics + automated pruning of stale data."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..graph.model import NodeKind
from ..storage.db import GraphDB
from ..storage.vectors import VectorStore
from ..storage.compsrc import CompSrc


def health_report(db: GraphDB) -> dict:
    last = db.get_meta("last_run", {})
    counts = {}
    for n in db.iter_nodes():
        counts[n.kind] = counts.get(n.kind, 0) + 1
    unresolved = sum(1 for e in db.iter_edges() if not e.resolved)
    return {
        "last_run": last,
        "node_count": db.count_nodes(),
        "edge_count": db.count_edges(),
        "nodes_by_kind": counts,
        "unresolved_edges": unresolved,
        "history": db.health_metrics(),
    }


def prune_deleted_files(cfg: Config, db: GraphDB, vectors: VectorStore | None = None
                        ) -> dict:
    """Remove nodes/edges/vectors for files that no longer exist on disk.

    This is the automated cleanup for deleted files / stale branches.
    """
    removed_files, removed_nodes = [], []
    for path in db.all_file_paths():
        if not (cfg.repo_path / path).exists():
            ids = db.delete_file(path)
            removed_files.append(path)
            removed_nodes.extend(ids)
    if vectors is not None and removed_nodes:
        vectors.remove(set(removed_nodes))
        vectors.save()

    # Prune stale source cache
    compsrc = CompSrc(cfg.repo_path)
    active_ids = {n.id for n in db.iter_nodes()}
    removed_cache = compsrc.prune_stale(active_ids)

    return {"removed_files": removed_files, "removed_nodes": len(removed_nodes), "removed_cache": removed_cache}
