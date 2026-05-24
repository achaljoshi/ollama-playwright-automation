# Local Setup Guide

> Step-by-step guide to install oapw on your machine, run your first AI-powered test, and build a Knowledge Base from your Jira, Confluence, and source code.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Install Python & Poetry](#install-python--poetry)
3. [Install Ollama & Pull Models](#install-ollama--pull-models)
4. [Install oapw](#install-oapw)
5. [Configure Your Environment](#configure-your-environment)
6. [Verify with `oapw doctor`](#verify-with-oapw-doctor)
7. [Scaffold a New Project](#scaffold-a-new-project)
8. [Write Your First Test](#write-your-first-test)
9. [Building the Knowledge Base](#building-the-knowledge-base)
   - [Step 1 — Install ChromaDB](#step-1--install-chromadb)
   - [Step 2 — Store Your Atlassian Token](#step-2--store-your-atlassian-token)
   - [Step 3 — Sync Jira Tickets](#step-3--sync-jira-tickets)
   - [Step 4 — Sync Confluence Pages](#step-4--sync-confluence-pages)
   - [Step 5 — Sync Code Repositories](#step-5--sync-code-repositories)
   - [Step 6 — Verify the KB](#step-6--verify-the-kb)
10. [Using the Knowledge Base](#using-the-knowledge-base)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| **Operating system** | macOS 12+ / Ubuntu 22.04+ / Windows 11 (WSL2) | Native Linux or macOS recommended |
| **Python** | 3.11 | 3.12 recommended |
| **RAM** | 8 GB | 16 GB for larger models (qwen2.5:7b) |
| **Disk space** | 6 GB free | ~5 GB for Ollama models, ~1 GB for dependencies |
| **Internet** | Required for first setup | Fully offline after initial model pulls |

---

## Install Python & Poetry

### macOS

```bash
# Install Homebrew (skip if already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12
brew install python@3.12

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Verify
python3 --version    # Python 3.12.x
poetry --version     # Poetry 1.8.x
```

### Ubuntu / Debian

```bash
# Install Python 3.12
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip

# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Add Poetry to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Windows (WSL2)

Run all commands inside a WSL2 terminal (Ubuntu 22.04 recommended). Follow the Ubuntu steps above.

---

## Install Ollama & Pull Models

Ollama runs all LLM inference locally. It must be running before you use oapw.

### macOS

```bash
brew install ollama
```

### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Start the Ollama server

```bash
ollama serve
```

> Keep this terminal open, or run it as a background service. On macOS, the Ollama app also starts the server automatically.

### Pull the required models

```bash
# 8 GB machine — small model, fast responses
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# 16 GB machine — larger model, better quality
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

> `nomic-embed-text` is required for the Knowledge Base. `qwen2.5:3b` (or `:7b`) is the default LLM for test generation, planning, and healing.

### Recommended Ollama environment settings

Add these to your shell profile (`~/.zshrc` or `~/.bashrc`) to prevent models from being unloaded between test runs:

```bash
export OLLAMA_KEEP_ALIVE=5m
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
```

---

## Install oapw

### Clone the repository

```bash
git clone https://github.com/your-org/ollama-playwright-automation.git
cd ollama-playwright-automation
```

### Install dependencies

```bash
# Minimal install (no ChromaDB — KB features disabled)
poetry install

# With knowledge base support (recommended)
poetry install --extras knowledge

# With everything (KB + Allure reports + visual regression)
poetry install --extras full
```

### Install Playwright browsers

```bash
poetry run playwright install chromium
```

> Only Chromium is needed. Firefox and WebKit are optional — install them with `playwright install` (no `chromium` argument) if required.

---

## Configure Your Environment

Create a `.env` file in the project root:

```bash
cp .env.example .env   # if oapw init was run, this already exists
```

Then edit `.env` with your values:

```env
# ── Application under test ────────────────────────────────────────────────────
OAPW_APP_BASE_URL=http://localhost:3000          # URL of your app

# ── Ollama ────────────────────────────────────────────────────────────────────
OAPW_OLLAMA_BASE_URL=http://localhost:11434      # default
OAPW_OLLAMA_DEFAULT_MODEL=qwen2.5:3b             # or qwen2.5:7b on 16 GB

# ── Browser ───────────────────────────────────────────────────────────────────
OAPW_BROWSER_HEADLESS=true                       # false to watch the browser
OAPW_BROWSER_SLOW_MO=0                           # ms delay (set to 100 for debugging)

# ── Atlassian (optional — only needed for KB sync) ────────────────────────────
OAPW_ATLASSIAN_URL=https://your-company.atlassian.net
OAPW_ATLASSIAN_EMAIL=you@company.com
```

> The Atlassian **API token** is stored in the OS keyring (not in `.env`). See [Step 2 — Store Your Atlassian Token](#step-2--store-your-atlassian-token).

---

## Verify with `oapw doctor`

```bash
poetry run oapw doctor
```

Expected output when everything is working:

```
╭──────────────────────────────── oapw doctor ─────────────────────────────────╮
│ Check                    Status  Detail                                       │
│ Python ≥ 3.11              ✓    3.12.4                                       │
│ Ollama server              ✓    http://localhost:11434                        │
│ Model: qwen2.5:3b          ✓    pulled                                       │
│ Model: nomic-embed-text    ✓    pulled                                       │
│ Playwright chromium        ✓    installed                                    │
│ RAM ≥ 8 GB                 ✓    16 GB detected                               │
│ Cache dir writable         ✓    .oapw/cache                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
✓ All checks passed — oapw v0.1.0 ready!
```

If any check fails, see [Troubleshooting](#troubleshooting).

---

## Scaffold a New Project

If you're starting a new test project (rather than running the oapw repo's own tests), use `oapw init` to create the boilerplate:

```bash
mkdir my-qa-tests && cd my-qa-tests
poetry init --no-interaction
poetry add oapw --extras knowledge
poetry run oapw init
```

This creates:

```
my-qa-tests/
├── conftest.py              ← base_url + auth_page fixtures
├── .env.example             ← copy to .env and fill in your values
├── tests/
│   ├── __init__.py
│   └── test_example.py      ← first runnable test
```

```bash
cp .env.example .env
# Edit .env: set OAPW_APP_BASE_URL to your app's URL

poetry run pytest tests/ -v
```

---

## Write Your First Test

All oapw fixtures are available automatically — no imports needed in your test file.

### Minimal test

```python
# tests/test_login.py
import pytest

pytestmark = pytest.mark.asyncio

async def test_login_page_loads(oapw_page):
    await oapw_page.goto("http://localhost:3000/login")
    await oapw_page.ai_assert("The login page is visible with email and password fields")
```

```bash
poetry run pytest tests/test_login.py -v
```

### With AI interactions and assertions

```python
async def test_login_happy_path(oapw_page, oapw_factory):
    creds = oapw_factory.build("credentials")

    await oapw_page.goto("http://localhost:3000/login")
    await oapw_page.ai(f"Fill the email input with '{creds.email}'")
    await oapw_page.ai(f"Fill the password input with '{creds.password}'")
    await oapw_page.ai("Click the Sign In button")
    await oapw_page.ai_assert("I am on the dashboard after logging in")
```

### With accessibility and performance checks

```python
async def test_login_full(oapw_page, oapw_factory, oapw_accessibility, oapw_performance):
    await oapw_page.goto("http://localhost:3000/login")

    # Accessibility — no WCAG critical violations
    report = await oapw_accessibility.check(oapw_page.page)
    report.assert_no_critical()

    # Performance — page loads fast enough
    metrics = await oapw_performance.capture(oapw_page.page)
    metrics.assert_ttfb_under(1000)   # Time to First Byte < 1s
    metrics.assert_fcp_under(2000)    # First Contentful Paint < 2s
```

### Run only unit tests (no live browser needed)

```bash
# From the oapw repo itself
poetry run pytest tests/unit/ tests/eval/ -q
```

---

## Building the Knowledge Base

The Knowledge Base (KB) is a vector store that gives the AI context about your application — acceptance criteria from Jira, design decisions from Confluence, and implementation details from your source code. It makes generated tests match your actual app instead of producing generic assertions.

```
Without KB → "Fill the email input and click submit"
With KB    → "Fill 'johndoe@company.com', click 'Sign in with Microsoft',
              wait for Azure AD redirect, verify dashboard header shows user name"
```

---

### Step 1 — Install ChromaDB

ChromaDB is the vector store that powers the KB. It's an optional dependency:

```bash
# If not already installed
poetry install --extras knowledge

# Verify ChromaDB is available
poetry run python -c "import chromadb; print('ChromaDB OK')"
```

---

### Step 2 — Store Your Atlassian Token

> Skip this step if you're only syncing code repositories (Bitbucket/Git), not Jira or Confluence.

**Get your Atlassian API token:**

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Give it a name (e.g. `oapw-local`)
4. Copy the generated token

**Store it in your OS keyring:**

```bash
poetry run oapw auth atlassian --email you@company.com
# Atlassian API token: [paste token here — input is hidden]
# ✓ Token saved for you@company.com
```

**Add your Atlassian URL to `.env`:**

```env
OAPW_ATLASSIAN_URL=https://your-company.atlassian.net
OAPW_ATLASSIAN_EMAIL=you@company.com
```

---

### Step 3 — Sync Jira Tickets

Sync the Jira tickets most relevant to what you're testing. Use JQL to target specific projects, sprints, or issue types.

```bash
# Sync all stories in a project (up to 50)
poetry run oapw kb sync --jira "project = AUTH"

# Sync the current sprint only
poetry run oapw kb sync --jira "project = AUTH AND sprint in openSprints()"

# Sync all open bugs and stories (up to 200 tickets)
poetry run oapw kb sync \
  --jira "project = AUTH AND issuetype in (Story, Bug) AND status != Done" \
  --max 200
```

**What gets indexed per ticket:**
- Summary, description, acceptance criteria
- Type, status, priority, components, labels
- All structured as searchable text

**Example output:**
```
Ingesting Jira: project = AUTH AND sprint in openSprints()
  ✓ 34/50 tickets ingested (34 added, 0 errors)
```

---

### Step 4 — Sync Confluence Pages

Sync design docs, test plans, and architecture pages that describe how your app works.

```bash
# Sync all pages with the "qa" label
poetry run oapw kb sync --confluence "label = qa"

# Sync a specific space
poetry run oapw kb sync --confluence "space = BACKEND AND type = page"

# Sync with component weighting
# Pages whose author or label matches "Authentication" are ranked higher in search
poetry run oapw kb sync \
  --confluence "space = ENG AND label = qa" \
  --component "Authentication"
```

**Tip — combine Jira and Confluence in one command:**

```bash
poetry run oapw kb sync \
  --jira "project = AUTH AND sprint in openSprints()" \
  --confluence "space = ENG AND label = qa" \
  --component "Authentication" \
  --max 100
```

---

### Step 5 — Sync Code Repositories

Index your source code so the AI understands component names, API endpoints, field names, and implementation details.

**Store Bitbucket credentials (if using Bitbucket):**

```bash
poetry run oapw auth bitbucket --username your-bb-username
# Bitbucket App Password: [paste here — input is hidden]
```

> Get a Bitbucket App Password: Bitbucket → Personal Settings → App Passwords → create with **Repositories: Read** permission.

**Sync one or more repos:**

```bash
# Single repo (public or HTTPS)
poetry run oapw kb sync \
  --repo https://github.com/your-org/your-app \
  --branch main

# Multiple repos with Bitbucket auth
poetry run oapw kb sync \
  --repo https://bitbucket.org/workspace/backend-api \
  --repo https://bitbucket.org/workspace/frontend-app \
  --branch develop \
  --username your-bitbucket-username

# Full sync: Jira + Confluence + code
poetry run oapw kb sync \
  --jira "project = AUTH AND sprint in openSprints()" \
  --confluence "space = ENG AND label = qa" \
  --repo https://bitbucket.org/workspace/backend-api \
  --repo https://bitbucket.org/workspace/frontend-app \
  --component "Authentication" \
  --username your-bb-username \
  --max 100
```

**What gets indexed per repo:**
- C# files: namespaces, classes, methods (with XML doc comments)
- TypeScript/React files: components, hooks, exported functions, API routes
- All other files: sliding-window chunks (80 lines, 20-line overlap)

**Example output:**
```
Syncing 2 code repo(s):
  ✓ backend-api: 312 files, 1847 chunks, sha a3f5c2d1
  ✓ frontend-app: 128 files, 642 chunks, sha 9b4e1f20
```

Subsequent syncs are **incremental** — only files changed since the last sync are re-indexed.

---

### Step 6 — Verify the KB

```bash
# Check document count
poetry run oapw kb stats
# Knowledge base: 2531 documents indexed

# Check test-to-ticket coverage
poetry run oapw kb coverage
```

---

## Using the Knowledge Base

### Generate a test from a Jira ticket

```bash
poetry run oapw generate from-jira AUTH-42 --out tests/e2e/
```

The generator automatically retrieves the ticket's acceptance criteria + related Confluence pages + code snippets from the KB and injects them into the LLM prompt. Generated tests are significantly more specific than without KB context.

### Run the QA Agent

```bash
# Run a natural-language regression goal
poetry run oapw qa "regression of the login flow on QA" --top-k 10
```

The agent: parses the goal → selects relevant tests from the KB → executes them → judges failures with LLM + KB context → optionally drafts a Jira bug report.

### Query the KB directly (Python)

```python
from oapw.knowledge.rag import RAGRetriever

retriever = RAGRetriever()

# Free-text search
snippets = await retriever.retrieve("login button click", top_k=5)

# Boosted by Jira ticket (1.2× score for linked docs)
snippets = await retriever.retrieve(
    "SSO authentication redirect",
    linked_jira=["AUTH-42"],
    top_k=5,
)

# Print formatted context for inspection
print(retriever.format_context(snippets))
```

### Re-sync on a schedule

For a team environment, add a daily KB sync to CI:

```yaml
# .github/workflows/kb-sync.yml
on:
  schedule:
    - cron: '0 6 * * *'   # 6 AM daily

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install poetry && poetry install --extras knowledge
      - run: |
          poetry run oapw auth atlassian \
            --email ${{ secrets.ATLASSIAN_EMAIL }} \
            --token ${{ secrets.ATLASSIAN_TOKEN }}
          poetry run oapw kb sync \
            --jira "project = AUTH AND sprint in openSprints()" \
            --confluence "space = ENG AND label = qa" \
            --max 200
        env:
          OAPW_ATLASSIAN_URL: ${{ secrets.ATLASSIAN_URL }}
          OAPW_ATLASSIAN_EMAIL: ${{ secrets.ATLASSIAN_EMAIL }}
```

---

## Troubleshooting

### `oapw doctor` fails — Ollama server not reachable

```
✗ Ollama server    http://localhost:11434 — connection refused
```

**Fix:** Ollama is not running. Start it:

```bash
ollama serve
```

If you see `address already in use`, Ollama is already running — restart it:

```bash
pkill ollama
ollama serve
```

---

### `oapw doctor` fails — model not pulled

```
✗ Model: qwen2.5:3b   not found
```

**Fix:** Pull the model:

```bash
ollama pull qwen2.5:3b
```

---

### `oapw doctor` fails — RAM check

```
✗ RAM ≥ 8 GB   4 GB detected
```

**Fix:** Override the RAM check with the actual value in `.env`:

```env
OAPW_RAM_GB=8
```

> This just changes what `oapw doctor` reports. Running large models on less than 8 GB will be slow.

---

### Playwright browser not found

```
Error: Executable doesn't exist at ...
```

**Fix:**

```bash
poetry run playwright install chromium
```

---

### ChromaDB not installed

```
RuntimeError: chromadb is not installed. Run: poetry install --extras knowledge
```

**Fix:**

```bash
poetry install --extras knowledge
```

---

### Atlassian token not found (KB sync fails)

```
KeyringError: No stored token for you@company.com
```

**Fix:** Store the token again:

```bash
poetry run oapw auth atlassian --email you@company.com
```

Then verify `.env` has:

```env
OAPW_ATLASSIAN_EMAIL=you@company.com
OAPW_ATLASSIAN_URL=https://your-company.atlassian.net
```

---

### Tests run slowly / LLM timeouts

The default timeout is 120 seconds. On slower machines with large models:

```env
OAPW_OLLAMA_TIMEOUT=180
```

Or switch to the smaller model:

```env
OAPW_OLLAMA_DEFAULT_MODEL=qwen2.5:3b
```

---

### Cache is stale after app changes

If tests generate wrong actions due to a cached plan:

```bash
# Wipe all cached LLM responses, plans, and locators
poetry run oapw cache clear --yes
```

---

## Next Steps

| Task | Command / Link |
|---|---|
| Run the full test suite | `poetry run pytest tests/unit/ tests/eval/ -q` |
| Run a single AI-powered test | `poetry run pytest tests/test_login.py -v` |
| Generate a test from a Jira ticket | `poetry run oapw generate from-jira AUTH-42` |
| Run an autonomous regression | `poetry run oapw qa "regression of login on QA"` |
| Watch the browser during debugging | Set `OAPW_BROWSER_HEADLESS=false` in `.env` |
| Full CLI reference | [docs/cli-reference.md](cli-reference.md) |
| Configuration reference | [docs/configuration.md](configuration.md) |
| Knowledge base deep-dive | [docs/knowledge-base.md](knowledge-base.md) |
| Self-healing locators | [docs/self-healing.md](self-healing.md) |
| Architecture overview | [docs/architecture.md](architecture.md) |
