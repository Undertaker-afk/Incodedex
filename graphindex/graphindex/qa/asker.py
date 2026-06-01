"""Grounded RAG over the index: rewrite -> retrieve -> read -> answer."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import Config
from ..graph.model import Node
from ..search import SearchEngine, parse_query

_REWRITE_SYSTEM = (
    "You turn a developer's question about a codebase into code-search queries. "
    "Focus on likely identifiers, function/class names, and programming concepts "
    "that would appear in source code — NOT real-world domain knowledge. "
    "Reply with 1-4 short queries, one per line, no numbering, no prose."
)

_ANSWER_SYSTEM = (
    "You are a precise software engineering assistant. Answer the question using "
    "ONLY the provided context snippets from the codebase. Cite every claim with "
    "the matching [ref N] marker. If the context is insufficient, say so plainly. "
    "Be concise and concrete; mention relevant function/class names."
)


@dataclass
class Reference:
    ref: int
    node_id: str
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    score: float
    snippet: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Answer:
    question: str
    answer: str
    rewritten: list[str] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    backend: str = ""
    grounded: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["references"] = [r.to_dict() for r in self.references]
        return d


class AskEngine:
    def __init__(self, cfg: Config, db, vectors, embedder, chat=None,
                 max_snippet_lines: int = 40):
        self.cfg = cfg
        self.db = db
        self.search = SearchEngine(db, vectors, embedder)
        self.chat = chat
        self.max_snippet_lines = max_snippet_lines

    # -- step 1: rewrite ---------------------------------------------------
    def _rewrite(self, question: str) -> list[str]:
        if self.chat is None:
            return [question]
        try:
            raw = self.chat.chat(_REWRITE_SYSTEM, question, max_tokens=80)
            queries = [ln.strip(" -*\t") for ln in raw.splitlines() if ln.strip()]
            queries = [q for q in queries if 2 <= len(q) <= 120][:4]
            return queries or [question]
        except Exception:
            return [question]

    # -- step 2: retrieve --------------------------------------------------
    _KINDS = ("function", "method", "class", "interface", "file")

    def _retrieve(self, queries: list[str], k: int) -> list[tuple[Node, float]]:
        scored: dict[str, float] = {}
        nodes: dict[str, Node] = {}

        def add(node: Node, score: float) -> None:
            if node.kind in self._KINDS:
                scored[node.id] = max(scored.get(node.id, 0.0), score)
                nodes[node.id] = node

        for q in queries:
            query = parse_query(q, semantic=True, fuzzy=True, top_k=k)
            for r in self.search.search(query):
                add(r.node, r.score)

        # Keyword anchor: ensure question content words that name real symbols
        # are retrieved even when (fallback) embeddings miss the intent.
        words = {w.lower() for q in queries
                 for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", q)}
        stop = {"the", "and", "how", "does", "what", "where", "which", "use",
                "used", "for", "with", "this", "that", "from", "into", "are",
                "function", "method", "class", "code", "make", "work", "works"}
        words -= stop
        if words:
            for n in self.db.iter_nodes():
                if n.kind not in self._KINDS or n.id in scored:
                    continue
                low = n.name.lower()
                if any(w in low or low in w for w in words):
                    add(n, 0.45)

        ranked = sorted(scored.items(), key=lambda kv: -kv[1])[:k]
        return [(nodes[nid], sc) for nid, sc in ranked]

    # -- step 3: read source ----------------------------------------------
    def _snippet(self, node: Node) -> str:
        path = self.cfg.repo_path / node.path
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return node.signature or ""
        start = max(0, (node.start_line or 1) - 1)
        end = node.end_line or node.start_line or len(lines)
        end = min(len(lines), max(end, start + 1), start + self.max_snippet_lines)
        return "\n".join(lines[start:end])

    # -- step 4: answer ----------------------------------------------------
    def ask(self, question: str, k: int = 8) -> Answer:
        rewritten = self._rewrite(question)
        # Always anchor retrieval on the original question too.
        queries = list(dict.fromkeys([*rewritten, question]))
        hits = self._retrieve(queries, k)
        references: list[Reference] = []
        for i, (node, score) in enumerate(hits, start=1):
            references.append(Reference(
                ref=i, node_id=node.id, name=node.name, kind=node.kind,
                path=node.path, start_line=node.start_line, end_line=node.end_line,
                score=round(float(score), 4), snippet=self._snippet(node),
            ))

        backend = getattr(self.chat, "name", None) or (
            self.chat.__class__.__name__ if self.chat else "extractive")

        if self.chat is None or not references:
            return Answer(question=question, rewritten=rewritten,
                          references=references, backend="extractive",
                          grounded=bool(references),
                          answer=self._extractive(question, references))

        context = self._context_block(references)
        user = (f"Question: {question}\n\nContext from the codebase:\n{context}\n\n"
                "Answer with citations like [ref 1].")
        grounded = True
        try:
            answer = self.chat.chat(_ANSWER_SYSTEM, user,
                                    max_tokens=max(256, self.cfg.summary_max_tokens * 3))
            if not answer or not answer.strip():
                raise RuntimeError("empty chat answer")
        except Exception:
            # LLM failed -> degraded extractive answer; report it honestly
            answer = self._extractive(question, references)
            backend = "extractive"
            grounded = bool(references)
        return Answer(question=question, answer=answer.strip(), rewritten=rewritten,
                      references=references, backend=backend, grounded=grounded)

    # -- helpers -----------------------------------------------------------
    def _context_block(self, refs: list[Reference]) -> str:
        blocks = []
        for r in refs:
            head = f"[ref {r.ref}] {r.kind} {r.name} — {r.path}:{r.start_line}-{r.end_line}"
            blocks.append(f"{head}\n{r.snippet}")
        return "\n\n".join(blocks)[:6000]

    def _extractive(self, question: str, refs: list[Reference]) -> str:
        if not refs:
            return ("No indexed code matched this question. Try indexing the "
                    "repository first, or rephrasing.")
        lines = ["Most relevant code for your question:"]
        for r in refs[:5]:
            lines.append(f"- [ref {r.ref}] {r.kind} `{r.name}` in {r.path}:{r.start_line}")
        lines.append("\n(LLM unavailable — showing retrieved sources. Enable the "
                     "llama.cpp backend for a synthesized answer.)")
        return "\n".join(lines)
