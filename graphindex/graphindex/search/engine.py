"""Unified search engine: regex + semantic + fuzzy + filtered + scoped.

The engine first narrows the candidate set by structural filters (language,
kind, extension, path scope, branch/commit), then scores candidates by the
requested mode(s):

* **regex** – ``re`` match over name/signature/summary (and code if present)
* **fuzzy** – RapidFuzz token-ratio over names (typo / partial tolerant)
* **semantic** – cosine similarity of the query embedding vs node vectors
* **plain text** – case-(in)sensitive substring

When multiple modes are enabled the per-mode scores are combined into a single
ranking. Results carry the matched node plus score and match provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz

from ..graph.model import Node
from ..storage.db import GraphDB
from ..storage.vectors import VectorStore
from .query import Query


@dataclass
class SearchResult:
    node: Node
    score: float
    matched_by: list[str]

    def to_dict(self) -> dict:
        d = self.node.to_dict()
        d.pop("code", None)
        d["score"] = round(self.score, 4)
        d["matched_by"] = self.matched_by
        return d


class SearchEngine:
    def __init__(self, db: GraphDB, vectors: VectorStore | None = None, embedder=None):
        self.db = db
        self.vectors = vectors
        self.embedder = embedder

    # -- candidate filtering ---------------------------------------------
    def _candidates(self, q: Query) -> list[Node]:
        nodes = self.db.iter_nodes()
        out = []
        for n in nodes:
            if q.kind and n.kind != q.kind:
                continue
            if q.language and n.language.lower() != q.language.lower():
                continue
            if q.ext and not n.path.lower().endswith("." + q.ext.lower().lstrip(".")):
                continue
            if q.path and q.path not in n.path:
                continue
            if q.scope and not n.path.startswith(q.scope):
                continue
            if q.branch and n.commit and not n.commit.startswith(q.branch):
                continue
            out.append(n)
        return out

    # -- main -------------------------------------------------------------
    def search(self, q: Query) -> list[SearchResult]:
        candidates = self._candidates(q)
        scores: dict[str, float] = {}
        matched: dict[str, set] = {}
        by_id = {n.id: n for n in candidates}

        def bump(nid: str, score: float, how: str) -> None:
            scores[nid] = max(scores.get(nid, 0.0), score)
            matched.setdefault(nid, set()).add(how)

        text = q.text.strip()

        # If there is no free text, the filtered candidate set IS the result.
        if not text:
            for n in candidates:
                bump(n.id, 0.5, "filter")
        else:
            if q.regex:
                self._regex(text, candidates, q.case_sensitive, bump)
            if q.fuzzy:
                self._fuzzy(text, candidates, bump)
            if q.semantic and self.vectors is not None and self.embedder is not None:
                self._semantic(text, by_id, q.top_k, bump)
            if not (q.regex or q.fuzzy or q.semantic):
                self._plain(text, candidates, q.case_sensitive, bump)

        results = [SearchResult(node=by_id[nid], score=sc, matched_by=sorted(matched[nid]))
                   for nid, sc in scores.items() if nid in by_id]
        results.sort(key=lambda r: (-r.score, r.node.path, r.node.start_line))
        return results[: q.top_k]

    # -- modes ------------------------------------------------------------
    def _regex(self, pattern, nodes, case, bump):
        flags = 0 if case else re.IGNORECASE
        try:
            rx = re.compile(pattern, flags)
        except re.error:
            return
        for n in nodes:
            hay = "\n".join((n.name, n.signature, n.summary, " ".join(n.tags)))
            if rx.search(hay) or (n.code and rx.search(n.code)):
                bump(n.id, 1.0, "regex")

    def _fuzzy(self, text, nodes, bump):
        low = text.lower()
        for n in nodes:
            # case-insensitive: typos/partials shouldn't be defeated by casing
            score = fuzz.token_set_ratio(low, n.name.lower()) / 100.0
            qr = fuzz.partial_ratio(low, (n.signature or "").lower()) / 100.0
            best = max(score, 0.8 * qr)
            if best >= 0.55:
                bump(n.id, best, "fuzzy")

    def _semantic(self, text, by_id, top_k, bump):
        try:
            vec = self.embedder.embed([text])[0]
        except Exception:
            return
        for nid, score in self.vectors.search(np.asarray(vec, dtype="float32"),
                                               top_k=max(top_k * 2, 20)):
            if nid in by_id and score > 0.2:
                bump(nid, float(score), "semantic")

    def _plain(self, text, nodes, case, bump):
        needle = text if case else text.lower()
        for n in nodes:
            hay = "\n".join((n.name, n.signature, n.summary, " ".join(n.tags)))
            if not case:
                hay = hay.lower()
            if needle in hay:
                # weight by where it matched (name > signature)
                name = n.name if case else n.name.lower()
                bump(n.id, 1.0 if needle in name else 0.7, "text")
