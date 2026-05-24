# Changelog

All notable changes to **oapw** are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Planned
- QA Agent mode (`oapw run "regress the login flow"` end-to-end)
- Visual regression support (screenshot comparison with LLM judge)
- Parallel repo sync (currently sequential to protect 8 GB RAM)
- Config file support for listing many repos (`oapw kb sync --config repos.yml`)

---

## [0.1.0] — 2026-05-24

## [Phase 7] — Agent System
### Added
- `agents/loop_guard.py`: `LoopGuard` with configurable budget cap and sliding-window cycle detection (`LoopViolation` exception)
- `agents/hooks.py`: Human-in-loop hook system — `HookRegistry`, `HookEvent`, `HookDecision`, `HookContext`, `HookResponse`, `SilentHook`, `ConsoleHook`
- `agents/models.py`: `RunStatus` enum + `RunResult` model (`ok` property, `failed_steps` helper)
- `agents/runner.py`: `AgentRunner` — orchestrates Planner + Executor with loop guards; RETRY/OVERRIDE/ABORT/CONTINUE hook decisions; optional LLM replan on step failure
- `prompts/replan.j2`: Jinja2 prompt template for post-failure replanning
- `core/config.py`: `agent_max_steps`, `agent_max_step_retries`, `agent_loop_window` settings
- `cli/main.py`: `oapw run goal` command with `--interactive` flag (activates `ConsoleHook`)
### Tests added
- `tests/unit/test_runner.py`: 34 unit tests covering LoopGuard, HookRegistry, SilentHook, RunResult, AgentRunner (retry, override, abort, loop detection, multi-step retries)

---

### Phase 6 — Test Generator

#### Added
- **`generators/models.py`** — GeneratedTest, MutatedTest, GenerationResult dataclasses
- **`generators/from_jira.py`** — JiraTestGenerator: AtlassianClient ticket fetch → KB RAG context → LLM generate → syntax check → write file → traceability link
- **`generators/from_user_story.py`** — UserStoryGenerator: plain-text story → pytest file with optional KB context
- **`generators/crawler.py`** — SmokeTestCrawler: crawls live site (Playwright), follows internal links up to max_pages, generates smoke test per page
- **`generators/mutator.py`** — EdgeCaseMutator: 10 mutation types per MUTATION_TYPES list; JSON-envelope LLM response with fallback to plain Python extraction; per-mutation L2 cache
- **`prompts/generate_from_story.j2`** — user story → pytest prompt with KB context slot
- **`prompts/generate_smoke.j2`** — URL + DOM context → smoke test prompt
- **`prompts/generate_edge_cases.j2`** — original test + mutation type → JSON {description, code} prompt
- **`cli/main.py`** — `oapw generate` sub-app with three commands:
  - `oapw generate from-jira TICKET [--out DIR] [--model M] [--no-kb] [--mutate N]`
  - `oapw generate from-story TEXT [--out DIR] [--feature NAME] [--model M]`
  - `oapw generate smoke URL [--out DIR] [--max-pages N] [--model M]`

#### Tests added
- `tests/unit/test_generators.py` — 41 tests (all generators, helpers, caching, file writing, traceability, mutation types)
- Total: 374 tests (360 unit + 14 eval)

---

### Phase 5 — Hybrid API+UI & Test Data

#### Added
- **`hybrid/api_client.py`** — `ApiClient` wrapping Playwright `APIRequestContext`
  - GET/POST/PUT/PATCH/DELETE helpers with response deserialization
  - Optional response caching via `CacheManager`
  - Auth header injection (bearer token or session cookie forwarding)
- **`hybrid/context.py`** — `HybridContext` combining `AiPage` and `ApiClient`
  - Shared cookie jar between browser and API request context
  - `login_via_api(credentials)` — authenticates via API, shares session with browser
  - `verify_via_api(endpoint)` — performs API assertion alongside UI interaction
- **`hybrid/__init__.py`** — exports `ApiClient`, `HybridContext`
- **`factories/base.py`** — `BaseFactory` with Pydantic field-name heuristics
  - Auto-generates realistic values from field names (email, phone, name, url, etc.)
  - `build(**overrides)` — returns a populated model instance
  - `build_batch(n, **overrides)` — returns a list of n instances
