"""extended_ask — a local multi-agent orchestrator over the index.

Purpose: let an external *coding agent* understand a codebase fast while spending
the **fewest possible tokens**. Instead of the main agent reading many files,
graphindex runs a local LFM2.5-driven investigation against the index and returns
one compact, grounded answer with precise references.

Flow (all caps configurable):
1. **Keyword rounds** (default 2 × 4): LFM proposes search queries; round 2 is
   refined using round-1 hits. This seeds a candidate pool.
2. **Agent rounds** (up to 10). Each round deploys up to 3 *parallel* search
   agents, each assigned a focus. An agent is given real context retrieved from
   the index and may **request more**: expand graph structures (callers/callees/
   inheritance) for node ids, run more searches, or read specific source ranges.
   Those requests are fulfilled and fed to the next round. The orchestrator reads
   all 3 agents' findings to decide whether to continue.
3. **Synthesis**: LFM composes the final grounded answer with [ref N] citations.

LLM inference is guarded by a lock (one local model), so agents are logically
parallel and their tool I/O (DB/index/source reads) truly runs concurrently; on
a GPU/remote backend the inference parallelizes too. Without a chat model it
degrades to a fast retrieval-only investigation.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from ..config import Config
from .tools import AgentTools

_KEYWORD_SYSTEM = (
    "You generate code-search queries for a codebase index. Given a question "
    "(and optionally earlier results), output up to {n} short queries — likely "
    "identifiers, function/class names, or concepts that appear in SOURCE CODE. "
    "One per line. No numbering, no prose."
)

_FOCUS_SYSTEM = (
    "You are the lead of a code-investigation team. Split the user's question into "
    "up to {n} distinct investigation focuses (sub-goals), each a single line. "
    "No numbering, no prose."
)

_AGENT_SYSTEM = (
    "You are a code-investigation agent. Investigate your FOCUS using ONLY the "
    "provided CONTEXT (symbols from a code index with signatures/summaries and "
    "source snippets). Be precise and grounded.\n"
    "Reply with a single JSON object and nothing else:\n"
    '{"findings": "<concise grounded findings>", '
    '"refs": ["<node_id used>", ...], '
    '"want_nodes": ["<node_id to expand>", ...], '
    '"want_queries": ["<extra search>", ...], '
    '"want_files": [{"path": "<path>", "start": <int>, "end": <int>}], '
    '"confident": true|false}'
)

_SYNTH_SYSTEM = (
    "You are a precise software engineering assistant. Using ONLY the findings and "
    "the reference code below, write a clear answer to the question. Do NOT invent "
    "behavior, hardware, or details that are not in the provided code/summaries. "
    "Cite evidence with [ref N] markers matching the reference list. If something is "
    "unknown from the context, say so explicitly. Be concise and concrete."
)

_STOPWORDS = {
    "about", "after", "before", "because", "between", "could", "does", "doing",
    "done", "enough", "flow", "from", "have", "into", "just", "more", "that",
    "then", "there", "this", "what", "when", "where", "which", "with", "would",
    "the", "and", "for", "how", "why", "who", "its", "is",
}

_ALIASES = {
    "deepask": ["deep ask", "extended_ask", "extended ask"],
    "deep": ["extended_ask", "investigation"],
    "ask": ["ask", "extended_ask"],
    "indexer": ["index", "pipeline", "orchestrator"],
    "agent": ["agent", "agents", "orchestrator"],
    "agents": ["agent", "agents", "orchestrator"],
    "keyword": ["keyword", "keywords", "search queries"],
    "keywords": ["keyword", "keywords", "search queries"],
}


def _extract_json(text: str) -> dict:
    """Best-effort parse of a JSON object from an LLM reply.

    Handles: leading prose, markdown ```json ... ``` fences, and nested
    braces in string values (the greedy ``{.*}`` pattern breaks on
    code-like text in the ``findings`` field).
    """
    if not text:
        return {}
    s = text.strip()
    # Strip common markdown code fences: ```json ... ``` or ``` ... ```
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    # Locate the first '{' and the matching '}' (brace-counted) so nested
    # braces inside string values don't trick the parser into swallowing
    # the whole reply.
    start = s.find("{")
    if start < 0:
        return {}
    depth = 0
    in_str = False
    escape = False
    end = -1
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return {}
    blob = s[start:end + 1]
    for candidate in (blob, blob.replace("\n", " ")):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return {}


@dataclass
class AgentResult:
    focus: str
    findings: str
    refs: list[str] = field(default_factory=list)
    want_nodes: list[str] = field(default_factory=list)
    want_queries: list[str] = field(default_factory=list)
    want_files: list[dict] = field(default_factory=list)
    confident: bool = False


@dataclass
class RoundResult:
    index: int
    agents: list[AgentResult] = field(default_factory=list)


@dataclass
class ExtendedAnswer:
    question: str
    answer: str = ""
    keywords: list[list[str]] = field(default_factory=list)
    focuses: list[str] = field(default_factory=list)
    rounds: list[RoundResult] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    backend: str = ""
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class ExtendedAsk:
    def __init__(self, cfg: Config, db, vectors, embedder, chat=None, bus=None,
                 keyword_rounds: int = 2, keywords_per_round: int = 4,
                 agents_per_round: int = 3, max_rounds: int = 10,
                 candidates_per_focus: int = 5):
        self.cfg = cfg
        self.db = db
        self.tools = AgentTools(cfg, db, vectors, embedder)
        self.chat = chat
        self.bus = bus
        self.keyword_rounds = max(1, min(keyword_rounds, 4))
        self.keywords_per_round = max(1, min(keywords_per_round, 8))
        self.agents_per_round = max(1, min(agents_per_round, 3))
        self.max_rounds = max(1, min(max_rounds, 10))
        self.candidates_per_focus = candidates_per_focus
        self._lock = threading.Lock()       # serialize single local model
        self.llm_calls = 0

    # -- llm helpers (locked) --------------------------------------------
    def _chat(self, system: str, user: str, max_tokens: int = 220) -> str:
        if self.chat is None:
            return ""
        with self._lock:
            self.llm_calls += 1
            try:
                return self.chat.chat(system, user, max_tokens=max_tokens)
            except Exception:
                return ""

    def _emit(self, type_: str, **payload):
        if self.bus is not None:
            self.bus.emit(type_, **payload)

    def _lines(self, text: str, limit: int) -> list[str]:
        out = []
        for ln in (text or "").splitlines():
            ln = ln.strip(" -*\t0123456789.")
            if 2 <= len(ln) <= 140:
                out.append(ln)
        return out[:limit]

    def _dedupe(self, values: list[str], limit: int) -> list[str]:
        out, seen = [], set()
        for value in values:
            clean = re.sub(r"\s+", " ", str(value or "").strip())
            key = clean.lower()
            if clean and key not in seen:
                out.append(clean)
                seen.add(key)
            if len(out) >= limit:
                break
        return out

    def _fallback_keywords(self, question: str, hits: list[str], round_index: int) -> list[str]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", question)
        terms = [w for w in words if w.lower() not in _STOPWORDS]
        expanded = []
        for term in terms:
            expanded.extend(_ALIASES.get(term.lower(), []))
            expanded.append(term)
            snake = re.sub(r"(?<!^)([A-Z])", r"_\1", term).lower()
            if snake != term.lower():
                expanded.append(snake)
        phrases = []
        for a, b in zip(terms, terms[1:]):
            phrases.append(f"{a} {b}")
            phrases.append(f"{a}_{b}")
        hit_terms = [h for h in hits if h and len(h) <= 80]
        pools = [
            expanded,
            phrases + expanded,
            hit_terms + expanded,
            hit_terms + phrases + [question],
        ]
        pool = pools[min(round_index, len(pools) - 1)]
        return self._dedupe(pool + [question], self.keywords_per_round)

    def _fallback_agent_findings(self, focus: str, briefs: list[dict]) -> str:
        if not briefs:
            return "No index matches were retrieved for this focus."
        parts = []
        for b in briefs[:5]:
            loc = f"{b.get('path')}:{b.get('line')}" if b.get("path") else "unknown location"
            sig = b.get("signature") or b.get("name") or b.get("id")
            summary = f" - {b.get('summary')}" if b.get("summary") else ""
            parts.append(f"{b.get('kind')} {sig} at {loc}{summary}")
        return f"Retrieved evidence for '{focus}': " + "; ".join(parts)

    # -- phase 1: keywords ------------------------------------------------
    def _keyword_rounds(self, question: str) -> tuple[list[list[str]], list[dict]]:
        rounds: list[list[str]] = []
        pool: dict[str, dict] = {}
        prior = ""
        for r in range(self.keyword_rounds):
            hits = []
            if self.chat is not None:
                sys = _KEYWORD_SYSTEM.format(n=self.keywords_per_round)
                user = f"Question: {question}\n{prior}"
                kws = self._lines(self._chat(sys, user, 90), self.keywords_per_round)
            else:
                kws = []
            if len(kws) < self.keywords_per_round:
                hit_names = [d.get("name", "") for d in pool.values()]
                kws = self._dedupe(
                    kws + self._fallback_keywords(question, hit_names, r),
                    self.keywords_per_round,
                )
            rounds.append(kws)
            self._emit("ext_keywords", round=r + 1, keywords=kws)
            for kw in kws:
                for d in self.tools.search(kw, k=4):
                    pool.setdefault(d["id"], d)
                    hits.append(d["name"])
            prior = ("Earlier results: "
                     + ", ".join(sorted(set(hits))[:20])) if hits else ""
        return rounds, list(pool.values())

    # -- phase 2: focuses -------------------------------------------------
    def _fallback_focuses(self, question: str) -> list[str]:
        pool = list(getattr(self, "pool", []))
        names = self._dedupe([d.get("name", "") for d in pool[:8]], 4)
        symbol_hint = ", ".join(names) if names else question
        candidates = [
            f"Find entry points, handlers, and UI/API calls for: {question}",
            f"Trace orchestration flow, rounds, stop conditions, and handoffs for: {question}",
            f"Inspect index search, graph expansion, and source-reading tools around: {symbol_hint}",
            f"Validate final synthesis, references, and progress events for: {question}",
        ]
        return candidates[: self.agents_per_round]

    def _focuses(self, question: str) -> list[str]:
        fallback = self._fallback_focuses(question)
        if self.chat is not None:
            sys = _FOCUS_SYSTEM.format(n=self.agents_per_round)
            foc = self._lines(self._chat(sys, f"Question: {question}", 90),
                              self.agents_per_round)
            return self._dedupe(foc + fallback, self.agents_per_round)
        return fallback

    # -- context assembly -------------------------------------------------
    def _context_for(self, focus: str, seeds: dict) -> tuple[str, list[dict]]:
        briefs: dict[str, dict] = {}
        for d in self.tools.search(focus, k=self.candidates_per_focus):
            briefs[d["id"]] = d
        # Seed with the keyword-round candidate pool so agents always have real
        # symbols to reason over, even when an abstract focus retrieves little.
        for d in getattr(self, "pool", [])[:6]:
            briefs.setdefault(d["id"], d)
        # expand requested structures
        for nid in seeds.get("want_nodes", [])[:6]:
            s = self.tools.structure(nid)
            if "error" not in s:
                briefs[nid] = s
        for q in seeds.get("want_queries", [])[:4]:
            for d in self.tools.search(q, k=3):
                briefs.setdefault(d["id"], d)
        snippets = []
        for f in seeds.get("want_files", [])[:4]:
            r = self.tools.read_source(f.get("path", ""), int(f.get("start", 1) or 1),
                                       f.get("end"))
            if "error" not in r:
                snippets.append(r)
        # Auto-ground: always read the real source for the top symbol hits so the
        # agent reasons over actual code, not just signatures/summaries.
        for b in list(briefs.values())[:2]:
            if b.get("path") and b.get("line"):
                r = self.tools.read_source(b["path"], int(b["line"]),
                                           b.get("end_line"), max_lines=30)
                if "error" not in r:
                    snippets.append(r)
        ctx = json.dumps({"symbols": list(briefs.values())[:8],
                          "source": snippets}, indent=1)[:5000]
        return ctx, list(briefs.values())

    # -- one agent --------------------------------------------------------
    def _run_agent(self, focus: str, seeds: dict, round_index: int) -> AgentResult:
        ctx, briefs = self._context_for(focus, seeds)
        self._emit("ext_agent_start", focus=focus, round=round_index)
        if self.chat is None:
            names = ", ".join(f"{b['kind']} {b['name']} ({b['path']})" for b in briefs[:5])
            res = AgentResult(focus=focus,
                              findings=f"Relevant: {names}" if names else "No matches.",
                              refs=[b["id"] for b in briefs[:5]], confident=bool(briefs))
        else:
            reply = self._chat(_AGENT_SYSTEM, f"FOCUS: {focus}\n\nCONTEXT:\n{ctx}", 300)
            j = _extract_json(reply)
            res = AgentResult(
                focus=focus,
                findings=str(j.get("findings", "")).strip() or reply.strip()[:500],
                refs=[str(x) for x in j.get("refs", []) if x][:10],
                want_nodes=[str(x) for x in j.get("want_nodes", []) if x][:6],
                want_queries=[str(x) for x in j.get("want_queries", []) if x][:4],
                want_files=[f for f in j.get("want_files", []) if isinstance(f, dict)][:4],
                confident=bool(j.get("confident", False)),
            )
            # ensure refs are valid node ids; backfill from retrieved briefs
            valid = {b["id"] for b in briefs}
            res.refs = [r for r in res.refs if r in valid] or [b["id"] for b in briefs[:4]]
            if not res.findings:
                res.findings = self._fallback_agent_findings(focus, briefs)
        self._emit("ext_agent_done", focus=focus, round=round_index, findings=res.findings,
                   refs=res.refs, want_nodes=res.want_nodes,
                   want_queries=res.want_queries, want_files=res.want_files,
                   confident=res.confident)
        return res

    # -- main -------------------------------------------------------------
    def run(self, question: str) -> ExtendedAnswer:
        ans = ExtendedAnswer(question=question,
                             backend=getattr(self.chat, "name", None)
                             or (self.chat.__class__.__name__ if self.chat else "retrieval-only"))
        self._emit("ext_phase", phase="keywords", message="Generating search keywords")
        ans.keywords, self.pool = self._keyword_rounds(question)

        self._emit("ext_phase", phase="plan", message="Planning investigation focuses")
        ans.focuses = self._focuses(question)

        # seeds carried between rounds, per focus index
        seeds_by_focus: dict[int, dict] = {}
        focuses = ans.focuses[: self.agents_per_round]
        seen_refs: set[str] = set()

        for r in range(self.max_rounds):
            self._emit("ext_phase", phase="round", message=f"Agent round {r + 1}",
                       round=r + 1)
            round_res = RoundResult(index=r + 1)
            with ThreadPoolExecutor(max_workers=self.agents_per_round) as ex:
                futures = [ex.submit(self._run_agent, focuses[i],
                                     seeds_by_focus.get(i, {}), r + 1)
                           for i in range(len(focuses))]
                agents = [f.result() for f in futures]
            round_res.agents = agents
            ans.rounds.append(round_res)

            # carry each agent's requests forward; collect new focuses
            new_refs = set()
            next_focuses, next_seeds = [], {}
            for i, a in enumerate(agents):
                seeds_by_focus[i] = {"want_nodes": a.want_nodes,
                                     "want_queries": a.want_queries,
                                     "want_files": a.want_files}
                new_refs.update(a.refs)
                for q in a.want_queries:
                    if len(next_focuses) < self.agents_per_round and q not in next_focuses:
                        next_focuses.append(q)
                        next_seeds[len(next_focuses) - 1] = {}

            fresh = new_refs - seen_refs
            seen_refs |= new_refs
            all_confident = all(a.confident for a in agents)
            # stop conditions
            if all_confident or (not fresh and r >= 1) or r + 1 >= self.max_rounds:
                break
            # set up next round: prefer agent-proposed follow-up queries as focuses
            if next_focuses:
                focuses = next_focuses
                seeds_by_focus = next_seeds

        # references
        ans.references = self._build_refs(seen_refs)
        # synthesis
        self._emit("ext_phase", phase="synthesize", message="Synthesizing answer")
        ans.answer = self._synthesize(question, ans)
        ans.stats = {
            "llm_calls": self.llm_calls,
            "rounds": len(ans.rounds),
            "agents_total": sum(len(r.agents) for r in ans.rounds),
            "nodes_inspected": self.tools.nodes_inspected,
            "files_read": self.tools.files_read,
            "references": len(ans.references),
            "context_source_chars": self.tools.source_bytes,
            "estimated_full_file_chars": self._full_file_chars(ans.references),
        }
        self._emit("ext_done", answer=ans.answer, references=ans.references,
                   stats=ans.stats)
        return ans

    # -- helpers ----------------------------------------------------------
    def _build_refs(self, ref_ids: set[str]) -> list[dict]:
        refs = []
        for i, nid in enumerate(sorted(ref_ids), start=1):
            n = self.db.get_node(nid)
            if not n:
                continue
            refs.append({"ref": i, "node_id": n.id, "name": n.name, "kind": n.kind,
                         "path": n.path, "start_line": n.start_line,
                         "end_line": n.end_line, "signature": n.signature,
                         "params": n.params})
        return refs

    def _full_file_chars(self, refs: list[dict]) -> int:
        total, seen = 0, set()
        for r in refs:
            p = r["path"]
            if p in seen:
                continue
            seen.add(p)
            try:
                total += (self.cfg.repo_path / p).stat().st_size
            except OSError:
                pass
        return total

    def _synthesize(self, question: str, ans: ExtendedAnswer) -> str:
        findings = []
        for rr in ans.rounds:
            for a in rr.agents:
                if a.findings:
                    findings.append(f"- ({a.focus}) {a.findings}")
        ref_list = "\n".join(
            f"[ref {r['ref']}] {r['kind']} {r['name']} — {r['path']}:{r['start_line']}"
            for r in ans.references)
        if self.chat is None:
            head = "Investigation summary (retrieval-only, no LLM):\n"
            return head + "\n".join(findings[:12]) + "\n\nReferences:\n" + ref_list
        # Include real reference code so synthesis stays grounded.
        ref_code = []
        for r in ans.references[:8]:
            snip = self.tools.read_source(r["path"], r["start_line"], r.get("end_line"),
                                          max_lines=25)
            code = snip.get("code", "") if isinstance(snip, dict) else ""
            ref_code.append(f"[ref {r['ref']}] {r['name']} ({r['path']}:{r['start_line']})\n"
                            f"{r.get('signature','')}\n{code}")
        user = (f"Question: {question}\n\nInvestigation findings:\n"
                + "\n".join(findings[:20]) + "\n\nReference code:\n"
                + "\n\n".join(ref_code)[:5000]
                + "\n\nReference list:\n" + ref_list
                + "\n\nWrite the final answer with [ref N] citations.")
        out = self._chat(_SYNTH_SYSTEM, user, max_tokens=400)
        if out.strip():
            return out.strip()
        return self._fallback_synthesis(question, findings, ans.references)

    def _fallback_synthesis(self, question: str, findings: list[str], refs: list[dict]) -> str:
        lines = [f"Investigation summary for: {question}", ""]
        if findings:
            lines.append("Agent findings:")
            lines.extend(findings[:8])
        else:
            lines.append("No agent findings were produced.")
        if refs:
            lines.append("")
            lines.append("Key references:")
            for r in refs[:8]:
                lines.append(f"- [ref {r['ref']}] {r['kind']} {r['name']} in {r['path']}:{r['start_line']}")
        lines.append("")
        lines.append("(LLM synthesis unavailable or empty; showing grounded investigation summary.)")
        return "\n".join(lines)
