# CLI Reference

Complete reference for all `oapw` commands.

---

## Global Options

```
oapw [OPTIONS] COMMAND [ARGS]...
```

| Option | Description |
|---|---|
| `--help` | Show help and exit |
| `--version` | Show version and exit (same as `oapw version`) |

---

## `oapw doctor`

Verify that all runtime dependencies are installed and reachable.

```bash
oapw doctor
```

**Checks performed:**

| Check | Pass condition |
|---|---|
| Python ≥ 3.11 | Interpreter version |
| Ollama server | `GET /api/tags` responds 200 |
| Model: qwen2.5:3b | Listed in `ollama list` |
| Model: nomic-embed-text | Listed in `ollama list` |
| Playwright chromium | `sync_playwright().start()` succeeds |
| RAM ≥ 8 GB | `sysctl hw.memsize` (macOS) or `/proc/meminfo` (Linux) |
| Cache dir writable | `OapwConfig.ensure_dirs()` succeeds |

**Exit codes:** `0` all checks pass, `1` one or more checks failed.

**Example output:**

```
╭──────────────────────── oapw doctor ────────────────────────╮
│ Check                    Status  Detail                      │
│ Python ≥ 3.11              ✓    3.12.4                      │
│ Ollama server              ✓    http://localhost:11434       │
│ Model: qwen2.5:3b          ✓    pulled                      │
│ Model: nomic-embed-text    ✓    pulled                      │
│ Playwright chromium        ✓    installed                   │
│ RAM ≥ 8 GB                 ✓    16 GB detected              │
│ Cache dir writable         ✓    .oapw/cache                 │
╰─────────────────────────────────────────────────────────────╯
✓ All checks passed — oapw v0.1.0 ready!
```

---

## `oapw version`

Print the framework version.

```bash
oapw version
```

```
oapw 0.1.0
```

---

## `oapw cache`

Cache management commands.

### `oapw cache stats`

Show L1 memory and L2 disk cache statistics.

```bash
oapw cache stats
```

```
╭──────────────── Cache Statistics ────────────────╮
│ Layer               Hits  Misses  Size            │
│ L1 Memory (LRU)      142      58  87 / 512       │
│ L2 Disk (SQLite)    1204     312  2847 rows       │
╰──────────────────────────────────────────────────╯
```

### `oapw cache prune`

Remove expired entries from the L2 SQLite cache. Runs fast — O(n) scan, deletes in bulk.

```bash
oapw cache prune
```

```
Pruned 43 expired entries.
```

### `oapw cache clear`

Wipe **all** cached data (L1 + L2). Prompts for confirmation.

```bash
oapw cache clear
```

```
This will delete all cached LLM responses, locators, and plans. Continue? [y/N]:
```

```bash
# Skip confirmation
oapw cache clear --yes
oapw cache clear -y
```

---

## `oapw kb`

Knowledge base commands (Jira + Confluence + code repos).

### `oapw kb sync`

Sync Jira tickets, Confluence pages, and/or code repositories into the knowledge base.

```bash
oapw kb sync [OPTIONS]
```

**At least one source flag is required.**

| Option | Type | Default | Description |
|---|---|---|---|
| `--jira` | str | — | JQL query for Jira tickets |
| `--confluence` | str | — | CQL query for Confluence pages |
| `--repo` | str (repeatable) | — | Git repository clone URL |
| `--component` | str | — | Jira component name for Confluence relevance weighting |
| `--branch` | str | `main` | Git branch to sync for `--repo` |
| `--username` | str | — | Bitbucket username (credential loaded from OS keyring) |
| `--max` | int | `50` | Maximum items per Jira/Confluence query |

**Examples:**

```bash
# Sync Jira user stories
oapw kb sync --jira "project = AUTH AND issuetype = Story"

# Sync Confluence docs
oapw kb sync --confluence "label = qa AND space = BACKEND"

# Sync both with component weighting
oapw kb sync \
  --jira "project = AUTH" \
  --confluence "space = BACKEND" \
  --component "Authentication"

# Sync code repos
oapw kb sync \
  --repo https://bitbucket.org/workspace/backend-api \
  --repo https://bitbucket.org/workspace/frontend-app \
  --branch develop \
  --username your-bitbucket-username

# Sync everything at once
oapw kb sync \
  --jira "project = AUTH AND sprint in openSprints()" \
  --confluence "label = qa AND space = ENG" \
  --repo https://bitbucket.org/workspace/backend \
  --repo https://bitbucket.org/workspace/frontend \
  --component "Authentication" \
  --username your-bitbucket-user \
  --max 100
```

