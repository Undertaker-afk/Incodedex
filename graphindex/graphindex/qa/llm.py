"""Chat-LLM provider resolution for QA.

Returns an object exposing ``chat(system, user, max_tokens)`` using the same
model strategy as the rest of graphindex:

* ``llamacpp``/``auto`` -> in-process LFM2.5 via :class:`LlamaEngine`
* ``hf``               -> :class:`HFInferenceEngine`
* otherwise / unavailable -> ``None`` (caller falls back to extractive QA)
"""

from __future__ import annotations

from ..config import Config


def get_chat(cfg: Config):
    backend = cfg.backend
    if backend == "hf":
        try:
            from ..engine.hf_client import HFInferenceEngine
            eng = HFInferenceEngine(cfg)
            return eng if eng.available() else None
        except Exception:
            return None
    if backend in ("auto", "llamacpp"):
        try:
            from ..engine.llama_engine import LlamaEngine
            eng = LlamaEngine(cfg)
            if LlamaEngine.runtime_available() and eng.local_chat_model() is not None:
                return eng
        except Exception:
            return None
    return None
