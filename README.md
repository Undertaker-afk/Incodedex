# Incodedex

A high-speed, local-model **codebase indexer** with a live-updating knowledge
graph, semantic/regex/fuzzy search, code intelligence, and a grounded
"ask the codebase" assistant — powered by **Qwen3-Embedding-0.6B** and
**LFM2.5-1.2B-Instruct** running locally via embedded **llama.cpp**.

The project lives in [`graphindex/`](graphindex/). See
[`graphindex/README.md`](graphindex/README.md) for full docs.

```bash
cd graphindex
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install -e .
graphindex serve .            # live WebUI + API at http://localhost:8000
```