- **`factories/common.py`** — five ready-made factories and a registry
  - `UserFactory` — username, email, password, first_name, last_name
  - `LoginCredentialsFactory` — email + password pair
  - `AddressFactory` — street, city, state, zip_code, country
  - `CreditCardFactory` — card number, expiry, cvv, holder name
  - `ProductFactory` — name, description, price, sku, category
  - `FactoryRegistry` — central lookup: `registry.get("user").build()`
- **`factories/__init__.py`** — exports all factories and `FactoryRegistry`
- **`security/pii.py`** — `PiiMasker` with 10 regex patterns
  - JWT tokens, bearer tokens, AWS access keys, email addresses, phone numbers
  - Payment card numbers, Social Security Numbers, UK National Insurance numbers, passwords
  - `mask(text)` → redacted string; `mask_dict(data)` → recursively masked dict
- **`security/__init__.py`** — exports `PiiMasker`
- **`plugin/__init__.py`** — pytest plugin registered as `oapw` entry point
  - `oapw_config` — session-scoped `OapwConfig` fixture
  - `oapw_page` — function-scoped `AiPage` fixture (manages browser lifecycle)
  - `oapw_api_context` — function-scoped `ApiClient` fixture
  - `oapw_hybrid` — function-scoped `HybridContext` fixture
  - `oapw_factory` — function-scoped `FactoryRegistry` fixture
  - `oapw_pii_masker` — session-scoped `PiiMasker` fixture
- **`core/config.py`** — added `app_base_url` and `app_api_base_url` fields (`OAPW_APP_BASE_URL`, `OAPW_APP_API_BASE_URL`)
- **`pyproject.toml`** — registered pytest plugin: `[tool.poetry.plugins."pytest11"] oapw = "oapw.plugin"`

#### Tests added
- `tests/unit/test_hybrid.py` — 26 tests (ApiClient, HybridContext, cookie sharing)
- `tests/unit/test_factories.py` — 54 tests (all five factories, BaseFactory heuristics, FactoryRegistry)
- `tests/unit/test_pii.py` — 41 tests (all 10 masking patterns, mask_dict recursion)

---

### Phase 4 Extension — Code Repository Ingestion

#### Added
- **`enterprise/code_parser.py`** — Language-aware source code chunkers
  - `parse_csharp()` — extracts C# namespaces, classes, methods, interfaces with XML `///` doc comments via regex
  - `parse_typescript()` — extracts React components, custom hooks (`use*`), exported functions, type/interface definitions, API route handlers (Express-style)
  - `parse_generic()` — sliding-window 80-line chunks with 20-line overlap for all other languages
  - `detect_language()` — maps file extension to language string
  - `CodeChunk` dataclass with `to_kb_doc()` for knowledge store ingestion
  - Both file-summary and function-level granularity per chunk type
- **`enterprise/connectors/bitbucket.py`** — Bitbucket App Password authentication
  - `save_credential(username, password)` — stores in OS keyring
  - `load_credential(username)` — retrieves from OS keyring
  - `build_auth_url(clone_url, username, password)` — injects URL-encoded credentials into HTTPS clone URL
  - `repo_slug(url)` — extracts short repository name from clone URL
- **`enterprise/code_ingest.py`** — Git-backed incremental code ingestion pipeline
  - `CodeIngestor` — clones/pulls repos under `.oapw/repos/`, batch upserts into ChromaDB
  - Incremental sync via L2 cache key `code:last_sha:{repo_name}` — on re-sync only processes files changed since last indexed SHA (`git diff --name-only`)
  - Sequential `sync_all()` to avoid OOM on 8 GB machines
  - Respects `_SKIP_DIRS` (node_modules, .git, bin, obj, dist, etc.) and `_MAX_FILE_BYTES` (300 KB)
  - `SyncResult` dataclass with files_indexed, chunks_added, sha, errors
  - `clear_repo(name)` — removes all chunks for a repo from ChromaDB
- **`cli/main.py`** — Extended `oapw kb sync` and new `oapw auth bitbucket`
  - `oapw kb sync --repo URL` — repeatable flag for multiple repos
  - `oapw kb sync --branch BRANCH` — specify git branch (default: main)
  - `oapw kb sync --username USER` — Bitbucket username for keyring credential lookup
  - `oapw auth bitbucket --username USER [--password PASS]` — store App Password in OS keyring
