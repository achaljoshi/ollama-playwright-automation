# Development Guide

> Contributing to oapw, running tests, adding new capabilities.

---

## Table of Contents

- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Project Conventions](#project-conventions)
- [Adding a New Agent](#adding-a-new-agent)
- [Adding a New Prompt Template](#adding-a-new-prompt-template)
- [Adding a New CLI Command](#adding-a-new-cli-command)
- [Documentation Policy](#documentation-policy)
- [Architecture Decision Records](#architecture-decision-records)

---

## Development Setup

```bash
# Clone and install all dev dependencies
git clone https://github.com/your-org/oapw
cd oapw
poetry install --extras knowledge

# Install Playwright browsers
poetry run playwright install chromium

# Pull Ollama models
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# Verify
poetry run oapw doctor
```

---

## Running Tests

### Unit tests (fast — all mocked, no external dependencies)

```bash
poetry run pytest tests/unit/ -v
```

Expected: **200 tests, ~4 seconds**.

### Eval suite (real Playwright, local HTTP server)

```bash
poetry run pytest tests/eval/ -v
```

Expected: **14 tests, ~8 seconds**. Requires Playwright chromium installed.

### Full suite

```bash
poetry run pytest tests/ -v
```

### With coverage

```bash
poetry run pytest tests/unit/ --cov=src/oapw --cov-report=html --cov-report=term-missing
open htmlcov/index.html
```

### Linting and type checking

```bash
poetry run ruff check src/ tests/         # fast linter
poetry run ruff format src/ tests/        # auto-format
poetry run mypy src/                      # type check
```

---

## Code Style

### Python style

- **ruff** for linting (`ruff check`) and formatting (`ruff format`)
- Line length: 100 characters
- Target: Python 3.11+ (`from __future__ import annotations` in every file)
- Enabled rules: `E`, `F`, `I` (isort), `UP` (pyupgrade), `B` (bugbear)
- Ignored: `E501` (line length — handled by formatter)

### Module docstring format

Every module starts with a docstring explaining:
1. What the module does (one line)
2. Key design decisions or constraints
3. Usage example (for public APIs)

```python
"""CacheManager — unified L1→L2 read-through / write-through interface.

Read order: L1 (memory) → L2 (SQLite).
Write order: L1 + L2 simultaneously.

Callers work with named buckets so TTL policy is centralised here.
"""
```

### Dataclasses vs Pydantic

- **Pydantic models** for data that crosses API boundaries (LLM output, config)
- **`@dataclass`** for internal data structures (fingerprints, cache entries, chunks)

### Async conventions

- All I/O-bound operations (Playwright, Ollama, ChromaDB, git) are `async`
- CPU-bound operations (regex parsing, fingerprint scoring) are synchronous
- Use `asyncio.run()` only at the CLI entry point, never inside library code

---

## Project Conventions

### Singleton pattern

Module-level singletons follow this pattern, used consistently across `config`, `cache`, `ollama_client`, `knowledge`:

```python
_instance: MyClass | None = None

def get_instance() -> MyClass:
    global _instance
    if _instance is None:
        _instance = MyClass()
    return _instance

def reset_instance() -> None:
    """Force re-create on next access — for tests."""
    global _instance
    _instance = None
```

Always expose `reset_*()` for test isolation.

### Cache key format

```python
# bucket:hash_or_id
"llm:a3f5c2d19b4e1f20"        # LLM response
"locator:9b4e1f20a3f5c2d1"    # Locator
"embed:nomic-embed-text:c2d1"  # Embedding
"jira:AUTH-42"                  # Jira ticket
"conf:12345678"                 # Confluence page
"code:last_sha:backend-api"    # Last indexed git SHA
```

### Test isolation

Unit tests that touch `CacheManager`, `OapwConfig`, or `get_knowledge_store()` must reset singletons after each test:

```python
@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("OAPW_DATA_DIR", str(tmp_path))
    reset_config()
    reset_cache()
    yield
    reset_cache()
    reset_config()
```

### Lazy imports for optional dependencies

ChromaDB is optional. Always guard its import:

```python
def _get_client(self):
    try:
        import chromadb
    except ImportError as e:
        raise RuntimeError(
            "chromadb is not installed. Run: poetry install --extras knowledge"
        ) from e
    return chromadb.PersistentClient(path=str(self._data_dir))
```

---

## Adding a New Agent

1. **Create the agent file** in `src/oapw/agents/`:

```python
# src/oapw/agents/my_agent.py
"""MyAgent — does X.

Usage:
  agent = MyAgent()
  result = await agent.run(input)
"""
from __future__ import annotations
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.ollama_client import get_ollama_client
import oapw.prompts as prompts


class MyAgent:
    def __init__(self, ollama=None, model=None):
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()

    async def run(self, input: str) -> str:
        # 1. Check cache
        key = _cache_key(input)
        cached = self._cache.get_llm(key)
        if cached:
            return cached

        # 2. Build prompt from template
        prompt = prompts.render("my_agent.j2", input=input)

        # 3. Call LLM
        result = await self._ollama.generate(prompt, model=self._model)

        # 4. Cache and return
        self._cache.set_llm(key, result)
        return result
```

2. **Create the Jinja2 prompt template** in `src/oapw/prompts/my_agent.j2`

3. **Add unit tests** in `tests/unit/test_my_agent.py`

4. **Export from `__init__.py`** if it's a public API

5. **Update `CHANGELOG.md`** under `[Unreleased] → Added`

---

## Adding a New Prompt Template

Templates live in `src/oapw/prompts/` and use Jinja2 syntax.

```jinja2
{# src/oapw/prompts/my_agent.j2 #}
You are a QA engineer analyzing a web application.

Input: {{ input }}

Respond with a JSON object:
{
  "result": "...",
  "confidence": 0.0-1.0
}
```

Render in Python:

```python
import oapw.prompts as prompts
rendered = prompts.render("my_agent.j2", input="some text", extra_var="value")
```

Test the template:

```python
def test_my_agent_prompt_contains_input():
    rendered = prompts.render("my_agent.j2", input="login button")
    assert "login button" in rendered
```

---

## Adding a New CLI Command

Commands live in `src/oapw/cli/main.py`. Follow the existing patterns:

### Add to the root app

```python
@app.command()
def my_command(
    option: str = typer.Option(..., "--option", "-o", help="Description"),
    flag: bool = typer.Option(False, "--flag", help="Enable something"),
) -> None:
    """One-line description shown in help."""
    # Use asyncio.run() for async work
    asyncio.run(_my_command(option, flag))


async def _my_command(option: str, flag: bool) -> None:
    from oapw.some.module import SomeClass
    result = await SomeClass().do_thing(option)
    console.print(f"[green]Done:[/] {result}")
```

### Add to a sub-app

```python
@kb_app.command("my-subcommand")
def kb_my_subcommand(...) -> None:
    """Description."""
    ...
```

### Update documentation

After adding a command, update:
- `docs/cli-reference.md` — add the command with all options and examples
- `CHANGELOG.md` — add to `[Unreleased] → Added`

---

## Documentation Policy

**Every code change must include documentation updates.**

### When to update what

| Change | Documents to update |
|---|---|
| New feature or module | `CHANGELOG.md` + relevant `docs/*.md` + `README.md` if user-facing |
| Bug fix | `CHANGELOG.md` under Fixed |
| New CLI command | `docs/cli-reference.md` + `CHANGELOG.md` |
| New config option | `docs/configuration.md` + `CHANGELOG.md` |
| Architecture change | `docs/architecture.md` + `CHANGELOG.md` |
| New language parser | `docs/code-ingestion.md` + `CHANGELOG.md` |
| Healing strategy change | `docs/self-healing.md` + `CHANGELOG.md` |

### CHANGELOG format

```markdown
## [Unreleased]

### Added
- **`module/file.py`** — Brief description of what was added

### Changed
- **`module/file.py`** — What changed and why

### Fixed
- **`module/file.py`** — What was broken and how it was fixed

### Removed
- Description of what was removed
```

### Module docstrings

Every `.py` file must have a module-level docstring:
- First line: what the module does
- Key design constraints or decisions
- Usage example (for public APIs and agents)

---

## Architecture Decision Records

Key decisions that drove the design:

| Decision | Rationale |
|---|---|
| Ollama over cloud LLMs | Privacy + zero cost + offline capability |
| ChromaDB as optional dep | 500 MB add; not every project needs semantic search |
| SQLite for L2 cache | Zero infrastructure, WAL concurrent reads, survives restarts |
| Sequential code repo sync | Prevents OOM on 8 GB minimum hardware |
| blake2b for cache keys | 3× faster than sha256; no collision risk at this scale |
| Jaccard for fingerprint matching | O(1) per pair; no LLM needed; good enough for semantic element matching |
| L3 semantic cache threshold 0.92 | Tuned empirically; higher = more cache misses, lower = wrong cached responses |
| `from __future__ import annotations` everywhere | Enables `X \| Y` union syntax on Python 3.11 |

When making a new design decision that affects the architecture, add it to `docs/architecture.md` under **Key Design Decisions**.
