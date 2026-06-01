"""Heuristic summary/tags fallback used when LFM2.5 is unavailable.

Generates a human-readable one-line description and a set of tags from the
node's kind, name (split on camelCase / snake_case), language and signature.
Deterministic and instant — keeps the pipeline and UI fully functional.
"""

from __future__ import annotations

import re

from ..graph.model import Node

_SPLIT = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

_VERB_HINTS = {
    "get": "accessor", "set": "mutator", "is": "predicate", "has": "predicate",
    "build": "factory", "create": "factory", "make": "factory", "parse": "parser",
    "render": "view", "handle": "handler", "run": "runner", "load": "loader",
    "save": "persistence", "delete": "mutation", "update": "mutation",
    "test": "test", "init": "initializer",
}


def split_identifier(name: str) -> list[str]:
    return [w.lower() for w in _SPLIT.findall(name) if w]


class HeuristicSummarizer:
    name = "fallback-heuristic"

    def summarize(self, node: Node) -> tuple[str, list[str]]:
        words = split_identifier(node.name)
        tags: list[str] = [node.kind]
        if node.language:
            tags.append(node.language.lower())
        for w in words:
            if w in _VERB_HINTS:
                tags.append(_VERB_HINTS[w])
        tags.extend(words[:4])

        phrase = " ".join(words) or node.name
        kind = node.kind
        loc = f" in {node.path}" if node.path else ""
        if kind in ("function", "method"):
            summary = f"{kind.capitalize()} '{node.name}' ({phrase}){loc}."
        elif kind in ("class", "interface"):
            summary = f"{kind.capitalize()} '{node.name}' ({phrase}){loc}."
        elif kind == "file":
            summary = f"Source file {node.path} ({node.language})."
        else:
            summary = f"{kind.capitalize()} '{node.name}'{loc}."
        if node.signature and kind != "file":
            summary += f" Signature: {node.signature.strip()[:120]}"

        # dedupe tags, keep order
        seen, out = set(), []
        for t in tags:
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return summary, out[:8]
