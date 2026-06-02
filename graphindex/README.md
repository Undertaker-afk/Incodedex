# graphindex

**High-speed, local-model codebase indexer with a live-updating knowledge graph.**

graphindex scans a repository, parses it with tree-sitter, builds a knowledge
graph of files and symbols, embeds every node with **Qwen3-Embedding-0.6B** and
summarizes/tags it with **LFM2.5-1.2B-Instruct** — all running **locally** via
an embedded **llama.cpp** runtime (`llama-cpp-python`, auto-installed). A
React WebUI renders the graph node-by-node as it is built, and an **Ask the
codebase** feature answers natural-language questions with grounded, cited
sources.

Everything works **offline with no models too**, thanks to a deterministic
fallback backend — so the full pipeline, UI and tests run anywhere.

---

## Features

**Search**
- Regex, semantic (vector), fuzzy (typo-tolerant), plain-text
- Filter syntax: `path:` `lang:` `ext:` `kind:` `scope:` `branch:`
- Case-sensitivity toggle, directory/branch scoping

**Code intelligence (tree-sitter AST)**
- Go-to-definition, find-all-references
- Call hierarchy (callers/callees), inheritance mapping
- Type/kind disambiguation of same-named symbols
- Languages: Python, JavaScript, TypeScript/TSX, Go, Java, Rust (extensible)

**Knowledge graph**
- Files, classes, functions, methods, interfaces, imports, externals
- Edges: contains, defines, calls, imports, inherits, references, similar
- Live node-by-node streaming with a colour state machine (see below)

**Ask the codebase (RAG)**
- LFM2.5 rewrites the question → embedding retrieval → reads source on disk →
  grounded answer with `[ref N]` citations mapping to file + line + node id
- Available in the WebUI, CLI (`graphindex ask`) and MCP (`ask_codebase`)

**extended_ask — multi-agent deep investigation**
- A local orchestrator built to let a coding agent understand a codebase while
  spending the **fewest possible tokens** (it does the reading; the main agent
  gets one compact, cited answer).
- Up to **2 keyword rounds × 4 queries**, then up to **3 parallel search agents**
  per round for up to **10 rounds**. Each agent reads index data structures
  (callers/callees/inheritance/refs) and requests specific **source ranges**,
  then the lead synthesizes a grounded answer.
- Reports **token-saving stats** (nodes inspected, source ranges read, distilled
  vs full-file size). WebUI "Deep ask" tab (live), CLI `graphindex extended-ask`,
  MCP `extended_ask`.
- Each indexed function stores its **full parameter setup** and a **search
  string** (the canonical embedding input) alongside its summary.

**Analysis**
- Dead-code detection, duplicate/near-duplicate detection
- Language breakdown, internal+external dependency graph
- Index health metrics (speed, errors, unresolved refs)
- Automated pruning of deleted files; incremental watcher

**Interfaces**
- CLI (`graphindex …`), Flask REST + WebSocket API, MCP server (stdio)
- Respects `.gitignore` **and** a custom `.graphignore` (full gitignore
  semantics incl. `!` negation); commit-aware (records the git SHA)

### Node colour state machine (live graph)

| State | Colour | Meaning |
|-------|--------|---------|
| discovered | gray | file/symbol found |
| parsed | yellow | AST parsed |
| embedded | blue | vector stored |
| summarized | green | summarized/tagged |
| hub | red | high-degree node |
| unresolved | orange | unresolved reference / external |
| warning | purple outline | duplicate / dead-code flag |

---

## Architecture

```
scanner/    repo walk + .gitignore/.graphignore
parsing/    tree-sitter AST -> symbols (calls, bases, imports)
graph/      node/edge model, builder, resolver (def/refs/calls/inherit/types)
chunking/   symbol -> embedding text
engine/     embedded llama.cpp: autoinstall, GGUF download, in-process + server
embedding/  Qwen3-Embedding-0.6B  | HF InferenceClient | deterministic fallback
summarize/  LFM2.5-1.2B-Instruct  | HF InferenceClient | heuristic fallback
storage/    SQLite (graph+meta+FTS) + FAISS (numpy fallback) vector store
search/     regex / semantic / fuzzy / filtered / scoped
analysis/   dead code, duplicates, languages, dependencies, health, prune
qa/         grounded ask-the-codebase RAG
pipeline/   orchestrator (10-step) + event bus (node-by-node streaming)
watcher/    incremental re-index on file changes
api/        Flask + SocketIO server, REST routes, MCP server
frontend/   React + react-force-graph-2d live graph UI
```