- **`tests/unit/test_code_parser.py`** — 36 unit tests
  - C# parser: file summary, class extraction, method extraction, XML doc comments, interface extraction, chunk ID format
  - TypeScript parser: React components, custom hooks, exported functions, interfaces, API routes, JSDoc comments
  - Generic parser: sliding window, chunk count, no duplicate IDs
  - Dispatcher: correct parser routing by file extension

---

### Phase 4 — Knowledge Base & Atlassian Integration

#### Added
- **`knowledge/embeddings.py`** — `EmbeddingService`
  - Embeds text via Ollama `nomic-embed-text` model
  - L2 cache key: `embed:{model}:{blake2b16(text)}`
  - `embed(text)`, `embed_batch(texts)`, singleton helpers
- **`knowledge/vector_store.py`** — `KnowledgeStore`
  - ChromaDB `PersistentClient` for production, `EphemeralClient` for tests
  - Collection `oapw_knowledge` with `{"hnsw:space": "cosine"}`
  - `add()`, `add_batch()`, `search()`, `exists()`, `delete()`, `count()`, `clear()`
  - `SearchResult.score` = `max(0, min(1, 1 - distance))` via `__post_init__`
  - Graceful `RuntimeError("chromadb is not installed")` when optional dep missing
- **`knowledge/rag.py`** — `RAGRetriever`
  - `KnowledgeSnippet` dataclass: id, text, source, title, url, score, metadata
  - `retrieve(query, top_k, min_score, source_filter, linked_jira)` — fetches top_k×2, filters below min_score, boosts Jira-linked results by 1.2×, returns sorted top_k
  - `format_context(snippets)` — Markdown-formatted context block for LLM injection
- **`enterprise/atlassian_client.py`** — `AtlassianClient`
  - Basic auth via `base64(email:token)`, token loaded from OS keyring
  - `get_jira_issue(key)`, `search_jira(jql, max_results)` → `JiraTicket`
  - `get_confluence_page(page_id)`, `search_confluence(cql, max_results)` → `ConfluencePage`
  - `find_linked_confluence(jira_key)` — resolves remote links from Jira to Confluence
  - ADF-to-text recursive walker, HTML-to-text via regex, acceptance criteria extractor
  - 1-day L2 cache TTL for all Atlassian API responses
  - `save_token(email, token)` / `load_token(email)` — OS keyring helpers
- **`enterprise/weighting.py`** — Confluence page relevance scoring
  - `weight_pages(pages, component, ref_date)` — returns pages sorted by relevance score
  - Recency weight (0.40): 90-day linear decay from last modified date
  - Owner weight (0.35): matches component name against author display name and space labels
  - Base weight (0.25): always present
  - `WeightedPage` dataclass with final `score`
- **`enterprise/traceability.py`** — `TraceabilityStore`
  - SQLite WAL database at `.oapw/traceability.db`
  - `traceability` table: test_path, jira_ids (JSON), confluence_ids (JSON), conf_versions (JSON)
  - `jira_test_index` table: bidirectional lookup from ticket → test paths
  - `link_test(test_path, jira_ids, confluence_ids)` — upsert + rebuild index
  - `tests_for_ticket(jira_key)` — all test paths covering a ticket
  - `record_for_test(test_path)` — full traceability record for a test
  - `coverage_summary()` — total tests traced, tickets covered, ticket keys
- **`enterprise/jira_ingest.py`** — `JiraIngestor`
  - `ingest_query(jql, max_results)` — searches Jira, converts to KB docs, batch upserts
  - Rich structured text per ticket: summary, description, AC, components, labels, status
  - `IngestResult` dataclass: added, total, errors
- **`enterprise/confluence_ingest.py`** — `ConfluenceIngestor`
  - `ingest_query(cql, max_results, component)` — applies recency/owner weighting before ingesting
  - Relevance weight stored as metadata for RAG scoring
- **`cache/l3_semantic.py`** — `L3SemanticCache`
  - ChromaDB collection `oapw_llm_cache` with cosine similarity
  - `get(prompt)` → `L3CacheHit(key, value, score)` or None; threshold 0.92
  - `set(prompt, value)` — stores JSON-serialised LLM response
  - Silent no-op when ChromaDB is unavailable
