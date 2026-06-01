"""Summarizer backed by huggingface_hub InferenceClient (chat_completion)."""

from __future__ import annotations

from ..config import Config
from ..engine.hf_client import HFInferenceEngine
from ..graph.model import Node
from .base import Summarizer
from .fallback import HeuristicSummarizer
from .lfm_llamacpp import _SYSTEM


class HFSummarizer(Summarizer):
    name = "hf-inference-chat"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.engine = HFInferenceEngine(cfg)
        self._fallback = HeuristicSummarizer()

    def available(self) -> bool:
        return self.engine.available()

    def summarize(self, node: Node) -> tuple[str, list[str]]:
        code = node.code[:1600] if node.code else node.signature
        prompt = (f"Language: {node.language}\nKind: {node.kind}\n"
                  f"Name: {node.name}\nPath: {node.path}\n\nCode:\n{code}")
        try:
            from .lfm_llamacpp import LFMSummarizer
            raw = self.engine.chat(_SYSTEM, prompt, max_tokens=self.cfg.summary_max_tokens)
            summary, tags = LFMSummarizer._parse(raw)
            if not summary:
                raise ValueError("empty")
            if not tags:
                _, tags = self._fallback.summarize(node)
            return summary, tags
        except Exception:
            return self._fallback.summarize(node)
