# Ollama + Playwright AI Automation Framework

> Local-first AI quality engineering platform. Combines Playwright for browser control, Ollama for local LLM reasoning, multi-layer caching for speed, a knowledge base fed by Jira + Confluence so it knows your business logic, and a QA Agent that can be told "regress the login flow on QA" and figure out the rest — like a junior QA engineer that never sleeps and reads every spec.

---

## Table of Contents
- [1. Vision & Goals](#1-vision--goals)
- [2. Locked Decisions](#2-locked-decisions)
- [3. Architecture](#3-architecture)
- [4. Core Components](#4-core-components)
- [5. Key Features](#5-key-features)
- [6. Caching Architecture](#6-caching-architecture)
- [7. QA Agent Mode](#7-qa-agent-mode)
- [8. Enterprise Knowledge Integration (Jira + Confluence)](#8-enterprise-knowledge-integration-jira--confluence)
- [9. Implementation Phases](#9-implementation-phases)
- [10. Tech Stack](#10-tech-stack)
- [11. Hardware Profiles](#11-hardware-profiles-m1-air--beyond)
- [12. Folder Structure](#12-folder-structure)
- [13. Code Sketches](#13-code-sketches)
- [14. Risks & Mitigations](#14-risks--mitigations)
- [15. Success Metrics](#15-success-metrics)
- [16. Roadmap](#16-roadmap)

---

## 1. Vision & Goals

Build an **AI-first quality engineering platform** that:

- Uses **Playwright** for reliable, cross-browser automation
- Uses **Ollama** for local, private LLM inference (no API costs, no data leakage)
- Accepts **natural language commands** (Browser-use / Stagehand style)
- Provides **self-healing locators** that auto-recover from UI changes
- Uses **aggressive multi-layer caching** so re-runs feel native, even on 8GB hardware
- Integrates **Jira + Confluence** so the framework knows business logic, not just UI behavior
- Offers a **QA Agent Mode** where you describe what you want tested in plain English

### Primary use cases
1. Test engineers writing flake-resistant E2E tests
2. QA teams running regression on every deployment via chat/CI
3. Generating tests directly from Jira tickets with acceptance criteria
4. Browser scraping pipelines that survive UI redesigns

---

## 2. Locked Decisions

| Decision | Choice | Why |
|---|---|---|
| **Language** | Python 3.11+ | Best AI ecosystem; Ollama, Pydantic-AI, ChromaDB all Python-first |
| **Browser** | Playwright (Python bindings) | Modern, fast, multi-browser, great trace viewer |
| **LLM runtime** | Ollama (local) | Free, private, easy model swap |
| **Agent orchestration** | Pydantic-AI | Typed, lean, native Ollama support |
| **Vector store** | ChromaDB (embedded) | Zero infra; swap to Qdrant later if needed |
| **Cache backend** | SQLite + in-memory LRU | Zero deps, fast, file-portable |
| **Enterprise data** | Atlassian MCP server | Official, uniform LLM interface, no custom REST glue |
| **Test runner** | Pytest + custom plugin | Standard, extensible |
| **Reference hardware** | M1 MacBook Air, 8GB | If it runs there, it runs anywhere |
| **TypeScript port** | Deferred (Phase 10+) | Python first, ship faster |

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       QA Agent Mode                           │
│   Goal Parser • Test Selector • Smart Executor • Judgment    │
│   Engine • Investigator • Reporter • QA Memory               │
└────────────────────────┬─────────────────────────────────────┘
                         │ uses
┌────────────────────────▼─────────────────────────────────────┐
│                  Test / Scenario Layer                        │
│   Pytest • Natural Language Specs • CLI • Python API         │
└─────────────────────────┬────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│              Agent Orchestrator (Pydantic-AI)                 │
│   Planner • Executor • Locator Resolver • Healer • Verifier   │
└──┬───────────────────────────────────┬───────────────────────┘
   │                                   │
┌──▼─────────────────────────────┐ ┌───▼───────────────────────┐
│   Cache Layer (load-bearing)   │ │   Playwright Controller   │
│   L1 in-memory LRU             │ │   browsers • contexts     │
│   L2 SQLite (.oapw/cache/)     │ │   tracing • DOM/AOM       │
│   L3 ChromaDB (semantic)       │ │   API client (hybrid)     │
└──┬─────────────────────────────┘ └───────────────────────────┘
   │ (miss)                          ▲
┌──▼────────────┐    ┌────────────────┴─────────┐
│    Ollama     │    │   Knowledge Base         │
│    LLMs       │    │   - Locators / DOMs      │
│ qwen2.5:3b    │    │   - Run history          │
└───────────────┘    │   - Jira tickets ────────┼──┐
                     │   - Confluence pages ────┼──┤
                     │   - QA Memory            │  │
                     └──────────────────────────┘  │
                                                   │
                     ┌─────────────────────────────▼──┐
                     │   Atlassian MCP Server         │
                     │   (live lookups + bulk sync)   │
                     │   Jira • Confluence            │
                     └────────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────┐
│         Observability • Reports • CI/CD • ChatOps             │
│  Allure • HTML report • OTel • GitHub Actions • Slack bot    │
└──────────────────────────────────────────────────────────────┘
```

### Design principles
- **Local-first** for LLM/automation; **enterprise-connected** for business context
- **Cache before compute** — every LLM call goes through L1→L2→L3 first
- **Deterministic fallback** — `getByRole`/`getByText` before LLM
- **Hybrid API + UI** — set up state via API, verify via UI
- **Two integration modes for Atlassian** — bulk sync (push) for scale, live MCP queries (pull) for freshness
- **Judgment, not autonomy** — agent escalates uncertainty; never auto-files bugs

---

## 4. Core Components

### 4.1 Browser Automation (Playwright)
Multi-browser, persistent contexts, trace viewer, built-in API client for hybrid workflows.

### 4.2 LLM Integration (Ollama)
Local server, per-task model registry (see [§11](#11-hardware-profiles-m1-air--beyond)), structured outputs via JSON schema.

### 4.3 Cache Layer
See [§6](#6-caching-architecture). Hot path for every action.

### 4.4 Knowledge Layer (ChromaDB)
Indexes: locators per page, DOM snapshots, run history, user stories, **Jira tickets**, **Confluence pages**, known issues, deployment history. See [§8](#8-enterprise-knowledge-integration-jira--confluence) for enterprise data sources.

### 4.5 Agent Layer (Pydantic-AI)
| Agent | Job |
|-------|-----|
| **Planner** | NL goal → step list |
| **Executor** | Run each step via Playwright |
| **Locator Resolver** | "the submit button" → CSS/XPath/role |
| **Healer** | On failure, propose & try new locators |
| **Verifier** | Assert step intent achieved |

### 4.6 QA Agent Layer
See [§7](#7-qa-agent-mode). Higher-level orchestration; consumes business context from [§8](#8-enterprise-knowledge-integration-jira--confluence).

### 4.7 Test Framework Layer
Pytest plugin, Allure + HTML reports, failure artifacts, GitHub Actions template.

---

## 5. Key Features

### 5.1 Self-Healing Locators
On failure: fingerprint, cache→vector→LLM, validate live, cache winner. Priority: cached → `getByRole` → text/label/placeholder → test-ids → LLM-generated.

### 5.2 Natural Language Actions
```python
await page.ai("Click the 'Sign in with Google' button")
await page.ai("Fill in the search box with 'laptops under 50000'")
price = await page.ai_extract("Price of first product as a number")
```

### 5.3 Test Case Generator
Inputs: **Jira tickets with acceptance criteria** (primary), user stories, existing tests (mutation), live URLs, API specs. Output: ready-to-run Pytest files with traceability headers linking back to source.

### 5.4 Knowledge Loop
Every run feeds locator mappings, failure patterns, healings, and **test ↔ ticket mappings** back into the vector store.

### 5.5 Hybrid API + UI Workflows
Set up state via API (fast, deterministic), verify via UI (the part that matters):
```python
user = await api.users.create({"email": "test@example.com"})
await api.carts.add_item(user.id, "SKU-123")
await page.goto(f"/cart?token={user.token}")
await page.ai_assert("Cart shows 1 laptop at ₹49,999")
```
Includes OpenAPI-driven client generation and recording mode.

### 5.6 Test Data & Fixtures
- Factories (`polyfactory` + Pydantic), deterministic seeds, configurable isolation modes
- Cleanup hooks with timeout-safe teardown
- `@pii` field tagging — sensitive fields masked before LLM

### 5.7 Multi-Faceted Verification
- **Visual regression** (16GB+ only) — semantic-same judgment via vision model
- **Accessibility** — axe-core integration, reuses our AOM extraction for free
- **Performance** — Core Web Vitals + custom marks per test

### 5.8 Framework Self-Evaluation
Golden test set the framework runs against itself (canonical pages, known-broken variants). Metrics tracked over time: healing success rate, prompt latency p50/p95, cache hit rate. **CI gates on this for any prompt/model change.**

---

## 6. Caching Architecture

On 8GB M1, caching is **load-bearing**. Cold 10-LLM-call run is ~40s; warm is ~3–5s.

### 6.1 Three Cache Layers

| Layer | Backend | Lookup | Lifetime | Purpose |
|---|---|---|---|---|
| **L1: Memory** | LRU dict | <1ms | Process | Hot path in one test run |
| **L2: Disk** | SQLite | 1–5ms | Days–weeks | Cross-run, per-project |
| **L3: Semantic** | ChromaDB | 20–50ms | ∞ | Fuzzy "similar prompt" match |

### 6.2 What Gets Cached

| Cache | Key | Layers | TTL | Validation |
|---|---|---|---|---|
| **LLM responses** | `hash(prompt + model + temp)` | L1+L2 | 30 days | Model-version aware |
| **Locators** | `(intent, page_signature)` | L1+L2 | 7 days | `is_visible()` on use |
| **Embeddings** | `hash(content)` | L2 | ∞ | Content-addressed |
| **Plans** | `(goal, page_signature)` | L2 | 1 day | DOM hash match |
| **Jira/Confluence** | `(id, version)` | L2 | 1 day | Re-fetch if stale |
| **Negative results** | `(intent, page_signature)` | L1 | 5 min | Stops retry storms |

### 6.3 Page Signature
```python
def page_signature(page) -> str:
    skeleton = extract_skeleton(await page.content())
    return blake2b(skeleton.encode(), digest_size=16).hexdigest()
```

### 6.4 Performance Impact (8GB M1, qwen2.5:3b)

| Scenario | Cold | Warm | Speedup |
|---|---|---|---|
| Single LLM call | 2–5s | <10ms | ~500× |
| Locator resolve | 3–8s | 50–100ms | ~50× |
| 10-step test | 30–50s | 3–6s | ~10× |
| 50-test suite | 25–40 min | 4–8 min | ~5× |

### 6.5 CLI
```bash
oapw cache stats / clear / prune / warm / export / import
```

---

## 7. QA Agent Mode

An autonomous QA agent — invoked via CLI, Slack, or CI webhook — that uses everything below as primitives.

> "Hey @oapw, run a quick regression of the login flow on QA."

### 7.1 vs. a Test Runner

| Human QA does | QA Agent equivalent |
|---|---|
| Reads ticket, decides what to test | Goal Parser + Test Selector |
| Runs the relevant tests | Smart Executor |
| Decides if a failure is real | Judgment Engine (now consults [§8](#8-enterprise-knowledge-integration-jira--confluence)) |
| Digs into why something broke | Investigator |
| Files a useful bug report | Reporter (drafts JIRA via Atlassian MCP) |
| Remembers known issues | QA Memory |

### 7.2 Triggers
- **CLI**: `oapw qa "regression of login on QA"`
- **Slack/Teams**: `@oapw run smoke tests on staging`
- **CI webhook**: post-deploy regression
- **Schedule**: every 30 min on prod canary
- **PR comment**: `/oapw test this on review-env-123`

### 7.3 Flow

```
Deployment / Slack command / Schedule
            │
            ▼
    ┌───────────────┐
    │ Goal Parser   │
    └───────┬───────┘
            ▼
    ┌───────────────┐     ┌──────────────────┐
    │ Test Selector │ ◄── │ KB + QA Memory   │
    └───────┬───────┘     │ + Jira/Confluence│
            │             └──────────────────┘
            ▼
    ┌───────────────┐
    │ Smart Executor│ ──► agents §4.5 + cache §6
    └───────┬───────┘
            ▼ per-test result
    ┌───────────────┐
    │ Judgment LLM  │ → consults Confluence specs
    └───────┬───────┘     for "is observed correct?"
            ▼ on fail / unclear
    ┌───────────────┐
    │ Investigator  │ → Jira history, git, related tests
    └───────┬───────┘
            ▼
    ┌───────────────┐
    │ Reporter      │ → Slack + Allure + JIRA draft
    └───────────────┘
```

### 7.4 Judgment Engine *(the magic)*

```python
class Judgment(BaseModel):
    classification: Literal["pass", "real_bug", "flaky", "env_issue", "data_issue", "unclear"]
    confidence: float
    hypothesis: str
    evidence: list[str]
    suggested_action: Literal["file_bug", "retry", "investigate", "ignore", "escalate"]
```

Inputs: expected behavior, observed DOM diff, screenshots, network logs, **relevant Confluence pages**, **related Jira history**, deployment delta.

### 7.5 Example Interaction

```
[Slack] @oapw run login regression on QA

[oapw] Running login regression on QA env...
       Found 8 relevant tests (6 from JIRA-PROJ epic AUTH-1).
       Estimated time: 3–5 min (warm cache).

[oapw] ▶ Smoke: login_valid (3.2s) ✓
       ▶ Smoke: login_invalid_pw (2.8s) ✓
       ▶ Critical: forgot_password_email (4.1s) ✗
       ▶ Regression: 5 more passing...

[oapw] ──── Done: 7/8 passed ────

       ❌ forgot_password_email
       Expected: email modal appears on click (per Confluence
                 "Authentication Flows" §3.2)
       Observed: button click, no network call, no modal

       🧠 Judgment: real_bug (confidence: 0.85)
       Hypothesis: Modal trigger is wired up but fires nothing.
       Confluence spec confirms the expected behavior.

       🔍 Investigation:
       - No related auth tests failing → not env-wide
       - Commit a3f7e21 touched /modals/auth.tsx 6h ago
       - JIRA-AUTH-892 (closed last sprint) was similar; check regression
       - API /auth/reset-password responds 200 to direct call

       🎯 Suggested action: open JIRA, assign to auth team
       Draft ticket: [link — linked to Confluence spec + trace]
```

### 7.6 Boundaries
- Drafts bugs, doesn't auto-file
- Doesn't auto-fix code
- Doesn't run destructive ops on prod without human-in-loop
- Escalates uncertainty (confidence < 0.6)

---

## 8. Enterprise Knowledge Integration (Jira + Confluence)

The framework's value compounds when it knows your business logic, not just your UI. Jira holds the *what* and *why* (tickets, acceptance criteria, bug history). Confluence holds the *how it's supposed to work* (specs, design docs, runbooks).

### 8.1 Integration Strategy: Push + Pull

Two modes, mirroring the cache layers:

| Mode | When | Tool | Latency | Freshness |
|---|---|---|---|---|
| **Bulk sync (push)** | Scheduled (hourly) or webhook | Atlassian MCP + ingestion pipeline | One-time cost | Hours stale |
| **Live query (pull)** | Agent needs current state | Atlassian MCP at runtime | 200ms–1s | Real-time |

Bulk-sync handles "what does the spec say about discounts" (rarely changes). Live-query handles "is JIRA-123 still in progress" (changes hourly).

### 8.2 What We Ingest

**From Jira** (via JQL):
- Open user stories with acceptance criteria (highest signal)
- Recently closed bugs (for "has this broken before" history)
- Epic descriptions for context
- Component / label / fix-version taxonomy
- Comments threads for clarifications

**From Confluence** (via CQL):
- Pages tagged as requirements / specs
- Architecture and business logic docs
- Test plans and runbooks
- Recently edited pages preferred (see [§8.6](#86-data-quality--staleness))

### 8.3 Use Cases Unlocked

**A. Generate tests directly from a Jira ticket**
```bash
oapw generate --from-jira PROJ-1234
# → Reads ticket: title, description, acceptance criteria
# → Follows linked Confluence pages
# → Generates Pytest files with traceability header
# → Tags tests with PROJ-1234 for two-way navigation
```

Generated file header:
```python
"""
Source: JIRA PROJ-1234 "User can reset password via email"
Requirements: CONF page "Authentication Flows" v3 (edited 2 days ago)
Acceptance criteria covered: AC1, AC2, AC4
Acceptance criteria NOT covered: AC3 (requires email inbox access — manual test)
Generated: 2024-01-15 by oapw v0.4.0
"""
```

**B. Business-context judgment** (QA Agent Judgment Engine):
- Test expects 5% discount, observes 0%
- Agent retrieves Confluence "Discount Rules"
- Spec: "5% applies to first-time buyers only"
- Test data: existing user → observed behavior is correct, **test is wrong**
- Classification: `data_issue`, not `real_bug`

**C. Bug filing with full provenance**
Drafted JIRA tickets include:
- Reproduction steps from Playwright trace
- Link to failing test file + git blame
- Link to original requirement page in Confluence
- Semantic-search results: 3 most-similar past bugs from Jira history
- Component/team auto-suggested from Jira component metadata

**D. Deploy-aware targeted regression**
```bash
oapw qa --deployment-tickets PROJ-1234,PROJ-1240,PROJ-1255
# → KB lookup: tests tagged with those tickets
# → Tests on affected Confluence pages
# → Runs that targeted suite
```

**E. Coverage tracking**
```bash
oapw coverage --sprint 42
# → Which acceptance criteria have automated tests
# → Which don't (with suggested test stubs)
# → Which tests cover requirements that changed since last run
```

### 8.4 Traceability Model

Bi-directional links in QA Memory:

```
Jira Ticket  ←→  Generated Test  ←→  Test Run Results
     ↕                                       ↕
Confluence Page (versioned)            Failure Trace
```

A `traceability` SQLite table:
```
test_path | jira_ids | confluence_page_ids | conf_versions | generated_at
```

This is what powers the coverage report and the "tests affected by this PR" view.

### 8.5 Authentication & Security

- Atlassian token in **OS keyring** (not env files, not `.env`)
- Read-only by default; write scopes (creating JIRA drafts) opt-in per project
- Per-project Jira project allowlist — never query unrelated projects
- PII regex pass on ticket descriptions before sending to LLM
- Audit log: every Atlassian fetch logged with `(user, query, ticket_ids, timestamp)`
- Optional: redact custom fields (e.g., customer names) via config

### 8.6 Data Quality & Staleness

Confluence is full of outdated docs. Mitigations:

- **Recency weighting** — pages edited in last 90 days score higher in retrieval
- **Owner weighting** — pages owned by the relevant team (matched via Jira component) score higher
- **Access-frequency weighting** — frequently-viewed pages assumed more authoritative
- **Version snapshots** — every retrieved page stored with its Confluence version number, so "regenerate tests" knows whether the spec changed
- **Surfaced provenance** — every generated test header shows source page + last-edit date so reviewers can sanity-check

### 8.7 Extensibility

Same architecture supports other sources via MCP:
- **Linear** for tickets (alternative to Jira)
- **Notion** for docs (alternative to Confluence)
- **GitHub Issues** / **GitLab** for tickets
- **Slack** for "what did the team decide in #qa-channel"

The connector layer is pluggable; Jira+Confluence is the v1 reference impl.

---

## 9. Implementation Phases

### Phase 1 — Foundation *(Weeks 1–2)*
Repo scaffold, Poetry, CI, Playwright async wrapper, Ollama client, cache module skeleton (L1+L2), `oapw doctor`.

### Phase 2 — AI-Powered Actions *(Weeks 3–4)*
DOM serializer, AOM extractor, `page.ai(intent)` API, planner→executor pipeline, LLM response cache wired.

### Phase 3 — Self-Healing Locators *(Weeks 5–6)*
Semantic fingerprinting, page signatures, locator cache with validate-on-use, healing pipeline, **golden self-eval set**.

### Phase 4 — Knowledge Base + Atlassian Integration *(Weeks 7–9)*
ChromaDB, embedding pipeline, L3 semantic cache. **Atlassian MCP connector**, Jira/Confluence ingestion pipeline, recency/owner weighting, version snapshots, traceability schema.

### Phase 5 — Hybrid API+UI & Test Data *(Weeks 10–11)*
API client integration, factory framework, fixtures, PII masking.

### Phase 6 — Test Generator *(Weeks 12–13)*
User-story → Pytest, **`--from-jira` mode**, live-crawl smoke generator, edge case mutator, traceability headers.

### Phase 7 — Agent System *(Weeks 14–15)*
Pydantic-AI orchestration, plan cache, loop guards, human-in-loop hooks.

### Phase 8 — QA Agent Mode *(Weeks 16–19)*
Goal Parser, Test Selector, Smart Executor, Judgment Engine (with business-context retrieval), Investigator (Jira history + git), Reporter (Slack/Allure/JIRA-draft), QA Memory.

### Phase 9 — Multi-Faceted Verification *(Weeks 20–21)*
Accessibility (axe-core), performance capture, visual regression (16GB+ only).

### Phase 10 — Productionization *(Weeks 22–23)*
Pytest plugin packaging, Allure polish, GitHub Action template, Slack bot, MkDocs site, example projects.

---

## 10. Tech Stack

| Concern | Tool | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Package mgr | Poetry | |
| Browser | Playwright (async) | + `request_context` for API |
| LLM runtime | Ollama | `brew install ollama` |
| Agent framework | Pydantic-AI | typed, lean |
| Vector DB | ChromaDB | embedded |
| Cache | SQLite + `cachetools` LRU | |
| Test runner | Pytest + pytest-asyncio | |
| Factories | polyfactory + Pydantic | |
| Accessibility | playwright-axe | |
| **Enterprise data** | **Atlassian MCP server** | **Jira + Confluence** |
| **MCP client** | **mcp Python SDK** | **for Atlassian queries** |
| Reporting | Allure + custom HTML | |
| ChatOps | slack-bolt | Slack bot for QA Agent |
| CI | GitHub Actions | `macos-latest` for M1 parity |
| Secrets | keyring (OS-native) | not env files |
| Observability | OpenTelemetry | optional, Phase 10 |
| Lint/format | Ruff + Black + Mypy | |

---

## 11. Hardware Profiles (M1 Air & Beyond)

### M1 Air, 8GB (primary target — your machine)
| Task | Model | Size (Q4) |
|---|---|---|
| Everything | `qwen2.5:3b` | ~2 GB |
| Embeddings | `nomic-embed-text` | ~270 MB |
| Vision | *skip on 8GB* | — |

**Required Ollama env** (`~/.zshrc`):
```bash
export OLLAMA_KEEP_ALIVE=5m
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
```

### M1 Air, 16GB
| Task | Model | Size |
|---|---|---|
| Planner / Judgment | `qwen2.5:7b` | ~4.5 GB |
| Code / locators | `qwen2.5-coder:7b` | ~4.5 GB |
| Vision | `llava:7b` | ~4.5 GB |

### Bootstrap (8GB)
```bash
brew install ollama
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

---

## 12. Folder Structure

```
ollama-playwright-automation/
├── src/oapw/
│   ├── core/                     # Playwright wrapper, Ollama client, config
│   ├── cache/                    # L1+L2+L3, @cached, CLI
│   ├── agents/                   # planner, executor, locator_resolver, healer, verifier
│   ├── qa_agent/                 # goal_parser, test_selector, executor, judgment,
│   │                             # investigator, reporter/, memory
│   ├── knowledge/                # Chroma, embeddings, fingerprint, rag
│   ├── enterprise/               # NEW — Atlassian integration
│   │   ├── atlassian_mcp.py      # MCP client wrapper
│   │   ├── jira_ingest.py        # JQL-driven ingestion
│   │   ├── confluence_ingest.py  # CQL-driven ingestion
│   │   ├── weighting.py          # recency/owner/access scoring
│   │   ├── traceability.py       # test ↔ ticket ↔ page links
│   │   └── connectors/           # pluggable: linear.py, notion.py, github.py
│   ├── healing/                  # strategies, locator cache
│   ├── generators/               # from_user_story, from_jira, from_crawl, mutator
│   ├── hybrid/                   # API+UI bridge
│   ├── factories/                # test data factories
│   ├── verification/             # a11y, visual, perf
│   ├── eval/                     # framework self-eval
│   ├── security/                 # PII masking, secrets (keyring), audit log
│   ├── plugin/                   # pytest plugin
│   └── cli/                      # `oapw` command
├── tests/{unit,eval,examples}/
├── prompts/                      # versioned Jinja templates
├── docs/                         # MkDocs
├── .oapw/                        # cache + traces + QA memory + traceability.db (gitignored)
├── .github/workflows/
│   ├── ci.yml
│   ├── self-eval.yml             # runs on prompt/model changes
│   └── qa-on-deploy.yml
├── pyproject.toml
├── README.md
└── PLAN.md
```

---

## 13. Code Sketches

### Generate tests from Jira
```bash
oapw generate --from-jira PROJ-1234 --out tests/generated/
```

```python
# oapw/generators/from_jira.py
async def generate_from_jira(ticket_id: str) -> Path:
    ticket = await atlassian.get_jira_issue(ticket_id)
    linked_pages = await atlassian.get_linked_confluence(ticket)
    weighted_pages = weight_by_recency_and_ownership(linked_pages, ticket.component)
    context = build_context(ticket, weighted_pages)
    test_code = await llm.generate_test(context, model=DEFAULT_MODEL)
    return write_test_file(test_code, traceability={
        "jira": ticket_id,
        "confluence": [p.id for p in weighted_pages],
        "versions": {p.id: p.version for p in weighted_pages},
    })
```

### Business-context judgment
```python
async def judge(observation, expected, test_meta) -> Judgment:
    # Pull relevant business context
    specs = await rag.retrieve(
        query=expected,
        filters={"source": "confluence", "linked_jira": test_meta.jira_ids},
        top_k=3,
    )
    history = await atlassian.search_similar_bugs(observation, top_k=5)

    return await llm.classify(
        prompt=JUDGMENT_PROMPT,
        inputs={"expected": expected, "observed": observation,
                "specs": specs, "history": history},
        schema=Judgment,
    )
```

### QA Agent CLI
```bash
oapw qa "regression of login on qa"
oapw qa --deployment-tickets PROJ-1234,PROJ-1240
oapw coverage --sprint 42
```

### Cache-first locator (unchanged)
```python
async def resolve(self, intent: str, page) -> Locator:
    sig = page_signature(page)
    if cached := self.locator_cache.get((intent, sig)):
        if await cached.is_visible():
            return cached
    fingerprint = await self.fingerprint(intent, page)
    candidates  = await self.llm.propose_locators(fingerprint)
    winner      = await self.validate(candidates, page)
    self.locator_cache.set((intent, sig), winner)
    return winner
```

---

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinated locators | Validate against live DOM; confidence threshold |
| Slow LLM calls | Three-layer cache ([§6](#6-caching-architecture)) |
| 8GB OOM | Tiered defaults, single-model mode, headless-only |
| Stale cached locators | Validate-on-use, page-signature invalidation |
| QA Agent false positives | Confidence threshold; bug drafts require human approve |
| LLM seeing PII / secrets | `@pii` tagging, regex stripping, secrets in keyring |
| Prompt injection from page | Sandboxed page text, instruction/data separation |
| **Stale Confluence specs** | **Recency/owner weighting, version snapshots, surfaced provenance** |
| **Atlassian rate limits** | **Local cache (1-day TTL); webhook-driven incremental sync** |
| **Sensitive Jira data → LLM** | **PII regex; per-project allowlist; redactable custom fields; audit log** |
| **Test generated from wrong spec** | **Traceability header lets reviewer verify source; humans approve generated tests before merge** |
| Vision verification flaky | DOM-first; vision tiebreaker only; skipped on 8GB |
| Framework regressions from prompt tweaks | Golden self-eval suite ([§5.8](#58-framework-self-evaluation)) gates CI |

---

## 15. Success Metrics

### Framework health
- **Cache hit rate** > 85% on warm lookups
- **Healing success rate** > 80%
- **Self-eval pass rate** > 95% on golden set
- **Cold→warm speedup** ≥ 10× on 10-step test

### QA Agent
- **Judgment accuracy** ≥ 85% vs labeled set
- **Investigation usefulness** ≥ 70% surveyed yes
- **False positive bug rate** < 5%

### Enterprise integration
- **Generated test usefulness** > 50% merged without edits
- **Requirements coverage** — % of acceptance criteria with automated tests, tracked per sprint
- **Spec staleness flag rate** — % of generated tests where source page is >90d old (lower is healthier)
- **Test-to-ticket traceability** — 100% of generated tests linked to source ticket

### Hardware
- **8GB feasibility** — full suite runs without OOM ✅

---

## 16. Roadmap

| Quarter | Milestone |
|---|---|
| Q1 | Phases 1–3: NL actions + self-healing + L1/L2 cache on Pytest |
| Q2 | Phases 4–6: KB + **Atlassian integration** + hybrid API/UI + **Jira-driven test gen** |
| Q3 | Phases 7–8: agent system + **QA Agent Mode with business-context judgment** |
| Q4 | Phases 9–10: a11y/perf/visual + productionization + OSS release |

---

## Getting Started *(once Phase 1 lands)*

```bash
git clone https://github.com/achaljoshi/ollama-playwright-automation.git
cd ollama-playwright-automation
poetry install
poetry run playwright install chromium
poetry run oapw doctor          # verify Ollama + models + browser + RAM
poetry run oapw atlassian login # one-time, stores token in keyring

poetry run pytest tests/examples
poetry run oapw cache stats

# After Phase 6:
poetry run oapw generate --from-jira PROJ-1234

# After Phase 8:
poetry run oapw qa "regression of login on qa"
```

---

*Last updated: living document — edit freely as the design evolves.*
