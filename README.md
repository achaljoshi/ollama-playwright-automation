# oapw — Ollama + Playwright AI Automation Framework

> **Local-first AI quality engineering platform.** Playwright for browser control, Ollama for private LLM reasoning, multi-layer caching so re-runs feel instant, a knowledge base fed by Jira + Confluence + your dev repos, and a QA Agent that can be told *"regress the login flow on QA"* and figure out the rest — like a junior QA engineer that never sleeps and reads every spec.

---

## Table of Contents

- [Why oapw?](#why-oapw)
- [Quick Start](#quick-start)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [Writing Tests](#writing-tests)
- [Self-Healing Locators](#self-healing-locators)
- [Knowledge Base](#knowledge-base)
- [Code Repository Ingestion](#code-repository-ingestion)
- [Cache Architecture](#cache-architecture)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Documentation Index](#documentation-index)

---

## Why oapw?

| Pain | oapw solution |
|---|---|
| Flaky locators break tests overnight | **Self-healing pipeline** — fingerprints every element; on breakage tries DOM scan, role+text fallback, then LLM as last resort |
| LLM API bills for every CI run | **Multi-layer cache** (L1 memory → L2 SQLite → L3 ChromaDB semantic) — same prompt hits cache in microseconds |
| AI has no idea what your app does | **Knowledge base** — ingest Jira tickets, Confluence pages, and your C#/TypeScript source code; AI gets relevant context injected at generation time |
| Test generators write generic assertions | **Jira-linked retrieval** — boosts context docs linked to the ticket being tested |
| Secrets leak to cloud LLMs | **100% local** — Ollama, ChromaDB, SQLite; nothing leaves your machine |

---

## Quick Start

```bash
# 1. Install Python dependencies
poetry install

# 2. Install Playwright browsers
poetry run playwright install chromium

# 3. Install and start Ollama
brew install ollama          # macOS
ollama serve                 # start the server

# 4. Pull required models (needs ~5 GB)
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# 5. Verify all dependencies
poetry run oapw doctor

# 6. Run the test suite
poetry run pytest tests/unit/ tests/eval/
```

Expected output from `oapw doctor`:

```
╭────────────────────── oapw doctor ──────────────────────╮
│ Check                    Status  Detail                  │
│ Python ≥ 3.11              ✓    3.12.x                  │
│ Ollama server              ✓    http://localhost:11434   │
│ Model: qwen2.5:3b          ✓    pulled                  │
│ Model: nomic-embed-text    ✓    pulled                  │
│ Playwright chromium        ✓    installed               │
│ RAM ≥ 8 GB                 ✓    16 GB detected          │
│ Cache dir writable         ✓    .oapw/cache             │
╰─────────────────────────────────────────────────────────╯
✓ All checks passed — oapw v0.1.0 ready!
```

---

## Features

### Phase 1 — Core Infrastructure
- `OllamaClient` — async httpx wrapper with streaming, timeout, structured JSON output
- `OapwConfig` — pydantic-settings; env vars (`OAPW_*`), `.env` file, sane defaults
- `L1Cache` (in-memory LRU) + `L2Cache` (SQLite WAL) + `CacheManager` with bucket-level TTLs
- `BrowserManager` with `async with managed_browser()` context manager
- `oapw doctor` CLI health check

### Phase 2 — AI-Powered Browser Actions
- `AiPage` — wraps Playwright `Page` with `.ai()`, `.ai_extract()`, `.ai_assert()` methods
- `Planner` — natural language goal → ordered `Step` list via LLM (cached by goal + page signature)
- `Executor` — executes steps, calls `LocatorResolver` for every element interaction
- DOM context extractor — extracts interactive elements for LLM prompts
- AOM (Accessibility Object Model) context builder
- Jinja2 prompt templates: `planner`, `locator_resolve`, `extract`, `assert`, `heal`, `generate_test`

### Phase 3 — Self-Healing Locators
- `ElementFingerprint` — semantic fingerprint (role, tag, label, placeholder, type, testid)
- `LocatorResolver` — 4-tier pipeline: L1/L2 cache → deterministic Playwright strategies → LLM
- `Healer` — triggered on stale cache: fingerprint scan → role+text → LLM
- Three healing strategies: `FingerprintStrategy`, `RoleTextStrategy`, `LLMHealStrategy`
- `HealingRecorder` — SQLite WAL store tracking all healing events + success rates
- Self-evaluation golden suite (14 test HTML pages)

### Phase 4 — Knowledge Base & Enterprise Integration
- `KnowledgeStore` — ChromaDB vector store (optional dep, graceful degradation)
- `EmbeddingService` — `nomic-embed-text` embeddings with L2 cache
- `RAGRetriever` — semantic search, source filtering, Jira-linked boost ×1.2
- `AtlassianClient` — Jira REST + Confluence REST with keyring API token storage
- `JiraIngestor` / `ConfluenceIngestor` — batch ingest with recency/owner weighting
- `TraceabilityStore` — SQLite; links tests ↔ Jira tickets ↔ Confluence pages
- `L3SemanticCache` — ChromaDB-backed fuzzy LLM response cache (threshold 0.92)
- **Code repo ingestion** — C# + TypeScript/React language-aware parsers, incremental SHA sync
- Bitbucket App Password auth via OS keyring

### Phase 5 — Hybrid API+UI & Test Data
- `ApiClient` — Playwright `APIRequestContext` wrapper with response caching and auth header injection
- `HybridContext` — shared cookie jar between browser session and API client; `login_via_api()` / `verify_via_api()` for mixed UI+API tests
- `BaseFactory` + 5 ready-made factories — `UserFactory`, `LoginCredentialsFactory`, `AddressFactory`, `CreditCardFactory`, `ProductFactory`; Pydantic field-name heuristics auto-generate realistic values; `FactoryRegistry` for central lookup
- `PiiMasker` — 10 regex patterns (JWT, bearer, AWS keys, email, phone, payment card, SSN, NI, password); `mask()` and `mask_dict()` for safe logging
- **pytest plugin** — install-once entry point; ready-made fixtures: `oapw_page`, `oapw_hybrid`, `oapw_factory`, `oapw_api_context`, `oapw_pii_masker`, `oapw_config`

### Phase 6 — Test Generator
- `JiraTestGenerator` (`oapw generate from-jira`) — fetches a Jira ticket, retrieves KB RAG context, generates a pytest file via LLM, syntax-checks it, writes it to disk, and records a traceability link
- `UserStoryGenerator` (`oapw generate from-story`) — turns plain-text user stories into pytest files with optional KB context injection
- `SmokeTestCrawler` (`oapw generate smoke`) — crawls a live site with Playwright, follows internal links up to `max_pages`, and generates a smoke test per discovered page
- `EdgeCaseMutator` — 10 mutation types: `empty_input`, `boundary_values`, `special_characters`, `invalid_format`, `wrong_credentials`, `sql_injection_attempt`, `xss_attempt`, `concurrent_submission`, `session_expiry`, `max_length_exceeded`; per-mutation L2 cache; JSON-envelope LLM response with plain Python fallback
- **`oapw generate` CLI sub-app** — `from-jira TICKET [--out DIR] [--mutate N]`, `from-story TEXT [--out DIR] [--feature NAME]`, `smoke URL [--out DIR] [--max-pages N]`

---

## Installation

### Requirements

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| Poetry | ≥ 1.8 |
| Ollama | latest |
| RAM | ≥ 8 GB |

### Full install (with knowledge base support)

```bash
# Install with ChromaDB for the knowledge base and L3 cache
poetry install --extras knowledge
poetry run playwright install chromium
```

### Minimal install (without ChromaDB)

```bash
poetry install
poetry run playwright install chromium
```

> The knowledge base and L3 semantic cache degrade gracefully when ChromaDB is not installed — the rest of the framework works fine.

### Ollama setup

```bash
# Recommended shell environment (add to ~/.zshrc)
export OLLAMA_KEEP_ALIVE=5m
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1

ollama serve &

# 8 GB machine
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# 16 GB machine (better quality)
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

---

## Configuration

All settings are read from environment variables (prefixed `OAPW_`) or a `.env` file in the project root.

```env
# .env example
OAPW_OLLAMA_DEFAULT_MODEL=qwen2.5:7b
OAPW_OLLAMA_BASE_URL=http://localhost:11434
OAPW_BROWSER_HEADLESS=false
OAPW_BROWSER_SLOW_MO=100
OAPW_DATA_DIR=.oapw

# Atlassian (for Jira + Confluence)
OAPW_ATLASSIAN_URL=https://your-company.atlassian.net
OAPW_ATLASSIAN_EMAIL=you@company.com
```

See **[docs/configuration.md](docs/configuration.md)** for the full reference.

---

## CLI Reference

```
oapw doctor               Verify all runtime dependencies
oapw version              Print framework version

oapw cache stats          Show L1/L2 hit rates and sizes
oapw cache prune          Remove expired entries from SQLite cache
oapw cache clear          Wipe all cached data (L1 + L2)

oapw kb sync              Sync Jira, Confluence, and/or code repos
oapw kb stats             Show knowledge base document count
oapw kb clear             Remove all documents from the knowledge base
oapw kb coverage          Show which Jira tickets have traced tests

oapw auth atlassian       Store Atlassian API token in OS keyring
oapw auth bitbucket       Store Bitbucket App Password in OS keyring
```

See **[docs/cli-reference.md](docs/cli-reference.md)** for full option details and examples.

---

## Writing Tests

### Natural language actions

```python
import pytest
from oapw.core.browser import managed_browser
from oapw.core.ai_page import AiPage

@pytest.mark.asyncio
async def test_login():
    async with managed_browser() as mgr:
        async with mgr.new_page() as page:
            ai = AiPage(page)
            await page.goto("https://your-app.com/login")

            await ai.ai("Fill the email input with 'user@example.com'")
            await ai.ai("Fill the password input with 'secret'")
            await ai.ai("Click the Sign In button")

            await ai.ai_assert("User is redirected to the dashboard")
```

### Direct locator resolution

```python
from oapw.agents.locator_resolver import LocatorResolver

resolver = LocatorResolver(page=page)
locator = await resolver.resolve("Email address input")
await locator.fill("user@example.com")
```

### Test generation from Jira ticket

```python
from oapw.enterprise.jira_ingest import JiraIngestor
from oapw.knowledge.rag import RAGRetriever

# After syncing the KB, retrieve context for test generation
retriever = RAGRetriever()
snippets = await retriever.retrieve("login authentication", linked_jira=["AUTH-42"])
context = retriever.format_context(snippets)
# Inject `context` into your test generation prompt
```

### Traceability

```python
from oapw.enterprise.traceability import TraceabilityStore
from oapw.core.config import get_config

store = TraceabilityStore(db_path=get_config().traceability_db)

# Link a test to tickets and confluence pages
store.link_test(
    test_path="tests/e2e/test_login.py::test_login_flow",
    jira_ids=["AUTH-42", "AUTH-55"],
    confluence_ids=["12345678"],
)

# Check which tests cover a ticket
tests = store.tests_for_ticket("AUTH-42")
```

---

## Self-Healing Locators

When a UI changes and a cached locator stops working, oapw automatically tries:

1. **Fingerprint scan** — searches the live DOM for an element with the same semantic fingerprint (role, label, placeholder) stored when the locator was first resolved
2. **Role + text fallback** — tries `page.get_by_role()` with the stored role and name variants
3. **LLM heal** — sends the stored fingerprint + current DOM context to the LLM for a new selector (result cached)

This is fully automatic — your test code never changes.

```python
# This just works, even after UI restructuring
locator = await resolver.resolve("Sign in button")
```

See **[docs/self-healing.md](docs/self-healing.md)** for the full design and configuration options.

---

## Knowledge Base

```bash
# Store Atlassian API token once
oapw auth atlassian --email you@company.com

# Sync Jira tickets
oapw kb sync --jira "project = AUTH AND issuetype = Story" --max 100

# Sync Confluence pages
oapw kb sync --confluence "label = qa AND space = ENG"

# Sync both with component weighting
oapw kb sync \
  --jira "project = AUTH" \
  --confluence "space = ENG" \
  --component "Authentication"

# Check what's indexed
oapw kb stats
oapw kb coverage
```

See **[docs/knowledge-base.md](docs/knowledge-base.md)** for the full guide.

---

## Code Repository Ingestion

Index your application source code so the AI understands how the app works:

```bash
# Store Bitbucket credentials once
oapw auth bitbucket --username your-bitbucket-username

# Sync one or more repos
oapw kb sync \
  --repo https://bitbucket.org/workspace/backend-api \
  --repo https://bitbucket.org/workspace/frontend-app \
  --branch main \
  --username your-bitbucket-username
```

**What gets indexed:**
- **C# files** — namespaces, classes, methods with XML `///` doc comments
- **TypeScript/TSX/JS/JSX** — React components, hooks, exported functions, interfaces, API routes
- **All other files** — sliding-window 80-line chunks with 20-line overlap

**Incremental sync** — after the first full index, re-syncing only processes files changed since the last git commit SHA. Large repos re-sync in seconds.

See **[docs/code-ingestion.md](docs/code-ingestion.md)** for the full guide.

---

## Cache Architecture

```
LLM call
   │
   ▼
L1 Memory (LRU, 512 entries)  ← microseconds, process lifetime
   │ miss
   ▼
L2 SQLite (WAL, unlimited)    ← milliseconds, persists across runs
   │ miss
   ▼
L3 ChromaDB (semantic, optional) ← finds near-identical prompts (≥0.92 cosine)
   │ miss
   ▼
Ollama (actual LLM call)      ← seconds, written back to all layers
```

| Bucket | Default TTL |
|---|---|
| LLM responses | 30 days |
| Locators | 7 days |
| Plans | 1 day |
| Embeddings | Never expires |
| Jira / Confluence | 1 day |
| Negative results | 5 minutes |

See **[docs/architecture.md](docs/architecture.md)** for the full design.

---

## Project Structure

```
src/oapw/
├── core/               # Browser, Ollama client, config, DOM, AOM
│   ├── browser.py      # BrowserManager, managed_browser() context manager
│   ├── ollama_client.py# Async httpx wrapper with streaming + JSON mode
│   ├── config.py       # OapwConfig — env/dotenv with pydantic-settings
│   ├── ai_page.py      # AiPage — natural language page actions
│   ├── dom.py          # DOM snapshot, interactive element extraction
│   └── aom.py          # Accessibility Object Model context
│
├── cache/              # Multi-layer caching
│   ├── l1_memory.py    # LRU in-memory cache (cachetools)
│   ├── l2_disk.py      # SQLite WAL persistent cache
│   ├── l3_semantic.py  # ChromaDB semantic fuzzy cache
│   └── manager.py      # CacheManager — unified L1→L2→L3 interface
│
├── agents/             # AI agents
│   ├── models.py       # Step, Plan, LocatorCandidate, LocatorStrategy
│   ├── planner.py      # Goal → ordered Step list via LLM
│   ├── executor.py     # Executes steps against live page
│   └── locator_resolver.py  # 4-tier locator resolution pipeline
│
├── healing/            # Self-healing locator system
│   ├── fingerprint.py  # ElementFingerprint, find_best_match()
│   ├── strategies.py   # FingerprintStrategy, RoleTextStrategy, LLMHealStrategy
│   ├── healer.py       # Healer — orchestrates healing strategies
│   └── recorder.py     # HealingRecorder — SQLite event log
│
├── knowledge/          # Vector knowledge base
│   ├── embeddings.py   # EmbeddingService (nomic-embed-text + L2 cache)
│   ├── vector_store.py # KnowledgeStore — ChromaDB wrapper
│   └── rag.py          # RAGRetriever — semantic search + context formatter
│
├── enterprise/         # Atlassian + code integrations
│   ├── atlassian_client.py  # Jira REST + Confluence REST client
│   ├── jira_ingest.py       # Batch ingest Jira tickets into KB
│   ├── confluence_ingest.py # Batch ingest Confluence pages into KB
│   ├── weighting.py         # Recency + owner scoring for Confluence pages
│   ├── traceability.py      # SQLite test ↔ ticket ↔ page links
│   ├── code_parser.py       # C#, TypeScript, generic source code chunkers
│   ├── code_ingest.py       # Git clone/pull + incremental KB sync
│   └── connectors/
│       └── bitbucket.py     # Bitbucket App Password auth helper
│
├── eval/               # Golden self-evaluation suite
│   ├── golden_pages.py # 14 HTML test pages (login, forms, tables, etc.)
│   ├── golden_suite.py # GoldenEvaluator — runs resolver against golden pages
│   └── metrics.py      # EvalMetrics — pass rate, heal rate, latency
│
├── prompts/            # Jinja2 prompt templates
│   ├── planner.j2
│   ├── locator_resolve.j2
│   ├── extract.j2
│   ├── assert.j2
│   ├── heal.j2
│   └── generate_test.j2
│
└── cli/
    └── main.py         # oapw CLI (typer + rich)

tests/
├── unit/               # 200 fast unit tests (all mocked)
└── eval/               # 14 golden evaluation tests (real Playwright)
```

---

## Running Tests

```bash
# All unit tests (fast, no external dependencies)
poetry run pytest tests/unit/ -v

# Eval suite (requires Playwright + local HTTP server)
poetry run pytest tests/eval/ -v

# Full suite
poetry run pytest tests/unit/ tests/eval/

# With coverage report
poetry run pytest tests/unit/ --cov=src/oapw --cov-report=html
open htmlcov/index.html

# Linting
poetry run ruff check src/ tests/
poetry run mypy src/
```

---

## Hardware Profiles

| RAM | Recommended models | Notes |
|---|---|---|
| 8 GB | `qwen2.5:3b` + `nomic-embed-text` | Default config; one model loaded at a time |
| 16 GB | `qwen2.5:7b` + `qwen2.5-coder:7b` + `nomic-embed-text` | Better reasoning quality |
| 32 GB+ | `qwen2.5:14b` + `nomic-embed-text` | Best quality; can run two models concurrently |

---

## Documentation Index

| Document | Description |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Full system design, data flows, design decisions |
| [docs/configuration.md](docs/configuration.md) | All `OAPW_*` environment variables and defaults |
| [docs/cli-reference.md](docs/cli-reference.md) | Every CLI command with options and examples |
| [docs/self-healing.md](docs/self-healing.md) | How self-healing locators work, tuning, debugging |
| [docs/knowledge-base.md](docs/knowledge-base.md) | Setting up Jira/Confluence ingestion and RAG retrieval |
| [docs/code-ingestion.md](docs/code-ingestion.md) | Indexing C# and TypeScript repos into the knowledge base |
| [docs/development.md](docs/development.md) | Contributing guide, adding new agents, running tests |
| [CHANGELOG.md](CHANGELOG.md) | Version history and change log |
| [PLAN.md](PLAN.md) | Original design document and roadmap |
