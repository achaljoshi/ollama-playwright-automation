# Self-Healing Locators

> How oapw automatically recovers when UI changes break a locator.

---

## The Problem

UI automation tests are fragile. When a developer renames a button, changes a CSS class, or moves a form field, tests break. Fixing them is manual, tedious, and continuous.

oapw solves this with a **self-healing pipeline** that:

1. Stores a semantic *fingerprint* of every element when it is first resolved
2. Detects when a cached locator no longer points to a visible element
3. Searches the live DOM for the element using progressively more expensive strategies
4. Re-caches the winner so future runs are instant again

Your test code **never changes**.

---

## The Four-Tier Resolution Pipeline

Every call to `resolver.resolve("Sign in button")` passes through these tiers in order:

### Tier 1 — Cache Hit (microseconds)

```
cache.get_locator(hash(intent + page_signature))
   → locator.is_visible() == True
   → return immediately
```

If the locator is cached and the element is visible, we're done. This is the common case after the first run.

### Tier 2 — Stale Cache → Heal (milliseconds to seconds)

```
cache.get_locator(key)
   → locator.is_visible() == False  (element moved/renamed)
   → Healer.heal(intent, page, stored_fingerprint)
```

The healer tries three strategies in order:

**2a. FingerprintStrategy** (milliseconds, no LLM)
- Extracts all interactive elements from the live DOM
- Compares each against the stored `ElementFingerprint` using Jaccard similarity
- If best match score ≥ 0.7, returns that element
- Fast — O(n) DOM scan with no AI involved

**2b. RoleTextStrategy** (milliseconds, no LLM)
- Uses the stored role and text/label to call Playwright's accessible APIs:
  ```python
  page.get_by_role(stored_role, name=stored_label)
  page.get_by_label(stored_label)
  page.get_by_placeholder(stored_placeholder)
  ```
- No LLM needed — relies on ARIA semantics being stable

**2c. LLMHealStrategy** (seconds, uses Ollama)
- Last resort — sends stored fingerprint + current DOM to the LLM
- Prompt: `heal.j2` — asks for a new CSS or XPath selector
- Result validated with `is_visible()` before caching
- Result cached at the locator TTL (7 days by default)

### Tier 3 — Deterministic Strategies (milliseconds, no cache)

Used when there is no cache entry at all (first run, or after `cache clear`):

```
_try_deterministic(intent, page):
   1. get_by_role(guessed_role, name=extracted_text)
   2. get_by_label(extracted_text)
   3. get_by_placeholder(extracted_text)
   4. get_by_text(extracted_text)
   5. get_by_test_id(extracted_text)
```

The first strategy that finds a visible element wins. Its `LocatorCandidate` (including the winning strategy name) is stored in cache.

### Tier 4 — LLM Proposal (seconds, no cache)

If no deterministic strategy works:

```
LLM prompt (locator_resolve.j2):
  intent + DOM context + AOM context
  → selector string (CSS or XPath)
validate: page.locator(selector).is_visible()
cache winner
```

---

## ElementFingerprint

Every resolved locator has a fingerprint stored alongside it in the cache:

```python
@dataclass
class ElementFingerprint:
    role: str           # ARIA role: "textbox", "button", "link", etc.
    tag: str            # HTML tag: "input", "button", "a", etc.
    text: str           # Visible text (truncated to 80 chars)
    label: str | None   # aria-label or associated <label> text
    placeholder: str | None
    type: str | None    # <input type="...">: "email", "password", "submit"
    href: str | None    # For links
    testid: str | None  # data-testid attribute
    cls: str | None     # className (first 100 chars)
```

The fingerprint is extracted by calling `locator.evaluate()` with inline JavaScript — the same `INPUT_ROLES` mapping used by `dom.py`, so role detection is consistent throughout the pipeline.

### Fingerprint similarity scoring

Two fingerprints are compared field by field:

| Field | Weight | Match condition |
|---|---|---|
| `role` | 3× | Exact string match |
| `type` | 2× | Exact string match |
| `label` | 2× | Exact string match |
| `placeholder` | 2× | Exact string match |
| `testid` | 3× | Exact string match |
| `tag` | 1× | Exact string match |
| `text` | 1× | Normalized substring match |

Final score = matched_weight / total_weight (0.0 to 1.0)
Threshold for FingerprintStrategy: **0.7**

---

## Healing Event Log

Every healing attempt is recorded in `.oapw/healing.db`:

```sql
CREATE TABLE heal_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   REAL,
    intent       TEXT,
    page_url     TEXT,
    strategy     TEXT,    -- "fingerprint" | "role_text" | "llm"
    original_sel TEXT,    -- cached selector that became stale
    new_sel      TEXT,    -- healed selector (NULL if failed)
    success      INTEGER, -- 1 or 0
    latency_ms   REAL
);
```

Query healing stats:

```python
from oapw.healing.recorder import HealingRecorder
from oapw.core.config import get_config

recorder = HealingRecorder(db_path=get_config().data_dir / "healing.db")
stats = recorder.stats()
# {
#   "fingerprint": {"attempts": 42, "success": 38, "rate": 0.90},
#   "role_text":   {"attempts": 12, "success": 9,  "rate": 0.75},
#   "llm":         {"attempts": 4,  "success": 3,  "rate": 0.75},
# }
```

---

## Configuration

Healing behaviour is controlled by standard config values:

```env
# Locator cache TTL — how long before a locator is considered stale
OAPW_CACHE_L2_TTL_LOCATOR=604800   # 7 days (default)

# LLM model used for LLMHealStrategy
OAPW_OLLAMA_DEFAULT_MODEL=qwen2.5:3b

# LLM timeout — increase if LLM heal strategy times out
OAPW_OLLAMA_TIMEOUT=120
```

---

## Debugging Healing

### 1. Run with visible browser

```env
OAPW_BROWSER_HEADLESS=false
OAPW_BROWSER_SLOW_MO=500
```

### 2. Clear the locator cache to force re-resolution

```bash
oapw cache clear --yes
```

### 3. Check healing event log

```python
from oapw.healing.recorder import HealingRecorder
recorder = HealingRecorder(db_path=".oapw/healing.db")
print(recorder.stats())
```

### 4. Add logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

The resolver and healer emit `DEBUG` logs for every strategy attempt.

---

## Adding a Custom Healing Strategy

Implement the `HealStrategy` protocol:

```python
from oapw.agents.models import LocatorCandidate
from playwright.async_api import Page, Locator

class MyStrategy:
    async def heal(
        self,
        intent: str,
        page: Page,
        fingerprint: ElementFingerprint,
    ) -> tuple[Locator, LocatorCandidate] | None:
        # Try to find the element
        locator = page.locator("...")
        if await locator.is_visible():
            candidate = LocatorCandidate(
                selector="...",
                strategy=LocatorStrategy.ROLE,  # or add a new enum value
                confidence=0.9,
                reasoning="Found by custom strategy",
            )
            return locator, candidate
        return None
```

Then register it in `Healer.__init__`:

```python
# healing/healer.py
self._strategies = [
    FingerprintStrategy(),
    RoleTextStrategy(),
    MyStrategy(),         # add before LLM strategy
    LLMHealStrategy(...),
]
```
