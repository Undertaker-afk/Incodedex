"""Tests for the grounded ask-codebase RAG (extractive path, no LLM)."""

from graphindex.qa import AskEngine
from graphindex.storage.vectors import VectorStore


def _ask_engine(ix, chat=None):
    vs = VectorStore(ix.cfg.vectors_path, ix.db.get_meta("embed_dim", 256))
    return AskEngine(ix.cfg, ix.db, vs, ix.embedder, chat=chat)


def test_ask_extractive_returns_grounded_references(indexed):
    ix, _ = indexed
    eng = _ask_engine(ix, chat=None)  # no chat -> extractive
    ans = eng.ask("how does a dog make a sound", k=5)
    assert ans.backend == "extractive"
    assert ans.references, "should retrieve grounding references"
    # references carry file + line + node id (index reference)
    r = ans.references[0]
    assert r.path and r.node_id and r.start_line >= 1
    # snippet is read from source on disk
    assert isinstance(r.snippet, str)


def test_ask_with_stub_llm_cites_refs(indexed):
    ix, _ = indexed

    class StubChat:
        name = "stub"
        def chat(self, system, user, max_tokens=128):
            if "search queries" in system:
                return "dog\nnoise\nspeak"
            return "The Dog class defines noise [ref 1]."

    eng = _ask_engine(ix, chat=StubChat())
    ans = eng.ask("what does Dog do?", k=5)
    assert ans.backend == "stub"
    assert "[ref 1]" in ans.answer
    assert ans.rewritten == ["dog", "noise", "speak"]
    assert ans.references


def test_ask_handles_no_results(cfg):
    # fresh index over an empty-ish query still returns a structured answer
    from graphindex.pipeline import Indexer
    ix = Indexer(cfg)
    ix.index()
    eng = _ask_engine(ix, chat=None)
    ans = eng.ask("zzzzz_nonexistent_symbol_qqq", k=3)
    assert isinstance(ans.answer, str) and ans.answer
    ix.db.close()
