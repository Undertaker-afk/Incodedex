"""Summarizer interface."""

from __future__ import annotations

import abc

from ..graph.model import Node


class Summarizer(abc.ABC):
    name: str = "summarizer"

    @abc.abstractmethod
    def summarize(self, node: Node) -> tuple[str, list[str]]:
        """Return ``(summary, tags)`` for a node."""

    def available(self) -> bool:  # pragma: no cover - overridden where relevant
        return True