- **`cli/main.py`** — Added `kb` and `auth` sub-command groups
  - `oapw kb sync --jira JQL --confluence CQL --component NAME --max N`
  - `oapw kb stats`, `oapw kb clear`, `oapw kb coverage`
  - `oapw auth atlassian --email EMAIL [--token TOKEN]`
- **`core/config.py`** — Added `atlassian_url`, `atlassian_email` fields and `traceability_db` property
- **`cache/manager.py`** — Added embedding, jira, confluence convenience methods

#### Tests added
- `tests/unit/test_knowledge.py` — 20 tests (EmbeddingService, SearchResult, KnowledgeStore, RAGRetriever)
- `tests/unit/test_atlassian_client.py` — 17 tests
- `tests/unit/test_weighting.py` — 11 tests
- `tests/unit/test_traceability.py` — 9 tests
- `tests/unit/test_l3_cache.py` — 9 tests

---

### Phase 3 — Self-Healing Locators

#### Added
- **`healing/fingerprint.py`** — `ElementFingerprint`
  - Semantic fingerprint: role, tag, label, placeholder, type, testid, href, class, text
  - `fingerprint_from_element(data)` — constructs from JS evaluate result
  - `find_best_match(fp, candidates)` — Jaccard-similarity matching, returns (best, score)
  - `score_match(a, b)` — weighted field comparison
- **`healing/strategies.py`** — Three ordered healing strategies
  - `FingerprintStrategy` — O(n) DOM scan, no LLM call
  - `RoleTextStrategy` — deterministic Playwright `get_by_role` / `get_by_label` attempts
  - `LLMHealStrategy` — full LLM call with DOM context (expensive; result cached)
- **`healing/healer.py`** — `Healer` orchestrator
  - Tries strategies in order, returns first successful locator
  - Records all attempts to `HealingRecorder`
- **`healing/recorder.py`** — `HealingRecorder`
  - SQLite WAL at `.oapw/healing.db`
  - Records every healing event: original locator, strategy used, success/failure, latency
  - `stats()` — per-strategy success rates and counts
- **`agents/locator_resolver.py`** — 4-tier `LocatorResolver`
  - Tier 1: L1/L2 cache hit → `is_visible()` validation → return immediately
  - Tier 2: Stale cache → Healer pipeline → re-cache winner
  - Tier 3: Deterministic Playwright strategies (role, label, placeholder, text, testid)
  - Tier 4: LLM proposal → validate → cache
  - `_extract_fp(locator)` — uses `locator.evaluate()` JS (same INPUT_ROLES as dom.py)
  - `_try_deterministic()` returns `(Locator, LocatorCandidate)` tuple — winner strategy serialised to cache
- **`eval/golden_pages.py`** — 14 in-process HTML pages: login, signup, e-commerce, dashboard, settings, data table, modal dialog, multi-step wizard, search, accordion, accessible form, dynamic content, shadow DOM, navigation
- **`eval/golden_suite.py`** — `GoldenEvaluator` runs resolver against all 14 pages
- **`eval/metrics.py`** — `EvalMetrics`: pass rate, heal rate, avg latency, P95 latency
- **`tests/eval/conftest.py`** — `_isolated_cache` fixture: `monkeypatch.setenv("OAPW_DATA_DIR", ...)` + `reset_config()/reset_cache()` per test

#### Fixed
- `test_login_password_input` returning `email` type instead of `password`:
  - Root cause: `_extract_fp` scanned DOM elements list; always matched first input (email) for inputs with empty textContent
  - Root cause: `_build_cache_entry` stored `str(locator)` (internal repr) as CSS selector
  - Root cause: Stale L2 SQLite cache across test runs without isolation
  - Fix: Rewrote `_extract_fp` to call `locator.evaluate()` directly; changed `_try_deterministic` to return `(locator, LocatorCandidate)` pairs; added eval conftest for cache isolation

#### Tests added
- `tests/eval/test_golden_self_eval.py` — 14 golden evaluation tests
- `tests/unit/test_fingerprint.py` — 17 tests
- `tests/unit/test_healing_strategies.py` — 7 tests

---

### Phase 2 — AI-Powered Actions

#### Added
- **`core/ai_page.py`** — `AiPage` natural language page wrapper
  - `.ai(intent)` — plans and executes a single natural language action
  - `.ai_extract(query)` — extracts structured data from the page
  - `.ai_assert(statement)` — asserts a natural language statement about page state
  - `__getattr__` delegation — all standard Playwright `Page` methods pass through
