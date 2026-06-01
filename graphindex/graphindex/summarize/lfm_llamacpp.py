"""LFM2.5-1.2B-Instruct summarizer backed by the in-process llama.cpp engine.

Asks the model for a concise one-sentence summary plus comma-separated tags,
parsing a lightweight ``SUMMARY: ... / TAGS: ...`` response. Falls back to the
heuristic summarizer for any node that errors or returns garbage, so a flaky
generation never breaks the pipeline.
"""

from __future__ import annotations

from ..config import Config
from ..engine.llama_engine import LlamaEngine
from ..graph.model import Node
from .base import Summarizer
from .fallback import HeuristicSummarizer

_SYSTEM = (
    "You are a senior software engineer documenting a codebase. "
    "Given a code symbol, reply with exactly two lines:\n"
    "SUMMARY: <one concise sentence describing what it does>\n"
    "TAGS: <3-6 short lowercase comma-separated keywords>"
)


class LFMSummarizer(Summarizer):
    name = "lfm2.5-1.2b-instruct"

    def __init__(self, cfg: Config, engine: LlamaEngine | None = None):
        self.cfg = cfg
        self.engine = engine or LlamaEngine(cfg)
        self._fallback = HeuristicSummarizer()

    def available(self) -> bool:
        # Side-effect free: do not trigger a download here.
        if not LlamaEngine.runtime_available():
            return False
        return self.engine.local_chat_model() is not None

    def _prompt(self, node: Node) -> str:
        code = node.code[:1600] if node.code else node.signature
        return (f"Language: {node.language}\nKind: {node.kind}\n"
                f"Name: {node.name}\nPath: {node.path}\n\nCode:\n{code}")

    def summarize(self, node: Node) -> tuple[str, list[str]]:
        try:
            raw = self.engine.chat(_SYSTEM, self._prompt(node),
                                   max_tokens=self.cfg.summary_max_tokens)
            summary, tags = self._parse(raw)
            if not summary:
                raise ValueError("empty summary")
            if not tags:
                _, tags = self._fallback.summarize(node)
            return summary, tags
        except Exception:
            return self._fallback.summarize(node)

    @staticmethod
    def _parse(raw: str) -> tuple[str, list[str]]:
        summary, tags = "", []
        for line in raw.splitlines():
            low = line.strip()
            if low.upper().startswith("SUMMARY:"):
                summary = low.split(":", 1)[1].strip()
            elif low.upper().startswith("TAGS:"):
                tags = [t.strip().lower() for t in low.split(":", 1)[1].split(",")
                        if t.strip()]
        if not summary:
            summary = raw.strip().split("\n")[0][:200]
        return summary, tags[:8]
