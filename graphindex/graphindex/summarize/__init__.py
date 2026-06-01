"""Summarization backends (LFM2.5 via llama.cpp, heuristic fallback)."""

from __future__ import annotations

from ..config import Config
from .base import Summarizer
from .fallback import HeuristicSummarizer


def get_summarizer(cfg: Config, engine=None) -> Summarizer:
    backend = cfg.backend
    if backend == "hf":
        from .hf_inference import HFSummarizer
        return HFSummarizer(cfg)
    if backend in ("auto", "llamacpp"):
        try:
            from .lfm_llamacpp import LFMSummarizer
            summ = LFMSummarizer(cfg, engine=engine)
            if summ.available():
                return summ
            if backend == "llamacpp":
                return summ
        except Exception:
            if backend == "llamacpp":
                raise
    return HeuristicSummarizer()