### The pipeline
1. Scan repo → 2. Respect `.gitignore`/`.graphignore` → 3. Parse (tree-sitter)
→ 4. Build graph nodes+edges → 5. Chunk symbol content → 6. Embed (Qwen3)
→ 7. Summarize/tag (LFM2.5) → 8. Store (SQLite + FAISS) → 9. Stream to WebUI
node-by-node → 10. Incremental watcher for updates.

---

## Install

graphindex is a normal Python package with a `graphindex` console-script entry
point. The base install gives you the full CLI, WebUI and pipeline — it uses
the deterministic fallback backend for embeddings + summaries so it runs
anywhere, with zero model downloads.

```bash
# 1) Create a venv (Python 3.10-3.12 recommended; 3.13+ may lack tree-sitter
#    wheels for some grammars).
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

# 2) Install graphindex itself
pip install graphindex                     # from PyPI
# or, from a clone of this repo:
# pip install -e .

# 3) (Optional) Real local LLM + fast vector search
#    Uses the prebuilt CPU wheel of llama.cpp — no C++ toolchain needed.
#    On Windows / Linux / macOS use the abetlen extra-index-url; the PyPI
#    sdist of llama-cpp-python needs a compiler.
pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
            "graphindex[llama,faiss]"
# Everything at once:
# pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
#             "graphindex[all]"
```

After install, `graphindex` is on your `PATH` — open any cmd / PowerShell /
bash, `cd` into a repo, and run:

```bash
graphindex setup .        # one-time: download GGUF models (~1.2 GB total)
graphindex index .        # build the index (streams live progress)
graphindex serve . --watch   # WebUI at http://localhost:8000
graphindex ask . "what does the bump function do"
```

`graphindex setup <repo>` auto-installs the llama.cpp runtime (when missing)
and downloads the GGUF models (`Qwen/Qwen3-Embedding-0.6B-GGUF`,
`LiquidAI/LFM2.5-1.2B-Instruct-GGUF`) to `~/.cache/graphindex/models`.

### Model backends (`--backend`)
- `auto` (default) — use the real llama.cpp models when present, else fallback
- `llamacpp` — force the embedded Qwen3 + LFM2.5 models
- `hf` — use `huggingface_hub` `InferenceClient` (remote provider or a local
  OpenAI-compatible endpoint via `GRAPHINDEX_HF_ENDPOINT`)
- `fallback` — deterministic, dependency-free embeddings + heuristic summaries

---

## Usage

```bash
# Build the index (streams progress)
graphindex index /path/to/repo

# Search
graphindex search "lang:python kind:function auth token" --semantic --fuzzy
graphindex search "^make_.*" --regex

# Ask the codebase (grounded, cited)
graphindex ask "How are inheritance edges resolved across files?" /path/to/repo

# Stats / maintenance
graphindex stats /path/to/repo
graphindex prune /path/to/repo

# Live WebUI + API (open http://localhost:8000)
graphindex serve /path/to/repo --watch

# MCP server (stdio) for agents/IDEs
graphindex mcp /path/to/repo
```

### Frontend dev
```bash
cd frontend && npm install && npm run build   # served by `graphindex serve`
# or: npm run dev   (proxies /api + /socket.io to :8000)
```

---

## REST API (under `/api`)
`GET /graph` · `GET /node/<id>` · `GET /search` · `POST /ask` · `GET /stats`
· `GET /health` · `POST /index` · `POST /prune` · `GET /config`
WebSocket channel `index_event` streams `node_add` / `node_update` /
`edge_add` / `phase` / `stats` / `done`.

## Tests
```bash
pip install pytest && pytest        # 31 tests (fast, fallback backend)
```

## Notes on performance
Embedding/summarization speed depends on the llama.cpp build. The generic CPU
wheel is portable but slow for large files; for production use a BLAS/AVX or
CUDA/Metal `llama-cpp-python` build (or the `hf` backend) for a large speedup.
The deterministic fallback backend is always instant.

### Environment variables (logging & verbosity)
| Var | Default | Effect |
|-----|---------|--------|
| `GRAPHINDEX_LOG_LEVEL` | `INFO` | Root Python logging level. |
| `GRAPHINDEX_ACCESS_LOG` | off | Set `1` to re-enable the per-request access log from Werkzeug/Engine.IO/Socket.IO that `graphindex serve` silences by default. |
| `GRAPHINDEX_LLAMA_LOG` | `error` | Verbosity of the embedded llama.cpp C logs: `silent` \| `error` \| `warn` \| `info` \| `debug`. |
| `GRAPHINDEX_LLAMA_LOG_SUPPRESS` | `1` | When `1`, well-known benign warnings (e.g. `llama_context: n_ctx_seq (2048) < n_ctx_train (32768) -- the full capacity of the model will not be utilized`) are dropped and any identical message is printed at most once per process. Set to `0` to see every occurrence. |
