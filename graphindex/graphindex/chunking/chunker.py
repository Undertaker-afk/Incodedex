"""Build the text that represents a node for embedding.

A node's embedding text combines its identity (kind, name, signature, path)
with a bounded slice of its source so that semantic search matches both intent
("authentication handler") and implementation details. Long symbols are
truncated by character budget (chunking) to stay within the model context.
"""

from __future__ import annotations

from ..graph.model import Node

_MAX_CHARS = 2000


def chunk_node_text(code: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Split ``code`` into <= ``max_chars`` chunks on line boundaries."""
    if len(code) <= max_chars:
        return [code]
    chunks, cur, size = [], [], 0
    for line in code.splitlines(keepends=True):
        if size + len(line) > max_chars and cur:
            chunks.append("".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


def embedding_text(node: Node, max_chars: int = _MAX_CHARS) -> str:
    """Compose the canonical embedding text for a node (header + first chunk)."""
    header = f"{node.language} {node.kind} {node.name}"
    if node.signature:
        header += f"\n{node.signature}"
    header += f"\npath: {node.path}"
    body = node.code or ""
    first = chunk_node_text(body, max_chars)[0] if body else ""
    text = header + ("\n\n" + first if first else "")
    return text[: max_chars + 256]
