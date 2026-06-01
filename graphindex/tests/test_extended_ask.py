"""Tests for the extended_ask multi-agent orchestrator (stub + retrieval)."""

from graphindex.qa import ExtendedAsk
from graphindex.storage.vectors import VectorStore


def _vs(ix):
    return VectorStore(ix.cfg.vectors_path, ix.db.get_meta("embed_dim", 256))


class StubChat:
    name = "stub"

    def chat(self, system, user, max_tokens=128):
        if "search queries" in system:
            return "Dog\nAnimal\nspeak\nnoise"
        if "investigation focuses" in system:
            return "How Dog speaks\nWhat Dog inherits\nHow noise differs"
        if system.startswith("You are a code-investigation agent"):
            return ('{"findings":"Dog.speak calls noise; Dog inherits Animal",'
                    '"refs":[],"want_nodes":[],"want_queries":[],"want_files":[],'
                    '"confident":true}')
        return "Dog inherits Animal and speak() calls noise() [ref 1]."


class EmptyChat:
    name = "empty"

    def chat(self, system, user, max_tokens=128):
        return ""


def test_extended_ask_with_stub(indexed):
    ix, _ = indexed
    ea = ExtendedAsk(ix.cfg, ix.db, _vs(ix), ix.embedder, chat=StubChat(),
                     keyword_rounds=2, agents_per_round=3, max_rounds=10)
    ans = ea.run("How does a Dog make sound and what does it inherit?")
    assert ans.keywords and len(ans.keywords) == 2          # 2 keyword rounds
    assert ans.focuses                                       # planned focuses
    assert ans.rounds                                        # at least one round
    assert ans.references                                    # grounded refs
    assert "[ref 1]" in ans.answer
    # caps respected
    assert all(len(r.agents) <= 3 for r in ans.rounds)
    assert len(ans.rounds) <= 10
    assert ans.stats["llm_calls"] > 0


def test_extended_ask_empty_chat_keeps_configured_search_shape(indexed):
    ix, _ = indexed
    ea = ExtendedAsk(ix.cfg, ix.db, _vs(ix), ix.embedder, chat=EmptyChat(),
                     keyword_rounds=4, keywords_per_round=4,
                     agents_per_round=3, max_rounds=3)
    ans = ea.run("what is the deepask action flow in this indexer")
    assert len(ans.keywords) == 4
    assert all(1 <= len(kws) <= 4 for kws in ans.keywords)
    assert len({kw for kws in ans.keywords for kw in kws}) > 1
    assert len(ans.focuses) == 3
    assert len(ans.rounds[0].agents) == 3
    assert any(a.findings for a in ans.rounds[0].agents)
    assert ans.answer.strip()


def test_extended_ask_retrieval_only(indexed):
    ix, _ = indexed
    ea = ExtendedAsk(ix.cfg, ix.db, _vs(ix), ix.embedder, chat=None, max_rounds=3)
    ans = ea.run("dog sound inheritance")
    assert ans.backend == "retrieval-only"
    assert ans.references          # still retrieves grounding refs
    assert ans.stats["nodes_inspected"] > 0
    # token-saving metric is reported
    assert "estimated_full_file_chars" in ans.stats


def test_extended_ask_caps_are_bounded(indexed):
    ix, _ = indexed
    ea = ExtendedAsk(ix.cfg, ix.db, _vs(ix), ix.embedder, chat=None,
                     agents_per_round=99, max_rounds=99, keyword_rounds=99)
    assert ea.agents_per_round == 3
    assert ea.max_rounds == 10
    assert ea.keyword_rounds == 4
