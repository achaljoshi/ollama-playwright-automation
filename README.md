# oapw — Ollama + Playwright AI Automation Framework

> Local-first AI quality engineering platform. Playwright for browser control, Ollama for private LLM reasoning, multi-layer caching, Jira + Confluence knowledge base, and a QA Agent that can be told "regress the login flow on QA" and figure out the rest.

---

## Quickstart

```bash
# 1. Install dependencies
poetry install
poetry run playwright install chromium

# 2. Pull required Ollama models (8 GB machine)
brew install ollama
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# 3. Verify everything is wired up
poetry run oapw doctor

# 4. Run tests
poetry run pytest tests/unit/
```

## CLI

```bash
oapw doctor          # check Ollama, models, browser, RAM, cache dir
oapw version         # print version

oapw cache stats     # show L1 / L2 hit rates
oapw cache prune     # remove expired entries
oapw cache clear     # wipe all cached data
```

## Recommended Ollama env (add to ~/.zshrc)

```bash
export OLLAMA_KEEP_ALIVE=5m
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
```

## Hardware profiles

| RAM  | Models used |
|------|-------------|
| 8 GB | `qwen2.5:3b` + `nomic-embed-text` |
| 16 GB | `qwen2.5:7b` + `qwen2.5-coder:7b` + `llava:7b` |

## Project structure

```
src/oapw/
├── core/       # Playwright wrapper, Ollama client, config
├── cache/      # L1 memory LRU + L2 SQLite + manager
├── agents/     # Planner, Executor, Locator Resolver, Healer, Verifier
├── qa_agent/   # Goal Parser, Test Selector, Judgment Engine, Reporter
├── knowledge/  # ChromaDB, embeddings, RAG
├── enterprise/ # Atlassian MCP (Jira + Confluence)
├── generators/ # Test generation from user stories / Jira
├── healing/    # Self-healing locator strategies
├── cli/        # oapw CLI
└── ...
```

See [PLAN.md](PLAN.md) for the full design document and implementation roadmap.
