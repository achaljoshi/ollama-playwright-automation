# oapw Architecture

> System design, data flows, and key design decisions.

---

## Table of Contents

- [System Overview](#system-overview)
- [Layer Map](#layer-map)
- [Request Data Flow](#request-data-flow)
- [Cache Architecture](#cache-architecture)
- [Self-Healing Pipeline](#self-healing-pipeline)
- [Knowledge Base Pipeline](#knowledge-base-pipeline)
- [Code Ingestion Pipeline](#code-ingestion-pipeline)
- [Configuration System](#configuration-system)
- [Key Design Decisions](#key-design-decisions)

---

## System Overview

oapw is a **local-first** AI automation framework. All AI inference runs via Ollama on the local machine — no cloud APIs, no data egress, no per-token billing.

```
┌─────────────────────────────────────────────────────────────────┐
│                         Test Code                               │
│   page.ai("Click Sign In")  /  resolver.resolve("email input")  │
└────────────────────┬────────────────────────────────────────────┘
                     │
         ┌───────────▼───────────┐
         │       AiPage          │  Natural language → Playwright calls
         │  Planner + Executor   │
         └───────────┬───────────┘
                     │
         ┌───────────▼───────────┐
         │   LocatorResolver     │  4-tier: cache → deterministic → LLM
         │   + Healer            │  + fingerprint-based self-healing
         └───────────┬───────────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼───┐    ┌───────▼──────┐  ┌─────▼──────┐
│  L1   │    │      L2       │  │     L3     │
│Memory │    │   SQLite      │  │  ChromaDB  │
│  LRU  │    │    (WAL)      │  │ (semantic) │
└───────┘    └──────────────┘  └─────┬──────┘
                                     │ miss
                              ┌──────▼──────┐
                              │   Ollama    │  qwen2.5:3b / :7b
                              │  (local)    │  nomic-embed-text
                              └─────────────┘

                 Knowledge Base (ChromaDB)
         ┌────────────────────────────────┐
         │  Jira tickets                  │
         │  Confluence pages              │  → RAGRetriever
         │  C# source code               │  → format_context()
         │  TypeScript/React source code  │  → injected into LLM prompts
         └────────────────────────────────┘
```

---

## Layer Map

| Layer | Module | Role |
|---|---|---|
| **Test API** | `core/ai_page.py` | `AiPage` — natural language page wrapper |
| **Planning** | `agents/planner.py` | Goal → ordered Step list via LLM |
| **Execution** | `agents/executor.py` | Step execution against live Playwright page |
| **Locator resolution** | `agents/locator_resolver.py` | 4-tier pipeline with caching |
| **Self-healing** | `healing/` | Fingerprint scan → role+text → LLM |
| **Cache L1** | `cache/l1_memory.py` | In-process LRU (cachetools), microseconds |
| **Cache L2** | `cache/l2_disk.py` | SQLite WAL, survives process restarts |
| **Cache L3** | `cache/l3_semantic.py` | ChromaDB semantic match (≥0.92 cosine) |
| **Cache manager** | `cache/manager.py` | Unified interface, bucket-level TTLs |
| **Hybrid API+UI** | `hybrid/` | Cookie-sharing ApiClient + HybridContext for combined tests |
| **Embeddings** | `knowledge/embeddings.py` | Ollama nomic-embed-text with L2 cache |
| **Vector store** | `knowledge/vector_store.py` | ChromaDB cosine-similarity store |
| **RAG retrieval** | `knowledge/rag.py` | Search + Jira boost + context formatting |
| **Atlassian client** | `enterprise/atlassian_client.py` | Jira REST + Confluence REST |
| **Code parsing** | `enterprise/code_parser.py` | C#, TypeScript, generic chunkers |
| **Code ingestion** | `enterprise/code_ingest.py` | Git clone/pull + incremental SHA sync |
| **Traceability** | `enterprise/traceability.py` | Test ↔ Jira ticket ↔ Confluence page links |
| **Config** | `core/config.py` | pydantic-settings, OAPW_* env prefix |
| **CLI** | `cli/main.py` | typer + rich CLI |

---

## Request Data Flow

### `await ai.ai("Click the Sign In button")`

```
1. AiPage.ai("Click the Sign In button")
   │
2. Planner.plan(goal, page)
   │  ├── cache.get_plan(hash(goal + page_signature)) → HIT → return cached Plan
   │  └── MISS → build DOM context → LLM prompt → Plan → cache.set_plan()
   │
3. Executor.execute(plan, page)
   │
4. For each Step:
   │  LocatorResolver.resolve("Sign In button")
   │    ├── Tier 1: cache.get_locator(key) → is_visible()? → return
   │    ├── Tier 2: cache hit but stale → Healer.heal()
   │    │     ├── FingerprintStrategy  (DOM scan)
   │    │     ├── RoleTextStrategy     (get_by_role, get_by_label, ...)
   │    │     └── LLMHealStrategy      (LLM + DOM context)
   │    ├── Tier 3: Deterministic (role=button name="Sign In")
   │    └── Tier 4: LLM proposal → validate → cache winner
   │
5. page.locator(...).click()  ← actual Playwright call
```

### `await store.search("user authentication")`

```
1. RAGRetriever.retrieve("user authentication", linked_jira=["AUTH-42"])
   │
2. EmbeddingService.embed("user authentication")
   │  ├── cache.get_embedding(blake2b(text)) → HIT → return vector
   │  └── MISS → ollama.embed(text, "nomic-embed-text") → cache.set_embedding()
   │
3. KnowledgeStore.search(vector, n_results=10)
   │  └── chroma.query(query_embeddings=[vector], n_results=10)
   │
4. Filter results below min_score (default 0.25)
5. Boost scores for docs with metadata.jira_id in linked_jira (× 1.2)
6. Sort descending, return top_k (default 5)
```

---

## Cache Architecture

### Three layers, one interface

```python
cache = get_cache()

# All three layers accessed through CacheManager
value = cache.get_llm(key)          # L1 → L2
cache.set_llm(key, value)           # L1 + L2 simultaneously
```

### L1 — In-memory LRU (`cache/l1_memory.py`)

- `cachetools.TTLCache` under the hood
- Default 512 entries maximum; evicts LRU on overflow
- Optional per-entry TTL
- Lives for the duration of the Python process
- Sub-microsecond reads

### L2 — SQLite WAL (`cache/l2_disk.py`)

- Single `cache.db` file in `.oapw/cache/`
- WAL mode for concurrent reads without locking
- Schema: `(key TEXT PK, value TEXT, expires_at REAL | NULL)`
- `prune()` removes rows where `expires_at < now()`
- On L2 hit, value is promoted back into L1 (no TTL — LRU eviction)

### L3 — Semantic (`cache/l3_semantic.py`)

- ChromaDB collection `oapw_llm_cache`
- Only used for LLM prompt/response caching
- On `get(prompt)`: embeds the prompt, queries ChromaDB for nearest neighbour
  - Score ≥ 0.92 → return cached response (`L3CacheHit`)
  - Score < 0.92 → miss
- Catches prompts that differ in whitespace/phrasing but ask the same thing
- Silent no-op if ChromaDB is not installed

### Bucket TTLs

| Bucket | TTL | Rationale |
|---|---|---|
| `llm` | 30 days | LLM responses rarely change for the same page |
| `locator` | 7 days | UIs change weekly at most |
| `plan` | 1 day | Page structure changes more frequently |
| `embedding` | Never | Embeddings are deterministic; model doesn't change |
| `jira` | 1 day | Ticket content changes daily |
| `confluence` | 1 day | Page content changes daily |
| `negative` | 5 minutes | Prevents retry storms on transient failures |

---

## Self-Healing Pipeline

Triggered when a cached locator is found but `is_visible()` returns false (stale cache):

```
Healer.heal(intent, page, fingerprint)
   │
   ├── 1. FingerprintStrategy
   │     extract_interactive_elements(page) → all interactive elements
   │     find_best_match(stored_fp, candidates) → Jaccard similarity scoring
   │     threshold: 0.7  → if best score ≥ 0.7, return that locator
   │
   ├── 2. RoleTextStrategy
   │     Tries (in order):
   │       page.get_by_role(stored_role, name=stored_label)
   │       page.get_by_role(stored_role, name=stored_name_variants)
   │       page.get_by_label(stored_label)
   │       page.get_by_placeholder(stored_placeholder)
   │
   └── 3. LLMHealStrategy
         DOM context + stored fingerprint → LLM prompt (heal.j2)
         LLM proposes new CSS/XPath selector
         Validates: page.locator(selector).is_visible()
         Caches result (TTL: locator TTL)
```

All healing events are recorded in `.oapw/healing.db`:
- Original locator, strategy used, new locator, success/failure, latency
- Queryable via `HealingRecorder.stats()` for monitoring

### ElementFingerprint

The fingerprint is what allows the healer to find the "same" element after UI changes:

```python
@dataclass
class ElementFingerprint:
    role: str           # "textbox", "button", "link", etc.
    tag: str            # "input", "button", "a"
    text: str           # visible text content (≤80 chars)
    label: str | None   # aria-label or <label> text
    placeholder: str | None
    type: str | None    # for <input>: "email", "password", etc.
    href: str | None    # for links
    testid: str | None  # data-testid attribute
    cls: str | None     # className (first 100 chars)
```

Fingerprints are extracted using `locator.evaluate()` with inline JS — matching the same `INPUT_ROLES` mapping used by `dom.py` to ensure consistency.

---

## Knowledge Base Pipeline

### Ingestion flow

```
Source (Jira / Confluence / Git repo)
   │
   ├── JiraIngestor.ingest_query(jql)
   │     AtlassianClient.search_jira(jql)
   │     _ticket_to_doc(ticket) → structured text
   │
   ├── ConfluenceIngestor.ingest_query(cql, component)
   │     AtlassianClient.search_confluence(cql)
   │     weight_pages(pages, component) → sorted by relevance
   │     _page_to_doc(page, weight) → structured text
   │
   └── CodeIngestor.sync_repo(config)
         git clone / git pull
         git diff --name-only {last_sha} HEAD → changed files
         parse_file(path) → [CodeChunk, ...]
         chunk.to_kb_doc() → {"id", "text", "metadata"}
         │
         ▼
   KnowledgeStore.add_batch(docs)
         EmbeddingService.embed_batch(texts) → [[float], ...]
         ChromaDB.upsert(ids, embeddings, documents, metadatas)
```

### Retrieval flow

```
RAGRetriever.retrieve(query, linked_jira=["PROJ-1"], top_k=5)
   │
   EmbeddingService.embed(query) → vector
   KnowledgeStore.search(vector, n_results=10)
   │
   Filter: score ≥ min_score (default 0.25)
   Boost:  if metadata.jira_id in linked_jira → score × 1.2
   Sort:   descending by score
   Slice:  return top_k results
   │
   RAGRetriever.format_context(snippets)
   → ### Title [SOURCE] (relevance: 0.87)
     Body text (max 500 chars)...
```

### Confluence page weighting

Before ingesting, pages are scored by relevance to the component being tested:

```
score = 0.25 (base)
      + 0.40 × recency_factor   (1.0 if modified today, 0.0 if ≥ 90 days ago)
      + 0.35 × owner_factor     (1.0 if author/label matches component name)
```

Pages with higher scores are ingested first and their weight is stored as metadata.

---

## Code Ingestion Pipeline

### First sync (full index)

```
CodeIngestor.sync_repo(config)
   git clone {auth_url} {local_path} --branch {branch} --depth 1
   git rev-parse HEAD → current_sha
   Walk all files in repo:
     Skip _SKIP_DIRS (node_modules, .git, bin, obj, dist, ...)
     Skip files > 300 KB
     Skip non-indexable extensions
     parse_file(path) → [CodeChunk, ...]
     Batch upsert every 20 docs
   cache.set("code", f"last_sha:{repo_name}", current_sha)
```

### Incremental sync (subsequent runs)

```
last_sha = cache.get("code", f"last_sha:{repo_name}")
git pull origin {branch}
current_sha = git rev-parse HEAD
if current_sha == last_sha: return (no changes)
changed_files = git diff --name-only {last_sha} {current_sha}
Parse and re-index only changed files
cache.set("code", f"last_sha:{repo_name}", current_sha)
```

### Language-aware chunking

```
parse_file(path) → dispatcher
   .cs  → parse_csharp()
   .ts .tsx .js .jsx → parse_typescript()
   other → parse_generic()

parse_csharp(source, repo_name, repo_url, file_path):
   1. file_summary chunk (first ~60 lines)
   2. For each class/interface found (regex):
      - Extract XML /// doc comments above
      - Extract class body
      - For each method (regex):
        - Extract XML doc + method signature + body

parse_typescript(source, ...):
   1. file_summary chunk
   2. React components (uppercase function/const, contains JSX markers)
   3. Custom hooks (use* prefix)
   4. Exported functions
   5. Type/interface definitions
   6. API route handlers (router.get/post/put/delete)

parse_generic(source, ...):
   Sliding window: 80-line windows, 60-line step (20-line overlap)
```

---

## Configuration System

`OapwConfig` is a `pydantic-settings` `BaseSettings` subclass:

1. Reads from `OAPW_*` environment variables (highest priority)
2. Reads from `.env` file in the working directory
3. Falls back to field defaults

The singleton is accessed via `get_config()` and can be reset with `reset_config()` (important in tests to pick up per-test `monkeypatch.setenv` changes).

See **[docs/configuration.md](configuration.md)** for all settings.

---

## Key Design Decisions

### Why Ollama (not OpenAI / Anthropic)?

- **Privacy** — source code, Jira tickets, and Confluence pages never leave the machine
- **Cost** — zero per-token billing; CI runs are free
- **Offline** — works without internet after models are pulled
- **Tradeoff** — smaller models (3b–7b) are less capable; aggressive caching compensates

### Why ChromaDB as optional?

- Most CI environments don't need semantic search
- The framework is fully functional without it (L1+L2 cache only)
- Installing ChromaDB adds ~500 MB; not appropriate for every project
- `poetry install --extras knowledge` enables it explicitly

### Why SQLite for L2 (not Redis)?

- Zero infrastructure — just a file
- WAL mode gives good concurrent read performance
- Survives process restarts, container restarts
- Sufficient for single-machine local-first use case

### Why sequential code repo sync?

- `sync_all()` processes repos one at a time
- Each repo can generate thousands of embedding requests
- Parallel embedding on an 8 GB machine causes OOM
- Tradeoff: slower, but reliable on the minimum hardware target

### Why Jaccard similarity for fingerprint matching?

- Fingerprints are small bags of string fields
- Jaccard is O(1) per pair (intersection/union of non-null fields)
- No LLM call needed — orders of magnitude cheaper than cosine on embeddings
- Good enough: same element across UI changes will share most fields (role, type, label)

### Why blake2b for cache keys (not sha256)?

- blake2b is ~3× faster than sha256 in CPython
- 16-byte (128-bit) digest has effectively zero collision probability for cache keys
- No cryptographic requirements — just stable, fast, deterministic hashing