- **`agents/models.py`** — Core data models
  - `Step` — single action with action type, target, value, strategy
  - `Plan` — ordered list of Steps with goal and page_signature
  - `LocatorCandidate` / `LocatorProposal` — locator resolution data
  - `LocatorStrategy` enum: CACHE, ROLE, LABEL, PLACEHOLDER, TEXT, TESTID, LLM
  - `ExtractionResult` — structured extraction output
- **`agents/planner.py`** — `Planner`
  - Goal + page DOM context → `Plan` via LLM (structured JSON output)
  - Cache key: `hash(goal + page_signature + model)`, 1-day TTL
- **`agents/executor.py`** — `Executor`
  - Executes `Plan.steps` sequentially
  - Calls `LocatorResolver` for all element interactions
  - Handles `click`, `fill`, `select`, `check`, `hover`, `assert`, `extract` step types
- **`core/dom.py`** — DOM snapshot utilities
  - `extract_interactive_elements(page)` — returns list of interactive elements with roles
  - `get_dom_context(page, max_elements)` — compact DOM summary for prompts
- **`core/aom.py`** — Accessibility Object Model
  - `get_aom_context(page)` — ARIA tree as text for prompt context
- **`prompts/`** — Jinja2 templates for all LLM interactions
  - `planner.j2`, `locator_resolve.j2`, `extract.j2`, `assert.j2`, `heal.j2`, `generate_test.j2`

#### Tests added
- `tests/unit/test_agent_models.py` — 18 tests
- `tests/unit/test_aom.py` — 5 tests
- `tests/unit/test_dom.py` — 7 tests
- `tests/unit/test_prompts.py` — 5 tests

---

### Phase 1 — Core Infrastructure

#### Added
- **`core/ollama_client.py`** — `OllamaClient`
  - Async httpx with streaming, configurable timeout
  - `generate(prompt, model, stream)`, `generate_json(prompt, schema)`, `embed(text, model)`
  - `is_running()`, `list_models()` for health checks
  - `get_ollama_client()` singleton
- **`core/config.py`** — `OapwConfig` (pydantic-settings)
  - `OAPW_` env prefix, `.env` file support
  - Fields: Ollama, browser, cache, RAM, Atlassian
  - `cache_dir`, `traces_dir`, `traceability_db` computed properties
  - `ensure_dirs()` — creates required directories
  - `get_config()` / `reset_config()` singletons
- **`cache/l1_memory.py`** — `L1Cache` (LRU, cachetools)
  - Optional TTL per entry; LRU eviction at `max_size`
  - `get()`, `set()`, `delete()`, `clear()`, `stats` property
- **`cache/l2_disk.py`** — `L2Cache` (SQLite WAL)
  - JSON serialisation; `expires_at` column for TTL
  - `get()`, `set()`, `delete()`, `prune()` (removes expired rows), `clear()`, `stats` property
- **`cache/manager.py`** — `CacheManager`
  - Read order: L1 → L2; Write order: L1 + L2 simultaneously
  - Bucket-level TTL policy; convenience methods per bucket type
  - `prune()`, `clear_all()`, `stats()`
  - `get_cache()` / `reset_cache()` singletons
- **`core/browser.py`** — `BrowserManager`
  - `managed_browser()` async context manager
  - Configures headless/headed, viewport, slow-mo from `OapwConfig`
  - `new_page()` context manager; `get_page_signature(page)` hash
- **`cli/main.py`** — `oapw` CLI (typer + rich)
  - `oapw doctor` — health check table
  - `oapw version` — version print
  - `oapw cache stats|prune|clear`
- **`pyproject.toml`** — Poetry project; `chromadb` as optional dep under `[extras] knowledge`
- **`PLAN.md`** — Full design document and implementation roadmap

#### Tests added
- `tests/unit/test_browser.py` — 4 tests
- `tests/unit/test_cache.py` — 16 tests
- `tests/unit/test_config.py` — 5 tests
- `tests/unit/test_ollama_client.py` — 4 tests
- `tests/unit/test_metrics.py` — 10 tests

---

[Unreleased]: https://github.com/your-org/oapw/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/oapw/releases/tag/v0.1.0
