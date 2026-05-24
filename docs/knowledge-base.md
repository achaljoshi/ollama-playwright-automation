# Knowledge Base Guide

> Indexing Jira tickets, Confluence pages, and source code so the AI knows what your application does.

---

## Overview

The knowledge base is a ChromaDB vector store that gives the AI context about your application's **business logic, requirements, and implementation**. Without it, the AI generates generic tests. With it, the AI generates tests that match your actual acceptance criteria, field names, flows, and terminology.

```
Jira ticket "AUTH-42: Login with SSO"
   + Confluence page "SSO Authentication Design"
   + C# AuthController.cs
   + TypeScript LoginForm.tsx
   ──────────────────────────────────
   → AI knows: the login button triggers Azure AD flow,
     the redirect URL is /dashboard, the error modal says
     "Invalid credentials", the token is stored in localStorage
```

---

## Prerequisites

```bash
# Install ChromaDB (optional dep)
poetry install --extras knowledge

# Pull the embedding model
ollama pull nomic-embed-text

# Verify
oapw doctor
```

---

## Setup

### 1. Store Atlassian credentials

```bash
oapw auth atlassian --email you@company.com
# Enter your API token when prompted
```

Set environment variables (add to `.env`):

```env
OAPW_ATLASSIAN_EMAIL=you@company.com
OAPW_ATLASSIAN_URL=https://your-company.atlassian.net
```

### 2. Get your Atlassian API token

1. Visit https://id.atlassian.com/manage-profile/security/api-tokens
2. Create a new token
3. Run `oapw auth atlassian --email you@company.com` and paste it

---

## Syncing Jira

```bash
# Sync all stories in a project
oapw kb sync --jira "project = AUTH"

# Sync by sprint
oapw kb sync --jira "project = AUTH AND sprint in openSprints()"

# Sync specific issue types
oapw kb sync --jira "project = AUTH AND issuetype in (Story, Bug) AND status != Done"

# Increase the limit (default: 50)
oapw kb sync --jira "project = AUTH" --max 200
```

### What gets indexed per ticket

```
Jira Ticket: AUTH-42
Summary: Login with Azure AD SSO
Type: Story | Status: In Progress | Priority: High
Components: Authentication | Labels: sso, login

Description:
As a user I want to log in using my company Microsoft account
so that I don't need to manage a separate password.

Acceptance Criteria:
- Given I am on the login page
  When I click "Sign in with Microsoft"
  Then I am redirected to the Azure AD login page
- Given I complete Azure AD authentication
  When I am redirected back
  Then I see the dashboard and my name in the header
```

The text is structured to make semantic search highly effective.

---

## Syncing Confluence

```bash
# Sync pages by label
oapw kb sync --confluence "label = qa"

# Sync a specific space
oapw kb sync --confluence "space = BACKEND AND type = page"

# Sync with component weighting
# Pages whose author or labels match "Authentication" are ranked higher
oapw kb sync --confluence "label = qa AND space = ENG" --component "Authentication"

# Combine label and space filters
oapw kb sync --confluence "label = design AND label = qa AND space = PROD"
```

### Confluence page weighting

When `--component` is specified, pages are scored for relevance before ingestion:

```
score = 0.25                              (always)
      + 0.40 × recency_factor             (1.0 today, 0.0 after 90 days)
      + 0.35 × owner_factor               (1.0 if author/label matches component)
```

Higher-weighted pages appear first in search results.

---

## Combined sync

```bash
oapw kb sync \
  --jira "project = AUTH AND sprint in openSprints()" \
  --confluence "space = ENG AND label = qa" \
  --component "Authentication" \
  --max 100
```

---

## Checking the knowledge base

```bash
# Document count
oapw kb stats
# Knowledge base: 847 documents indexed

# Test coverage by Jira ticket
oapw kb coverage
```

---

## Using the knowledge base in tests

### Automatic context injection (planned)

When the QA Agent is invoked with a Jira ticket, it automatically retrieves relevant context:

```python
# Future usage — via QA Agent
await agent.run("Test the login flow for AUTH-42")
# Agent retrieves context for AUTH-42, Confluence pages, and related code
# before generating the test plan
```

### Manual RAG retrieval

```python
from oapw.knowledge.rag import RAGRetriever

retriever = RAGRetriever()

# Basic search
snippets = await retriever.retrieve("login button click", top_k=5)

# With Jira ticket linking (boosts relevant docs by 1.2×)
snippets = await retriever.retrieve(
    "SSO authentication redirect",
    linked_jira=["AUTH-42"],
    top_k=5,
    min_score=0.3,
)

# Filter by source
snippets = await retriever.retrieve(
    "error message validation",
    source_filter="jira",   # "jira" | "confluence" | "code"
)

# Format for LLM injection
context = retriever.format_context(snippets)
print(context)
# ### Login with Azure AD SSO [JIRA] (relevance: 0.87)
# Summary: Login with Azure AD SSO...
#
# ### SSO Authentication Design [CONFLUENCE] (relevance: 0.82)
# Azure AD is configured with...
```

### Traceability

Link your tests to Jira tickets so coverage reports work:

```python
from oapw.enterprise.traceability import TraceabilityStore
from oapw.core.config import get_config

store = TraceabilityStore(db_path=get_config().traceability_db)

# In a pytest fixture or at the start of a test
store.link_test(
    test_path="tests/e2e/test_sso_login.py::test_sso_redirect",
    jira_ids=["AUTH-42"],
    confluence_ids=["98765432"],  # Confluence page ID
)
```

Then `oapw kb coverage` shows which tickets are covered.

---

## Clearing the knowledge base

```bash
# Wipe everything (start fresh)
oapw kb clear --yes
```

You can also clear just one source type programmatically:

```python
from oapw.knowledge.vector_store import get_knowledge_store

store = get_knowledge_store()
# Clear all Jira documents
# (filter by metadata not yet implemented — use clear() + re-sync)
store.clear()
```

---

## Architecture notes

### Storage

ChromaDB stores data in `.oapw/` (or wherever `OAPW_DATA_DIR` points). The collection is named `oapw_knowledge` with cosine similarity (`hnsw:space: cosine`).

### Embeddings

All text is embedded using `nomic-embed-text` via Ollama. Embeddings are cached in L2 (SQLite, no TTL — embeddings never change for the same text + model). On a warm cache, re-syncing the same content costs zero embedding API calls.

### Deduplication

Documents are upserted by ID. For Jira: `jira:{key}`. For Confluence: `conf:{page_id}`. For code: `{repo}:{file_path}#{symbol_name}`. Re-syncing the same content overwrites without duplicating.

### Without ChromaDB

If ChromaDB is not installed (`poetry install` without `--extras knowledge`), `get_knowledge_store()` returns a `KnowledgeStore` that raises `RuntimeError` when used. The rest of the framework works normally. Install with `poetry install --extras knowledge` to enable.
