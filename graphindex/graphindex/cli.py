"""``graphindex`` command-line interface.

Commands:
  index     build / rebuild the index for a repo
  search    query the index (regex / semantic / fuzzy / filters / scope)
  serve     run the Flask + WebSocket API and live WebUI
  watch     incrementally re-index on file changes
  stats     language / dependency / dead-code / health report
  prune     remove data for deleted files
  setup     install the llama.cpp runtime and download the GGUF models
  mcp       run the MCP server over stdio
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn,
)
from rich.table import Table

try:
    from graphindex.config import load_config
except ImportError:  # pragma: no cover
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from graphindex.config import load_config

console = Console(force_terminal=True, legacy_windows=False)


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def configure_serve_logging() -> None:
    """Quiet the per-request access log spam from Werkzeug / Engine.IO / Socket.IO.

    ``graphindex serve`` is the kind of command that runs for hours; the
    default Werkzeug dev server logs every HTTP and Engine.IO polling request,
    which buries actual progress output. We silence those loggers unless the
    user explicitly opts in via ``GRAPHINDEX_ACCESS_LOG=1``.
    """
    if not _env_flag("GRAPHINDEX_ACCESS_LOG"):
        for name in ("werkzeug", "engineio", "engineio.server", "socketio",
                     "socketio.server", "geventwebsocket"):
            logging.getLogger(name).setLevel(logging.WARNING)
    level_name = os.environ.get("GRAPHINDEX_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=False,
    )


def _cfg(repo, **kw):
    return load_config(repo, **{k: v for k, v in kw.items() if v is not None})


@click.group(help="High-speed local-model codebase indexer with a live knowledge graph.")
@click.version_option(package_name="graphindex")
def main() -> None:
    pass


@main.command()
@click.argument("repo", default=".")
@click.option("--backend", type=click.Choice(["auto", "llamacpp", "hf", "fallback"]),
              default=None, help="Model backend.")
@click.option("--no-summarize", is_flag=True, help="Skip LLM summaries.")
@click.option("--no-embed", is_flag=True, help="Skip embeddings.")
def index(repo, backend, no_summarize, no_embed):
    """Build/rebuild the index for REPO."""
    from graphindex.pipeline import Indexer, EventBus
    from graphindex.pipeline.events import PROGRESS, PHASE, LOG, DONE
    cfg = _cfg(repo, backend=backend)
    bus = EventBus()
    # task_id per phase so each phase shows its own bar; unknown phases get a
    # fresh task. Mutated from the bus thread, so all access goes through
    # rich's Progress(thread_safe=True) below.
    task_ids: dict[str, int] = {}
    total_for: dict[str, int] = {}

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=None),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TextColumn("[dim]{task.fields[current]}[/dim]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        expand=True,
    )

    def on(evt):
        if evt.type == PHASE:
            phase = evt.payload.get("phase", "")
            console.print(f"[cyan]▸ {evt.payload.get('message','')}[/cyan]")
            if phase and phase not in task_ids:
                # open a task with an unknown total; the first PROGRESS
                # event will set the real total
                tid = progress.add_task(phase, total=None, current="")
                task_ids[phase] = tid
        elif evt.type == PROGRESS:
            phase = evt.payload.get("phase", "")
            done = int(evt.payload.get("done", 0))
            total = int(evt.payload.get("total", 0))
            current = evt.payload.get("current", "") or ""
            if phase not in task_ids:
                task_ids[phase] = progress.add_task(phase, total=total, current="")
            tid = task_ids[phase]
            # Late-arriving totals: switch the task to determinate.
            if total and total_for.get(phase) != total:
                total_for[phase] = total
                progress.update(tid, total=total)
            progress.update(tid, completed=done, current=current[:60])
        elif evt.type == LOG:
            console.print(f"  {evt.payload.get('message','')}")
        elif evt.type == DONE:
            # leave the bar visible; the table printed below shows the final
            # numbers cleanly. Stop the live display so the table aligns.
            progress.stop()

    bus.subscribe(on)
    console.print(f"[bold]Indexing[/bold] {cfg.repo_path}  (backend={cfg.backend})")
    ix = Indexer(cfg, bus=bus, do_summarize=not no_summarize, do_embed=not no_embed)
    progress.start()
    try:
        m = ix.index()
    finally:
        # If DONE never fired (crash / Ctrl-C), stop the live display so
        # the final message doesn't interleave with the bar.
        progress.stop()
    ix.db.close()
    t = Table(title="Index complete", show_header=False)
    for k, v in m.items():
        t.add_row(str(k), str(v))
    console.print(t)


@main.command()
@click.argument("query")
@click.argument("repo", default=".")
@click.option("--regex", is_flag=True)
@click.option("--semantic", is_flag=True)
@click.option("--fuzzy", is_flag=True)
@click.option("--case", is_flag=True, help="Case-sensitive.")
@click.option("-k", "--top", default=20, help="Max results.")
@click.option("--json", "as_json", is_flag=True)
def search(query, repo, regex, semantic, fuzzy, case, top, as_json):
    """Search the index. Supports filters like lang: kind: path: scope:."""
    from graphindex.storage.db import GraphDB
    from graphindex.storage.vectors import VectorStore
    from graphindex.embedding import get_embedder
    from graphindex.search import SearchEngine, parse_query
    cfg = _cfg(repo)
    db = GraphDB(cfg.db_path)
    dim = db.get_meta("embed_dim", cfg.embed_dim) or cfg.embed_dim
    vs = VectorStore(cfg.vectors_path, dim)
    emb = get_embedder(cfg) if semantic else None
    eng = SearchEngine(db, vs, emb)
    q = parse_query(query, regex=regex, semantic=semantic, fuzzy=fuzzy,
                    case_sensitive=case, top_k=top)
    results = eng.search(q)
    if as_json:
        click.echo(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        t = Table(title=f"{len(results)} results for {query!r}")
        for col in ("score", "kind", "name", "path:line", "matched"):
            t.add_column(col)
        for r in results:
            t.add_row(f"{r.score:.3f}", r.node.kind, r.node.name,
                      f"{r.node.path}:{r.node.start_line}", ",".join(r.matched_by))
        console.print(t)
    db.close()


@main.command()
@click.argument("repo", default=".")
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.option("--backend", type=click.Choice(["auto", "llamacpp", "hf", "fallback"]),
              default=None)
@click.option("--watch", is_flag=True, help="Also watch for changes.")
def serve(repo, host, port, backend, watch):
    """Run the API + live WebUI server."""
    configure_serve_logging()
    from graphindex.api.server import create_app
    cfg = _cfg(repo, host=host, port=port, backend=backend)
    app, socketio = create_app(cfg)
    if watch:
        from graphindex.watcher import RepoWatcher
        state = app.config["GRAPHINDEX_STATE"]
        # Share the API's single-flight index_lock so the watcher and the
        # foreground /api/index runner never collide on the same DB/vectors.
        w = RepoWatcher(cfg, bus=state.bus, index_lock=state.index_lock,
                        on_reload=state.reload)
        w.start()
        state.watcher = w
    url = f"http://{cfg.host}:{cfg.port}"
    console.print(f"[bold green]graphindex[/bold green] serving at {url}")
    console.print(f"  API: {url}/api/graph   WebUI: {url}/")
    socketio.run(app, host=cfg.host, port=cfg.port, allow_unsafe_werkzeug=True)


@main.command()
@click.argument("repo", default=".")
@click.option("--no-summarize", is_flag=True)
def watch(repo, no_summarize):
    """Incrementally re-index REPO on file changes."""
    import time
    from graphindex.watcher import RepoWatcher
    from graphindex.pipeline import EventBus
    cfg = _cfg(repo)
    bus = EventBus()
    bus.subscribe(lambda e: console.print(f"  {e.payload.get('message','')}")
                  if e.type in ("log", "done") else None)
    w = RepoWatcher(cfg, bus=bus, do_summarize=not no_summarize)
    w.start()
    console.print(f"[bold]Watching[/bold] {cfg.repo_path} … Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        w.stop()


@main.command()
@click.argument("question")
@click.argument("repo", default=".")
@click.option("-k", "--top", default=8, help="Snippets to retrieve.")
@click.option("--backend", type=click.Choice(["auto", "llamacpp", "hf", "fallback"]),
              default=None)
@click.option("--json", "as_json", is_flag=True)
def ask(question, repo, top, backend, as_json):
    """Ask a grounded question about the codebase (RAG with citations)."""
    from graphindex.storage.db import GraphDB
    from graphindex.storage.vectors import VectorStore
    from graphindex.embedding import get_embedder
    from graphindex.qa import AskEngine, get_chat
    cfg = _cfg(repo, backend=backend)
    db = GraphDB(cfg.db_path)
    dim = db.get_meta("embed_dim", cfg.embed_dim) or cfg.embed_dim
    vs = VectorStore(cfg.vectors_path, dim)
    eng = AskEngine(cfg, db, vs, get_embedder(cfg), chat=get_chat(cfg))
    with console.status("thinking…"):
        ans = eng.ask(question, k=top)
    if as_json:
        click.echo(json.dumps(ans.to_dict(), indent=2))
    else:
        console.print(f"[bold cyan]Q:[/bold cyan] {question}")
        if ans.rewritten and ans.rewritten != [question]:
            console.print(f"[dim]search queries: {', '.join(ans.rewritten)}[/dim]")
        console.print(f"\n[bold]{ans.answer}[/bold]\n")
        t = Table(title=f"References  (backend: {ans.backend})")
        for col in ("ref", "kind", "name", "path:line", "score"):
            t.add_column(col)
        for r in ans.references:
            t.add_row(str(r.ref), r.kind, r.name,
                      f"{r.path}:{r.start_line}", f"{r.score:.3f}")
        console.print(t)
    db.close()


@main.command(name="extended-ask")
@click.argument("question")
@click.argument("repo", default=".")
@click.option("--rounds", default=10, help="Max agent rounds (<=10).")
@click.option("--agents", default=3, help="Agents per round (<=3).")
@click.option("--keyword-rounds", default=2, help="Keyword rounds (<=4).")
@click.option("--backend", type=click.Choice(["auto", "llamacpp", "hf", "fallback", "none"]),
              default=None)
@click.option("--json", "as_json", is_flag=True)
def extended_ask(question, repo, rounds, agents, keyword_rounds, backend, as_json):
    """Multi-agent deep investigation: keyword rounds -> parallel search agents
    that read the index + source -> grounded answer. Built to let a coding agent
    understand a codebase while spending minimal tokens."""
    from graphindex.storage.db import GraphDB
    from graphindex.storage.vectors import VectorStore
    from graphindex.embedding import get_embedder
    from graphindex.qa import ExtendedAsk, get_chat
    cfg = _cfg(repo, backend=backend)
    db = GraphDB(cfg.db_path)
    dim = db.get_meta("embed_dim", cfg.embed_dim) or cfg.embed_dim
    vs = VectorStore(cfg.vectors_path, dim)

    def on(evt):
        p = evt.payload
        if evt.type == "ext_phase":
            console.print(f"[cyan]▸ {p.get('message','')}[/cyan]")
        elif evt.type == "ext_keywords":
            console.print(f"  [dim]keywords r{p.get('round')}: {', '.join(p.get('keywords',[]))}[/dim]")
        elif evt.type == "ext_agent_done":
            console.print(f"  [green]agent[/green] {p.get('focus','')[:60]} → "
                          f"{p.get('findings','')[:80]}")

    from graphindex.pipeline import EventBus
    bus = EventBus(); bus.subscribe(on)
    eng = ExtendedAsk(cfg, db, vs, get_embedder(cfg), chat=get_chat(cfg), bus=bus,
                      keyword_rounds=keyword_rounds, agents_per_round=agents,
                      max_rounds=rounds)
    ans = eng.run(question)
    if as_json:
        click.echo(json.dumps(ans.to_dict(), indent=2))
    else:
        console.print(f"\n[bold]{ans.answer}[/bold]\n")
        t = Table(title=f"References (backend: {ans.backend})")
        for col in ("ref", "kind", "name", "path:line"):
            t.add_column(col)
        for r in ans.references:
            t.add_row(str(r["ref"]), r["kind"], r["name"], f"{r['path']}:{r['start_line']}")
        console.print(t)
        console.print(f"[dim]stats: {ans.stats}[/dim]")
    db.close()


@main.command()
@click.argument("repo", default=".")
@click.option("--json", "as_json", is_flag=True)
def stats(repo, as_json):
    """Show language / dependency / dead-code / health stats."""
    from graphindex.storage.db import GraphDB
    from graphindex.analysis.languages import language_breakdown
    from graphindex.analysis.dependencies import dependency_graph
    from graphindex.analysis.deadcode import find_dead_code
    from graphindex.analysis.health import health_report
    cfg = _cfg(repo)
    db = GraphDB(cfg.db_path)
    report = {
        "languages": language_breakdown(db),
        "dependencies": dependency_graph(db),
        "dead_code": find_dead_code(db),
        "health": health_report(db),
    }
    if as_json:
        click.echo(json.dumps(report, indent=2, default=str))
    else:
        h = report["health"]
        console.print(f"[bold]Nodes:[/bold] {h['node_count']}  "
                      f"[bold]Edges:[/bold] {h['edge_count']}  "
                      f"[bold]Unresolved:[/bold] {h['unresolved_edges']}")
        console.print("[bold]Languages:[/bold]",
                      report["languages"]["files_by_language"])
        console.print("[bold]External packages:[/bold]",
                      report["dependencies"]["external_packages"])
        console.print(f"[bold]Dead-code candidates:[/bold] {len(report['dead_code'])}")
    db.close()


@main.command()
@click.argument("repo", default=".")
def prune(repo):
    """Remove nodes/edges/vectors for deleted files."""
    from graphindex.storage.db import GraphDB
    from graphindex.storage.vectors import VectorStore
    from graphindex.analysis.health import prune_deleted_files
    cfg = _cfg(repo)
    db = GraphDB(cfg.db_path)
    dim = db.get_meta("embed_dim", cfg.embed_dim) or cfg.embed_dim
    vs = VectorStore(cfg.vectors_path, dim)
    res = prune_deleted_files(cfg, db, vs)
    console.print(res)
    db.close()


@main.command()
@click.argument("repo", default=".")
def setup(repo):
    """Install the llama.cpp runtime and download the GGUF models."""
    from graphindex.engine.bootstrap import ensure_engine
    cfg = _cfg(repo)
    console.print("Installing llama.cpp runtime + downloading models … (may take a while)")
    status = ensure_engine(cfg)
    console.print(status)


@main.command()
@click.argument("repo", default=".")
def mcp(repo):
    """Run the MCP server over stdio."""
    from graphindex.api import mcp_server
    cfg = _cfg(repo)
    try:
        mcp_server.run(cfg)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
