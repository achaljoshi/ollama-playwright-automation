"""JiraTestGenerator — generate pytest tests directly from Jira tickets.

Workflow:
  1. Fetch the ticket via AtlassianClient (falls back to KB search if unconfigured)
  2. Optionally retrieve RAG context (Jira-linked docs + code from KB)
  3. Render generate_test.j2 with ticket + context
  4. Call Ollama (L2/L3 cached) to produce the test code
  5. Strip markdown fences, validate Python syntax
  6. Optionally write to disk + record traceability link

CLI usage:
  oapw generate from-jira AUTH-42
  oapw generate from-jira AUTH-42 --out tests/generated/

Programmatic usage:
  gen = JiraTestGenerator()
  result = await gen.generate("AUTH-42", out_dir=Path("tests/generated"))
  print(result.test.code)
"""

from __future__ import annotations

import ast
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
    """Remove leading/trailing markdown code fences if the LLM included them."""
    m = _FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


def _is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _safe_module_name(ticket_key: str, summary: str) -> str:
    """Convert 'AUTH-42: Login with SSO' → 'test_auth_42_login_with_sso'."""
    base = f"{ticket_key} {summary}".lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = base.strip("_")[:60]
    return f"test_{base}"


class JiraTestGenerator:
    """Generate pytest test files from Jira tickets.

    Parameters
    ----------
    ollama:
        ``OllamaClient`` instance. Defaults to global singleton.
    model:
        Ollama model to use. Defaults to ``OapwConfig.ollama_default_model``.
    use_kb:
        Whether to enrich prompts with knowledge base context (RAG).
        Set to False if ChromaDB is not installed or KB is empty.
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
        ticket_key: str,
        out_dir: Path | None = None,
    ) -> GenerationResult:
        """Generate a test for ``ticket_key``.

        Parameters
        ----------
        ticket_key:
            Jira ticket key, e.g. ``"AUTH-42"``.
        out_dir:
            If provided, write the generated test file here and record
            the traceability link in the SQLite traceability store.
        """
        # ── 1. Fetch ticket ──────────────────────────────────────────────────
        ticket = await self._fetch_ticket(ticket_key)
        if ticket is None:
            return GenerationResult(
                test=GeneratedTest(
                    test_name=f"test_{ticket_key.lower().replace('-', '_')}",
                    code="",
                    summary=f"Could not fetch {ticket_key}",
                    source_type="jira",
                    ticket_key=ticket_key,
                ),
                error=f"Could not fetch Jira ticket {ticket_key}. "
                      "Check OAPW_ATLASSIAN_URL and run: oapw auth atlassian",
            )

        # ── 2. Knowledge base context ────────────────────────────────────────
        knowledge_context = ""
        confluence_ids: list[str] = []
        if self._use_kb:
            knowledge_context, confluence_ids = await self._get_kb_context(
                ticket_key, ticket["summary"], ticket.get("description", "")
            )

        # ── 3. Build prompt and generate ─────────────────────────────────────
        cache_key = self._cache_key(ticket_key, self._model, bool(knowledge_context))
        cached_code = self._cache.get_llm(cache_key)

        if cached_code:
            logger.debug("JiraTestGenerator: cache hit for %s", ticket_key)
            code = cached_code
        else:
            prompt_text = prompts.render(
                "generate_test.j2",
                ticket_key=ticket_key,
                summary=ticket["summary"],
                issue_type=ticket.get("issue_type", "Story"),
                priority=ticket.get("priority", "Medium"),
                description=ticket.get("description", ""),
                acceptance_criteria=ticket.get("acceptance_criteria", ""),
                knowledge_context=knowledge_context,
                criteria_covered=ticket.get("acceptance_criteria", "")[:200],
            )
            raw = await self._ollama.generate(prompt_text, model=self._model)
            code = _strip_fences(raw)
            if _is_valid_python(code):
                self._cache.set_llm(cache_key, code)
            else:
                logger.warning("JiraTestGenerator: generated code has syntax errors for %s", ticket_key)

        # ── 4. Build result ──────────────────────────────────────────────────
        test_name = _safe_module_name(ticket_key, ticket["summary"])
        generated = GeneratedTest(
            test_name=test_name,
            code=code,
            summary=ticket["summary"],
            source_type="jira",
            ticket_key=ticket_key,
            jira_ids=[ticket_key],
            confluence_ids=confluence_ids,
            model=self._model,
        )

        # ── 5. Write to disk + record traceability ───────────────────────────
        result = GenerationResult(test=generated)
        if out_dir and code:
            result = self._write(generated, out_dir)

        return result

    async def generate_batch(
        self, ticket_keys: list[str], out_dir: Path | None = None
    ) -> list[GenerationResult]:
        """Generate tests for multiple tickets sequentially."""
        results = []
        for key in ticket_keys:
            r = await self.generate(key, out_dir=out_dir)
            results.append(r)
        return results

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _fetch_ticket(self, ticket_key: str) -> dict | None:
        """Fetch ticket via AtlassianClient; fall back to KB search."""
        cfg = get_config()

        # Try live Atlassian API
        if cfg.atlassian_url and cfg.atlassian_email:
            try:
                from oapw.enterprise.atlassian_client import AtlassianClient
                client = AtlassianClient()
                ticket = await client.get_jira_issue(ticket_key)
                return {
                    "summary": ticket.summary,
                    "description": ticket.description,
                    "acceptance_criteria": ticket.acceptance_criteria,
                    "issue_type": ticket.issue_type,
                    "priority": ticket.priority,
                    "components": ticket.components,
                    "labels": ticket.labels,
                }
            except Exception as exc:
                logger.warning("AtlassianClient failed for %s: %s", ticket_key, exc)

        # Fall back to KB search
        try:
            from oapw.knowledge.rag import RAGRetriever
            retriever = RAGRetriever()
            snippets = await retriever.retrieve(
                ticket_key, source_filter="jira", top_k=1
            )
            if snippets:
                s = snippets[0]
                return {
                    "summary": s.title or ticket_key,
                    "description": s.text,
                    "acceptance_criteria": "",
                    "issue_type": "Story",
                    "priority": "Medium",
                    "components": [],
                    "labels": [],
                }
        except Exception as exc:
            logger.debug("KB fallback failed for %s: %s", ticket_key, exc)

        return None

    async def _get_kb_context(
        self, ticket_key: str, summary: str, description: str
    ) -> tuple[str, list[str]]:
        """Return (formatted_context, confluence_ids) from the knowledge base."""
        try:
            from oapw.knowledge.rag import RAGRetriever
            retriever = RAGRetriever()
            query = f"{summary} {description[:300]}"
            snippets = await retriever.retrieve(
                query, linked_jira=[ticket_key], top_k=5
            )
            conf_ids = [
                s.metadata.get("page_id", "")
                for s in snippets
                if s.source == "confluence" and s.metadata.get("page_id")
            ]
            return retriever.format_context(snippets), conf_ids
        except Exception as exc:
            logger.debug("KB context retrieval failed: %s", exc)
            return "", []

    def _cache_key(self, ticket_key: str, model: str, has_kb: bool) -> str:
        import hashlib
        raw = f"gen_jira:{ticket_key}:{model}:{has_kb}"
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()

    def _write(self, test: GeneratedTest, out_dir: Path) -> GenerationResult:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{test.test_name}.py"
            path.write_text(test.code, encoding="utf-8")
            test.out_path = path
            logger.info("Written: %s", path)

            # Record traceability
            if test.jira_ids:
                try:
                    from oapw.enterprise.traceability import TraceabilityStore
                    store = TraceabilityStore(db_path=get_config().traceability_db)
                    store.link_test(
                        test_path=str(path),
                        jira_ids=test.jira_ids,
                        confluence_ids=test.confluence_ids,
                    )
                except Exception as exc:
                    logger.debug("Traceability recording failed: %s", exc)

            return GenerationResult(test=test, written=True, path=path)
        except Exception as exc:
            return GenerationResult(test=test, error=str(exc))
