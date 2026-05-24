"""EdgeCaseMutator — generate edge-case test variants from an existing test.

Takes a ``GeneratedTest`` and asks the LLM to produce N edge-case variants,
each targeting a different failure mode:
  - empty_input     → leave required fields blank
  - boundary        → max-length strings, extreme numeric values
  - special_chars   → Unicode, emoji, quotes, script tags (sanitized)
  - invalid_format  → wrong type (e.g. letters in a numeric field)
  - wrong_credentials → bad password, inactive user, locked account
  - concurrent      → rapid repeated submissions

Each mutation is returned as a ``MutatedTest`` with its own complete pytest code.

Usage:
  mutator = EdgeCaseMutator()
  mutations = await mutator.mutate(original_test, count=5)
  for m in mutations:
      print(m.mutation_type, "→", m.description)

  # Write mutations alongside the original
  paths = mutator.write_mutations(mutations, out_dir=Path("tests/generated"))
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.ollama_client import get_ollama_client
from oapw.generators.models import GeneratedTest, MutatedTest

if TYPE_CHECKING:
    from oapw.core.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:python)?\s*\n?(.*?)\n?```$", re.DOTALL)

# All supported mutation types — LLM picks from this list
MUTATION_TYPES = [
    "empty_input",
    "boundary_values",
    "special_characters",
    "invalid_format",
    "wrong_credentials",
    "sql_injection_attempt",
    "xss_attempt",
    "concurrent_submission",
    "session_expiry",
    "max_length_exceeded",
]


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


def _is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


class EdgeCaseMutator:
    """Generate edge-case test variants from a base ``GeneratedTest``.

    Parameters
    ----------
    ollama:
        ``OllamaClient`` instance.
    model:
        Ollama model.
    """

    def __init__(
        self,
        ollama: "OllamaClient | None" = None,
        model: str | None = None,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._cache = get_cache()

    async def mutate(
        self,
        test: GeneratedTest,
        count: int = 5,
        mutation_types: list[str] | None = None,
    ) -> list[MutatedTest]:
        """Generate ``count`` edge-case variants of ``test``.

        Parameters
        ----------
        test:
            The ``GeneratedTest`` to mutate.
        count:
            Number of mutations to request (1–10).
        mutation_types:
            Explicit list of mutation type strings to include.
            Defaults to a balanced selection from ``MUTATION_TYPES``.
        """
        count = min(max(1, count), 10)
        types_to_use = (mutation_types or MUTATION_TYPES)[:count]

        mutations: list[MutatedTest] = []
        for mtype in types_to_use:
            m = await self._mutate_one(test, mtype)
            if m:
                mutations.append(m)

        return mutations

    async def _mutate_one(
        self, test: GeneratedTest, mutation_type: str
    ) -> MutatedTest | None:
        cache_key = hashlib.blake2b(
            f"mutate:{test.test_name}:{mutation_type}:{self._model}".encode(),
            digest_size=16,
        ).hexdigest()

        cached = self._cache.get_llm(cache_key)
        if cached:
            try:
                data = json.loads(cached)
                return MutatedTest(
                    parent=test,
                    mutation_type=mutation_type,
                    description=data.get("description", mutation_type),
                    code=data.get("code", ""),
                )
            except Exception:
                pass

        prompt_text = prompts.render(
            "generate_edge_cases.j2",
            original_code=test.code[:3000],
            summary=test.summary,
            mutation_type=mutation_type,
            all_mutation_types=MUTATION_TYPES,
        )

        try:
            raw = await self._ollama.generate(prompt_text, model=self._model)
        except Exception as exc:
            logger.warning("EdgeCaseMutator: LLM call failed for %s: %s", mutation_type, exc)
            return None

        # LLM should return JSON {description, code}
        code, description = self._parse_response(raw, mutation_type)
        if not code:
            return None

        payload = json.dumps({"description": description, "code": code})
        self._cache.set_llm(cache_key, payload)

        return MutatedTest(
            parent=test,
            mutation_type=mutation_type,
            description=description,
            code=code,
        )

    def _parse_response(
        self, raw: str, mutation_type: str
    ) -> tuple[str, str]:
        """Parse LLM response → (code, description).

        Tries JSON first, falls back to extracting Python code block.
        """
        text = raw.strip()

        # Try JSON envelope
        try:
            data = json.loads(text)
            code = _strip_fences(data.get("code", ""))
            desc = data.get("description", mutation_type.replace("_", " "))
            if _is_valid_python(code):
                return code, desc
        except (json.JSONDecodeError, TypeError):
            pass

        # Try extracting a Python code block
        code = _strip_fences(text)
        if _is_valid_python(code):
            return code, mutation_type.replace("_", " ").title()

        logger.debug("EdgeCaseMutator: could not parse valid Python for %s", mutation_type)
        return "", mutation_type

    def write_mutations(
        self, mutations: list[MutatedTest], out_dir: Path
    ) -> list[Path]:
        """Write all mutations to ``out_dir`` and return their paths."""
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for m in mutations:
            path = out_dir / f"{m.test_name}.py"
            try:
                path.write_text(m.code, encoding="utf-8")
                paths.append(path)
            except Exception as exc:
                logger.warning("Failed to write mutation %s: %s", m.test_name, exc)
        return paths
