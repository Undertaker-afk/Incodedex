"""Duplicate / near-duplicate code detection via embedding similarity.

Two strategies, combined:

* **Exact / structural** — identical normalized source (whitespace-collapsed)
  for function/method nodes is an exact duplicate.
* **Near-duplicate** — high cosine similarity between node embeddings flags
  copy-paste-with-edits. Uses whatever vectors are already in the store.

Flagged nodes get a ``duplicate`` entry in ``node.flags`` (rendered as a purple
outline in the UI) and ``similar`` edges connect the pair.
"""

from __future__ import annotations

import re

from ..graph.model import Edge, EdgeKind, Graph, NodeKind
from ..storage.vectors import VectorStore

_DEF = {NodeKind.FUNCTION.value, NodeKind.METHOD.value}
_WS = re.compile(r"\s+")


def _normalize(code: str) -> str:
    return _WS.sub(" ", code or "").strip()


def _structural_key(code: str, name: str) -> str:
    """Whitespace-normalized body with the symbol's own name neutralized,
    so a copy-pasted function with a different name still matches."""
    norm = _normalize(code)
    if name:
        norm = re.sub(rf"\b{re.escape(name)}\b", "_SYM_", norm)
    return norm


def flag_duplicates(graph: Graph, vectors: VectorStore, threshold: float = 0.92,
                    min_chars: int = 80) -> int:
    """Flag duplicate function/method nodes in ``graph``. Returns pair count."""
    nodes = [n for n in graph.nodes.values()
             if n.kind in _DEF and len(n.code or "") >= min_chars]
    pairs = 0

    # exact structural duplicates (name-insensitive, catches renamed copies)
    by_norm: dict[str, list[str]] = {}
    for n in nodes:
        by_norm.setdefault(_structural_key(n.code, n.name), []).append(n.id)
    for ids in by_norm.values():
        if len(ids) > 1:
            for nid in ids:
                if "duplicate" not in graph.nodes[nid].flags:
                    graph.nodes[nid].flags.append("duplicate")
            for other in ids[1:]:
                graph.add_edge(Edge(src=ids[0], dst=other, kind=EdgeKind.SIMILAR.value,
                                    weight=1.0, extra={"kind": "exact"}))
                pairs += 1

    # near-duplicates via embeddings (only if vectors present)
    if len(vectors) and threshold < 1.0:
        seen: set[tuple[str, str]] = set()
        ids_set = {n.id for n in nodes}
        for n in nodes:
            # O(1) vector lookup via the public accessor (no internals/scan)
            vec = vectors.get_vector(n.id)
            if vec is None:
                continue
            for other_id, score in vectors.search(vec, top_k=5):
                if other_id == n.id or other_id not in ids_set:
                    continue
                if score < threshold:
                    continue
                key = tuple(sorted((n.id, other_id)))
                if key in seen:
                    continue
                seen.add(key)
                for nid in key:
                    if "duplicate" not in graph.nodes[nid].flags:
                        graph.nodes[nid].flags.append("duplicate")
                graph.add_edge(Edge(src=key[0], dst=key[1], kind=EdgeKind.SIMILAR.value,
                                    weight=float(score), extra={"kind": "near"}))
                pairs += 1
    return pairs
