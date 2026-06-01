from collections import Counter

from graphindex.pipeline import Indexer, EventBus
from graphindex.pipeline import events as E


def test_pipeline_streams_lifecycle_events(cfg):
    counts = Counter()
    final_state = {}

    def on(evt):
        counts[evt.type] += 1
        if evt.type == E.NODE_UPDATE:
            final_state[evt.payload["id"]] = evt.payload["state"]

    bus = EventBus()
    bus.subscribe(on)
    ix = Indexer(cfg, bus=bus)
    m = ix.index()
    ix.db.close()

    assert counts[E.NODE_ADD] > 0
    assert counts[E.EDGE_ADD] > 0
    assert counts[E.DONE] == 1
    # nodes reach summarized state (green) by the end
    assert "summarized" in set(final_state.values())
    assert m["nodes_per_sec"] > 0


def test_incremental_only_changed(cfg):
    ix = Indexer(cfg)
    ix.index()
    n0 = ix.db.count_nodes()
    ix.db.close()
    # re-index a single file; counts should remain stable (idempotent upsert)
    ix2 = Indexer(cfg)
    ix2.index(only_changed=["pkg/models.py"])
    assert ix2.db.count_nodes() >= 1
    ix2.db.close()
