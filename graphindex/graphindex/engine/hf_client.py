"""Hugging Face ``InferenceClient`` engine (optional, remote or local-server).

``huggingface_hub`` is used for model *download* everywhere in graphindex; this
module additionally exposes its ``InferenceClient`` for *inference*. Unlike the
in-process llama.cpp engine, ``InferenceClient`` makes HTTP calls to either:

* a Hugging Face Inference Provider (set ``GRAPHINDEX_HF_TOKEN`` / ``HF_TOKEN``
  and optionally ``GRAPHINDEX_HF_PROVIDER``), or
* a local OpenAI-compatible server URL (``GRAPHINDEX_HF_ENDPOINT``), e.g. a
  running ``llama_cpp.server``, Ollama, vLLM or TGI.

This makes it a convenient zero-local-compute backend. It is selected with
``backend="hf"``. Embeddings use ``feature_extraction``; summaries use
``chat_completion``.
"""

from __future__ import annotations

import os

import numpy as np

from ..config import Config


def _token() -> str | None:
    return (os.environ.get("GRAPHINDEX_HF_TOKEN") or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN"))


class HFInferenceEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.endpoint = os.environ.get("GRAPHINDEX_HF_ENDPOINT")
        self.provider = os.environ.get("GRAPHINDEX_HF_PROVIDER", "auto")
        self._client = None

    def available(self) -> bool:
        try:
            import huggingface_hub  # noqa: F401
        except Exception:
            return False
        return bool(self.endpoint or _token())

    def _get_client(self):
        if self._client is not None:
            return self._client
        from huggingface_hub import InferenceClient
        if self.endpoint:
            self._client = InferenceClient(model=self.endpoint, token=_token())
        else:
            self._client = InferenceClient(provider=self.provider, token=_token())
        return self._client

    def embed(self, texts: list[str]) -> np.ndarray:
        client = self._get_client()
        vecs = []
        for t in texts:
            out = client.feature_extraction(t, model=self.cfg.embed_model.repo_id)
            arr = np.asarray(out, dtype="float32")
            if arr.ndim == 2:  # token-level -> mean pool
                arr = arr.mean(axis=0)
            vecs.append(arr)
        return np.vstack(vecs)

    def chat(self, system: str, user: str, max_tokens: int = 128) -> str:
        client = self._get_client()
        out = client.chat_completion(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            model=self.cfg.chat_model.repo_id, max_tokens=max_tokens,
            temperature=0.2,
        )
        return out.choices[0].message.content.strip()
