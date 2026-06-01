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
    # The chat model is independent of the embedding backend: if the LFM2.5
    # GGUF and llama.cpp runtime are present we can answer questions even when
    # embeddings use the fast fallback (e.g. on a CPU host where embedding a
    # large repo with the real model would be slow). Disable with backend="none".
    if backend == "none":
        return None
    try:
        from ..engine.llama_engine import LlamaEngine
        eng = LlamaEngine(cfg)
        if LlamaEngine.runtime_available() and eng.chat_model_path() is not None:
            return eng
    except Exception:
        return None
    return None
