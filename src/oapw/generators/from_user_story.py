"""UserStoryGenerator — generate pytest tests from plain-text user stories.

No Jira connection required. Accepts any user story or feature description
and produces a complete pytest file using the LLM + optional KB context.

Usage:
  oapw generate from-story "As a user I want to reset my password via email"
  oapw generate from-story "Login form should validate email format" --feature auth

Programmatic:
  gen = UserStoryGenerator()
  result = await gen.generate(
      story="As a user I want to log in with SSO",
      feature_name="sso_login",
  )
  print(result.test.code)
"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import oapw.prompts as prompts
from oapw.cache.manager import get_cache
from oapw.core.config import get_config
from oapw.core.ollama_client import get_ollama_client
from oapw.generators.models import GeneratedTest, GenerationResult

if TYPE_CHECKING:
    from oapw.core.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:python)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


def _is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _safe_module_name(feature: str, story: str) -> str:
    base = feature if feature else story[:60]
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return f"test_{base[:60]}"


class UserStoryGenerator:
    """Generate pytest test files from plain-text user stories.

    Parameters
    ----------
    ollama:
        ``OllamaClient`` instance. Defaults to global singleton.
    model:
        Ollama model. Defaults to ``OapwConfig.ollama_default_model``.
    use_kb:
        Whether to inject knowledge base context into the prompt.
    """

    def __init__(
        self,
        ollama: "OllamaClient | None" = None,
        model: str | None = None,
        use_kb: bool = True,
    ) -> None:
        self._ollama = ollama or get_ollama_client()
        self._model = model or get_config().ollama_default_model
        self._use_kb = use_kb
        self._cache = get_cache()

    async def generate(
        self,
        story: str,
        feature_name: str = "",
        out_dir: Path | None = None,
    ) -> GenerationResult:
        """Generate a test for the given user story text.

        Parameters
        ----------
        story:
            Plain-text description, e.g. ``"As a user I want to reset my password"``.
        feature_name:
            Short name used for the output file, e.g. ``"password_reset"``.
            If empty, derived from the story text.
        out_dir:
            If provided, write the generated file to this directory.
        """
        # ── 1. Optional KB context ──────────────────────────────────────────
        knowledge_context = ""
        if self._use_kb:
            knowledge_context = await self._get_kb_context(story)

        # ── 2. Cache check ──────────────────────────────────────────────────
        cache_key = hashlib.blake2b(
            f"gen_story:{story}:{self._model}:{bool(knowledge_context)}".encode(),
            digest_size=16,
        ).hexdigest()

        cached = self._cache.get_llm(cache_key)
        if cached:
            code = cached
        else:
            prompt_text = prompts.render(
                "generate_from_story.j2",
                story=story,
                feature_name=feature_name,
                knowledge_context=knowledge_context,
            )
            raw = await self._ollama.generate(prompt_text, model=self._model)
            code = _strip_fences(raw)
            if _is_valid_python(code):
                self._cache.set_llm(cache_key, code)
            else:
                logger.warning("UserStoryGenerator: generated code has syntax errors")

        # ── 3. Build result ─────────────────────────────────────────────────
        test_name = _safe_module_name(feature_name, story)
        generated = GeneratedTest(
            test_name=test_name,
            code=code,
            summary=story[:120],
            source_type="user_story",
            model=self._model,
        )

        result = GenerationResult(test=generated)
        if out_dir and code:
            result = self._write(generated, out_dir)
        return result

    async def _get_kb_context(self, story: str) -> str:
        try:
            from oapw.knowledge.rag import RAGRetriever
            snippets = await RAGRetriever().retrieve(story, top_k=4)
            return RAGRetriever().format_context(snippets)
        except Exception as exc:
            logger.debug("KB context failed: %s", exc)
            return ""

    def _write(self, test: GeneratedTest, out_dir: Path) -> GenerationResult:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{test.test_name}.py"
            path.write_text(test.code, encoding="utf-8")
            test.out_path = path
            return GenerationResult(test=test, written=True, path=path)
        except Exception as exc:
            return GenerationResult(test=test, error=str(exc))
