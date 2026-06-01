"""Language breakdown statistics over the indexed graph."""

from __future__ import annotations

from collections import Counter

from ..graph.model import NodeKind
from ..storage.db import GraphDB


def language_breakdown(db: GraphDB) -> dict:
    file_langs: Counter = Counter()
    symbol_langs: Counter = Counter()
    for n in db.iter_nodes():
        if n.kind == NodeKind.FILE.value:
            file_langs[n.language or "unknown"] += 1
        elif n.kind in {NodeKind.FUNCTION.value, NodeKind.METHOD.value,
                        NodeKind.CLASS.value, NodeKind.INTERFACE.value}:
            symbol_langs[n.language or "unknown"] += 1
    total_files = sum(file_langs.values()) or 1
    return {
        "files_by_language": dict(file_langs.most_common()),
        "symbols_by_language": dict(symbol_langs.most_common()),
        "language_share": {
            lang: round(100 * cnt / total_files, 1)
            for lang, cnt in file_langs.most_common()
        },
    }
