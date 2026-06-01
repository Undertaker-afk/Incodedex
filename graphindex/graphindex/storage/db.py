"""SQLite data-access layer for the knowledge graph and metadata."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from ..graph.model import Edge, Node

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class GraphDB:
    """Thin DAO over SQLite. Safe for single-process pipelines + a Flask reader."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # -- meta -------------------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, _dumps(value)),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return _loads(row["value"], default) if row else default

    # -- files ------------------------------------------------------------
    def upsert_file(self, path: str, language: str, size: int, mtime: float,
                    sha: str, commit_id: str) -> None:
        self.conn.execute(
            "INSERT INTO files(path,language,size,mtime,sha,commit_id,indexed_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
            "language=excluded.language,size=excluded.size,mtime=excluded.mtime,"
            "sha=excluded.sha,commit_id=excluded.commit_id,indexed_at=excluded.indexed_at",
            (path, language, size, mtime, sha, commit_id, time.time()),
        )

    def get_file_sha(self, path: str) -> str | None:
        row = self.conn.execute("SELECT sha FROM files WHERE path=?", (path,)).fetchone()
        return row["sha"] if row else None

    def all_file_paths(self) -> list[str]:
        return [r["path"] for r in self.conn.execute("SELECT path FROM files")]

    def delete_file(self, path: str) -> list[str]:
        """Delete a file and all nodes/edges it owns. Returns removed node ids."""
        node_ids = [r["id"] for r in self.conn.execute(
            "SELECT id FROM nodes WHERE path=?", (path,))]
        if node_ids:
            qmarks = ",".join("?" * len(node_ids))
            self.conn.execute(f"DELETE FROM edges WHERE src IN ({qmarks}) OR dst IN ({qmarks})",
                              node_ids + node_ids)
            self.conn.execute(f"DELETE FROM nodes WHERE id IN ({qmarks})", node_ids)
            self.conn.execute(f"DELETE FROM nodes_fts WHERE id IN ({qmarks})", node_ids)
        self.conn.execute("DELETE FROM files WHERE path=?", (path,))
        self.conn.commit()
        return node_ids

    # -- nodes ------------------------------------------------------------
    def upsert_node(self, node: Node) -> None:
        self.conn.execute(
            "INSERT INTO nodes(id,kind,name,path,language,start_line,end_line,signature,"
            "type_hint,summary,tags,state,degree,flags,commit_id,extra) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "kind=excluded.kind,name=excluded.name,path=excluded.path,language=excluded.language,"
            "start_line=excluded.start_line,end_line=excluded.end_line,signature=excluded.signature,"
            "type_hint=excluded.type_hint,summary=excluded.summary,tags=excluded.tags,"
            "state=excluded.state,degree=excluded.degree,flags=excluded.flags,"
            "commit_id=excluded.commit_id,extra=excluded.extra",
            (node.id, node.kind, node.name, node.path, node.language, node.start_line,
             node.end_line, node.signature, node.type_hint, node.summary, _dumps(node.tags),
             node.state, node.degree, _dumps(node.flags), node.commit, _dumps(node.extra)),
        )
        # keep FTS in sync
        self.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node.id,))
        self.conn.execute(
            "INSERT INTO nodes_fts(id,name,signature,summary,tags,code) VALUES(?,?,?,?,?,?)",
            (node.id, node.name, node.signature, node.summary, " ".join(node.tags),
             node.code[:4000]),
        )

    def upsert_nodes(self, nodes: Iterable[Node]) -> None:
        for n in nodes:
            self.upsert_node(n)
        self.conn.commit()

    def update_node_state(self, node_id: str, state: str) -> None:
        self.conn.execute("UPDATE nodes SET state=? WHERE id=?", (state, node_id))

    def update_node_fields(self, node_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(f"{k}=?")
            vals.append(_dumps(v) if isinstance(v, (list, dict)) else v)
        vals.append(node_id)
        self.conn.execute(f"UPDATE nodes SET {','.join(cols)} WHERE id=?", vals)

    def get_node(self, node_id: str) -> Node | None:
        row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return self._row_to_node(row) if row else None

    def iter_nodes(self, kind: str | None = None) -> list[Node]:
        if kind:
            rows = self.conn.execute("SELECT * FROM nodes WHERE kind=?", (kind,))
        else:
            rows = self.conn.execute("SELECT * FROM nodes")
        return [self._row_to_node(r) for r in rows]

    def count_nodes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]

    # -- edges ------------------------------------------------------------
    def upsert_edge(self, edge: Edge) -> None:
        self.conn.execute(
            "INSERT INTO edges(id,src,dst,kind,weight,resolved,extra) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET weight=excluded.weight,resolved=excluded.resolved,"
            "extra=excluded.extra",
            (edge.id, edge.src, edge.dst, edge.kind, edge.weight,
             1 if edge.resolved else 0, _dumps(edge.extra)),
        )

    def upsert_edges(self, edges: Iterable[Edge]) -> None:
        for e in edges:
            self.upsert_edge(e)
        self.conn.commit()

    def iter_edges(self) -> list[Edge]:
        return [self._row_to_edge(r) for r in self.conn.execute("SELECT * FROM edges")]

    def count_edges(self) -> int:
        return self.conn.execute("SELECT COUNT(*) c FROM edges").fetchone()["c"]

    def edges_from(self, node_id: str, kind: str | None = None) -> list[Edge]:
        if kind:
            rows = self.conn.execute("SELECT * FROM edges WHERE src=? AND kind=?", (node_id, kind))
        else:
            rows = self.conn.execute("SELECT * FROM edges WHERE src=?", (node_id,))
        return [self._row_to_edge(r) for r in rows]

    def edges_to(self, node_id: str, kind: str | None = None) -> list[Edge]:
        if kind:
            rows = self.conn.execute("SELECT * FROM edges WHERE dst=? AND kind=?", (node_id, kind))
        else:
            rows = self.conn.execute("SELECT * FROM edges WHERE dst=?", (node_id,))
        return [self._row_to_edge(r) for r in rows]

    # -- health -----------------------------------------------------------
    def record_health(self, run_id: str, metric: str, value: float) -> None:
        self.conn.execute(
            "INSERT INTO health(run_id,ts,metric,value) VALUES(?,?,?,?)",
            (run_id, time.time(), metric, float(value)),
        )
        self.conn.commit()

    def health_metrics(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id:
            rows = self.conn.execute(
                "SELECT * FROM health WHERE run_id=? ORDER BY ts", (run_id,))
        else:
            rows = self.conn.execute("SELECT * FROM health ORDER BY ts")
        return [dict(r) for r in rows]

    # -- helpers ----------------------------------------------------------
    def _row_to_node(self, row: sqlite3.Row) -> Node:
        return Node(
            id=row["id"], kind=row["kind"], name=row["name"] or "", path=row["path"] or "",
            language=row["language"] or "", start_line=row["start_line"] or 0,
            end_line=row["end_line"] or 0, signature=row["signature"] or "",
            type_hint=row["type_hint"] or "", summary=row["summary"] or "",
            tags=_loads(row["tags"], []), state=row["state"] or "discovered",
            degree=row["degree"] or 0, flags=_loads(row["flags"], []),
            commit=row["commit_id"] or "", extra=_loads(row["extra"], {}),
        )

    def _row_to_edge(self, row: sqlite3.Row) -> Edge:
        return Edge(src=row["src"], dst=row["dst"], kind=row["kind"],
                    weight=row["weight"] or 1.0, resolved=bool(row["resolved"]),
                    extra=_loads(row["extra"], {}))

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