**Output:**

```
Ingesting Jira: project = AUTH AND issuetype = Story
  ✓ 42/50 tickets ingested
Ingesting Confluence: label = qa AND space = BACKEND
  ✓ 18/20 pages ingested
Syncing 2 code repo(s):
  ✓ backend-api: 312 files, 1847 chunks, sha a3f5c2d1
  ✓ frontend-app: 128 files, 642 chunks, sha 9b4e1f20
```

### `oapw kb stats`

Show the total number of documents indexed in the knowledge base.

```bash
oapw kb stats
```

```
Knowledge base: 2531 documents indexed
```

### `oapw kb clear`

Remove **all** documents from the knowledge base (ChromaDB). Prompts for confirmation.

```bash
oapw kb clear
```

```bash
# Skip confirmation
oapw kb clear --yes
oapw kb clear -y
```

### `oapw kb coverage`

Show which Jira tickets have traced automated tests.

```bash
oapw kb coverage
```

```
╭──────────── Test Coverage Summary ────────────────╮
│ Metric                           Value             │
│ Tests with traceability            14              │
│ Jira tickets covered               8               │
│ Ticket keys         AUTH-42, AUTH-55, AUTH-61 ...  │
╰───────────────────────────────────────────────────╯
```

---

## `oapw auth`

Credential management. Stores credentials in the OS keyring (Keychain on macOS, Secret Service on Linux, Credential Manager on Windows).

### `oapw auth atlassian`

Store your Atlassian API token for Jira and Confluence access.

```bash
oapw auth atlassian --email EMAIL [--token TOKEN]
```

| Option | Short | Required | Description |
|---|---|---|---|
| `--email` | `-e` | Yes | Atlassian account email |
| `--token` | `-t` | No | API token (prompted securely if omitted) |

**Example:**

```bash
oapw auth atlassian --email you@company.com
# Atlassian API token: [hidden input]
# ✓ Token saved for you@company.com. Set OAPW_ATLASSIAN_EMAIL=you@company.com in your env.
```

**Getting an Atlassian API token:**
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Copy the token and paste it when prompted

After storing the token, set your email in `.env`:
```env
OAPW_ATLASSIAN_EMAIL=you@company.com
OAPW_ATLASSIAN_URL=https://your-company.atlassian.net
```

### `oapw auth bitbucket`

Store your Bitbucket App Password for code repository access.

```bash
oapw auth bitbucket --username USERNAME [--password PASSWORD]
```

| Option | Short | Required | Description |
|---|---|---|---|
| `--username` | `-u` | Yes | Bitbucket username |
| `--password` | `-p` | No | App Password (prompted securely if omitted) |

**Example:**

```bash
oapw auth bitbucket --username your-bb-username
# Bitbucket App Password: [hidden input]
# ✓ Credential saved for your-bb-username. Use --username your-bb-username with oapw kb sync --repo.
```

**Getting a Bitbucket App Password:**
1. Go to Bitbucket → Personal Settings → App Passwords
2. Click **Create app password**
3. Grant permissions: **Repositories: Read**
4. Copy the generated password and paste it when prompted

---

## Shell Completion

Enable tab completion for your shell:

```bash
# bash
oapw --install-completion bash

# zsh
oapw --install-completion zsh

# fish
oapw --install-completion fish
```

---

## Using oapw in CI

```yaml
# .github/workflows/test.yml (example)
- name: Sync knowledge base
  env:
    OAPW_ATLASSIAN_EMAIL: ${{ secrets.ATLASSIAN_EMAIL }}
    OAPW_ATLASSIAN_URL: ${{ secrets.ATLASSIAN_URL }}
  run: |
    echo "${{ secrets.ATLASSIAN_TOKEN }}" | \
      poetry run oapw auth atlassian --email $OAPW_ATLASSIAN_EMAIL --token -
    poetry run oapw kb sync --jira "project = AUTH AND sprint in openSprints()"

- name: Run tests
  run: poetry run pytest tests/
```
