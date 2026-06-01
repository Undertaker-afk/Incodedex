"""Grounded codebase question-answering (retrieval-augmented generation).

Pipeline:
1. LFM2.5 rewrites the user's question into focused search queries.
2. Queries run through the Qwen3 embedding index (+ fuzzy/text fallback).
3. The top symbols' source is read from disk for grounding.
4. LFM2.5 produces an answer constrained to the retrieved context, citing
   ``[ref N]`` markers that map back to file paths, line ranges and node ids.

Degrades gracefully: if no chat model is available it returns an extractive
answer assembled from the retrieved snippets/summaries.
"""

from .asker import AskEngine, Answer, Reference  # noqa: F401
from .llm import get_chat  # noqa: F401
