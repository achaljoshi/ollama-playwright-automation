# Configuration Reference

All settings are read by `OapwConfig` (pydantic-settings) in this priority order:

1. `OAPW_*` environment variables
2. `.env` file in the working directory
3. Field defaults listed below

---

## Complete Settings Reference

### Project

| Variable | Default | Description |
|---|---|---|
| `OAPW_PROJECT_NAME` | `default` | Project name used for cache namespacing |
| `OAPW_DATA_DIR` | `.oapw` | Root directory for all runtime data (cache, traces, DBs) |

### Ollama

| Variable | Default | Description |
|---|---|---|
| `OAPW_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OAPW_OLLAMA_DEFAULT_MODEL` | `qwen2.5:3b` | Default LLM used for planning, locator resolution, healing, generation |
| `OAPW_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model for knowledge base and L3 cache |
| `OAPW_OLLAMA_TIMEOUT` | `120` | HTTP timeout in seconds for all Ollama API calls |

### Browser

| Variable | Default | Description |
|---|---|---|
| `OAPW_BROWSER_TYPE` | `chromium` | Playwright browser engine (`chromium`, `firefox`, `webkit`) |
| `OAPW_BROWSER_HEADLESS` | `true` | Run browser headless (`true`/`false`) |
| `OAPW_BROWSER_SLOW_MO` | `0` | Slow-motion delay in milliseconds (useful for debugging, e.g. `100`) |
| `OAPW_BROWSER_VIEWPORT_WIDTH` | `1280` | Viewport width in pixels |
| `OAPW_BROWSER_VIEWPORT_HEIGHT` | `720` | Viewport height in pixels |
| `OAPW_BROWSER_TIMEOUT` | `30000` | Default element timeout in milliseconds |

### Cache

| Variable | Default | Description |
|---|---|---|
| `OAPW_CACHE_L1_MAX_SIZE` | `512` | Maximum number of entries in the L1 in-memory LRU cache |
| `OAPW_CACHE_L2_TTL_LLM` | `2592000` | LLM response cache TTL in seconds (default: 30 days) |
| `OAPW_CACHE_L2_TTL_LOCATOR` | `604800` | Locator cache TTL in seconds (default: 7 days) |
| `OAPW_CACHE_L2_TTL_PLAN` | `86400` | Plan cache TTL in seconds (default: 1 day) |

### Hardware

| Variable | Default | Description |
|---|---|---|
| `OAPW_RAM_GB` | `8` | Available RAM in GB — used by `oapw doctor` to validate hardware |

### Atlassian

| Variable | Default | Description |
|---|---|---|
| `OAPW_ATLASSIAN_URL` | `` | Atlassian Cloud base URL, e.g. `https://company.atlassian.net` |
| `OAPW_ATLASSIAN_EMAIL` | `` | Atlassian account email used for API authentication |

> **API token** — stored in the OS keyring (not an env var). Set it once with `oapw auth atlassian --email you@company.com`.

---

## Computed Properties

These are derived from the settings above and are read-only:

| Property | Value | Description |
|---|---|---|
| `cache_dir` | `{data_dir}/cache` | L2 SQLite cache location |
| `traces_dir` | `{data_dir}/traces` | Playwright trace files |
| `traceability_db` | `{data_dir}/traceability.db` | Test traceability SQLite database |

---

## Example `.env` Files

### Minimal (local dev, 8 GB machine)

```env
OAPW_PROJECT_NAME=my-app
```

### Development with visible browser

```env
OAPW_PROJECT_NAME=my-app
OAPW_BROWSER_HEADLESS=false
OAPW_BROWSER_SLOW_MO=100
OAPW_OLLAMA_DEFAULT_MODEL=qwen2.5:3b
```

### 16 GB machine with better models

```env
OAPW_PROJECT_NAME=my-app
OAPW_OLLAMA_DEFAULT_MODEL=qwen2.5:7b
OAPW_RAM_GB=16
OAPW_CACHE_L1_MAX_SIZE=1024
```

### With Atlassian integration

```env
OAPW_PROJECT_NAME=my-app
OAPW_ATLASSIAN_URL=https://company.atlassian.net
OAPW_ATLASSIAN_EMAIL=you@company.com
# API token stored separately: oapw auth atlassian --email you@company.com
```

### CI environment

```env
OAPW_PROJECT_NAME=my-app-ci
OAPW_DATA_DIR=/tmp/oapw-ci
OAPW_BROWSER_HEADLESS=true
OAPW_OLLAMA_TIMEOUT=60
OAPW_CACHE_L2_TTL_LLM=0
```

---

## Programmatic Access

```python
from oapw.core.config import get_config, reset_config

cfg = get_config()
print(cfg.ollama_default_model)  # "qwen2.5:3b"
print(cfg.cache_dir)             # Path(".oapw/cache")

# In tests — reset after monkeypatching
import os
os.environ["OAPW_OLLAMA_DEFAULT_MODEL"] = "qwen2.5:7b"
reset_config()
cfg = get_config()
assert cfg.ollama_default_model == "qwen2.5:7b"
```

---

## Data Directory Layout

```
.oapw/
├── cache/
│   └── cache.db          # L2 SQLite cache (WAL mode)
├── repos/
│   ├── backend-api/      # Cloned code repositories
│   └── frontend-app/
├── traces/               # Playwright trace files
├── traceability.db       # Test ↔ Jira ↔ Confluence links
└── healing.db            # Self-healing event log
```

All paths are configurable via `OAPW_DATA_DIR`.
