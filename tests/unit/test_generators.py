"""Tests for the test generator layer.

All LLM calls and Atlassian/KB accesses are mocked — no network required.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oapw.generators.models import GeneratedTest, GenerationResult, MutatedTest
from oapw.generators.from_jira import (
    JiraTestGenerator,
    _strip_fences,
    _is_valid_python,
    _safe_module_name,
)
from oapw.generators.from_user_story import UserStoryGenerator
from oapw.generators.crawler import SmokeTestCrawler, _url_to_test_name
from oapw.generators.mutator import EdgeCaseMutator, MUTATION_TYPES
from oapw.cache.manager import CacheManager


# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_TEST_CODE = '''"""Test module."""
import pytest
pytestmark = pytest.mark.asyncio

async def test_login():
    pass
'''

_TICKET_DATA = {
    "summary": "Login with SSO",
    "description": "As a user I want to log in with SSO",
    "acceptance_criteria": "Given I click Sign in with Microsoft\nWhen I complete auth\nThen I see dashboard",
    "issue_type": "Story",
    "priority": "High",
    "components": ["Authentication"],
    "labels": ["sso"],
}


def _make_ollama(return_value: str = _VALID_TEST_CODE) -> MagicMock:
    ollama = MagicMock()
    ollama.generate = AsyncMock(return_value=return_value)
    return ollama


def _make_cache() -> CacheManager:
    tmp = Path(tempfile.mkdtemp())
    return CacheManager(data_dir=tmp)


# ── GeneratedTest model ───────────────────────────────────────────────────────

class TestGeneratedTestModel:
    def test_defaults(self):
        t = GeneratedTest(test_name="test_x", code="pass", summary="x", source_type="jira")
        assert t.ticket_key == ""
        assert t.jira_ids == []
        assert t.confluence_ids == []
        assert t.out_path is None

    def test_generated_at_is_iso(self):
        t = GeneratedTest(test_name="t", code="", summary="s", source_type="smoke")
        assert "T" in t.generated_at  # ISO timestamp


class TestMutatedTestModel:
    def test_test_name_combines_parent_and_type(self):
        parent = GeneratedTest(test_name="test_login", code="pass", summary="s", source_type="jira")
        m = MutatedTest(parent=parent, mutation_type="empty_input", description="d", code="pass")
        assert m.test_name == "test_login_empty_input"


class TestGenerationResultModel:
    def test_ok_when_no_error(self):
        t = GeneratedTest(test_name="t", code="", summary="", source_type="jira")
        r = GenerationResult(test=t)
        assert r.ok is True

    def test_not_ok_when_error(self):
        t = GeneratedTest(test_name="t", code="", summary="", source_type="jira")
        r = GenerationResult(test=t, error="something went wrong")
        assert r.ok is False


# ── Helper functions ──────────────────────────────────────────────────────────

class TestHelpers:
    def test_strip_fences_with_python_fence(self):
        fenced = "```python\nprint('hi')\n```"
        assert _strip_fences(fenced) == "print('hi')"

    def test_strip_fences_without_fence(self):
        code = "print('hi')"
        assert _strip_fences(code) == "print('hi')"

    def test_strip_fences_plain_backtick_fence(self):
        fenced = "```\nresult = 1 + 1\n```"
        assert _strip_fences(fenced) == "result = 1 + 1"

    def test_is_valid_python_true(self):
        assert _is_valid_python("x = 1\ny = 2") is True

    def test_is_valid_python_false(self):
        assert _is_valid_python("def broken(:\n    pass") is False

    def test_safe_module_name_basic(self):
        name = _safe_module_name("AUTH-42", "Login with SSO")
        assert name.startswith("test_")
        assert "auth" in name.lower()
        assert " " not in name

    def test_safe_module_name_no_special_chars(self):
        name = _safe_module_name("PROJ-1", "User can't sign-in!")
        assert all(c.isalnum() or c == "_" for c in name)


# ── _url_to_test_name ─────────────────────────────────────────────────────────

class TestUrlToTestName:
    def test_root_path(self):
        assert _url_to_test_name("http://localhost:3000/") == "test_smoke_home"

    def test_nested_path(self):
        result = _url_to_test_name("http://localhost:3000/admin/users")
        assert "admin" in result
        assert "users" in result

    def test_no_spaces(self):
        result = _url_to_test_name("http://localhost:3000/my-page")
        assert " " not in result


# ── JiraTestGenerator ─────────────────────────────────────────────────────────

class TestJiraTestGenerator:
    def _make_gen(self, ticket_data=None, llm_response=None):
        ollama = _make_ollama(llm_response or _VALID_TEST_CODE)
        cache = _make_cache()
        gen = JiraTestGenerator(ollama=ollama, use_kb=False)
        gen._cache = cache
        return gen, ollama

    @pytest.mark.asyncio
    async def test_generate_calls_ollama(self):
        gen, ollama = self._make_gen()
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
            result = await gen.generate("AUTH-42")
        ollama.generate.assert_awaited_once()
        assert result.ok

    @pytest.mark.asyncio
    async def test_generate_returns_code(self):
        gen, _ = self._make_gen()
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
            result = await gen.generate("AUTH-42")
        assert result.test.code == _VALID_TEST_CODE.strip()

    @pytest.mark.asyncio
    async def test_generate_sets_ticket_key(self):
        gen, _ = self._make_gen()
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
            result = await gen.generate("AUTH-42")
        assert result.test.ticket_key == "AUTH-42"
        assert "AUTH-42" in result.test.jira_ids

    @pytest.mark.asyncio
    async def test_generate_source_type_is_jira(self):
        gen, _ = self._make_gen()
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
            result = await gen.generate("AUTH-42")
        assert result.test.source_type == "jira"

    @pytest.mark.asyncio
    async def test_generate_caches_result(self):
        gen, ollama = self._make_gen()
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
            await gen.generate("AUTH-42")
            await gen.generate("AUTH-42")
        assert ollama.generate.await_count == 1  # second call from cache

    @pytest.mark.asyncio
    async def test_generate_writes_file(self):
        gen, _ = self._make_gen()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
                result = await gen.generate("AUTH-42", out_dir=Path(tmpdir))
            assert result.written
            assert result.path.exists()

    @pytest.mark.asyncio
    async def test_generate_returns_error_when_ticket_not_found(self):
        gen, _ = self._make_gen()
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=None)):
            result = await gen.generate("NOTFOUND-99")
        assert not result.ok
        assert "NOTFOUND-99" in result.error

    @pytest.mark.asyncio
    async def test_generate_strips_fences_from_llm_output(self):
        fenced = f"```python\n{_VALID_TEST_CODE}```"
        gen, _ = self._make_gen(llm_response=fenced)
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
            result = await gen.generate("AUTH-42")
        assert "```" not in result.test.code

    @pytest.mark.asyncio
    async def test_generate_batch(self):
        gen, ollama = self._make_gen()
        ollama.generate = AsyncMock(return_value=_VALID_TEST_CODE)
        with patch.object(gen, "_fetch_ticket", AsyncMock(return_value=_TICKET_DATA)):
            results = await gen.generate_batch(["AUTH-1", "AUTH-2"])
        assert len(results) == 2


# ── UserStoryGenerator ────────────────────────────────────────────────────────

class TestUserStoryGenerator:
    def _make_gen(self, llm_response=None):
        ollama = _make_ollama(llm_response or _VALID_TEST_CODE)
        gen = UserStoryGenerator(ollama=ollama, use_kb=False)
        gen._cache = _make_cache()
        return gen, ollama

    @pytest.mark.asyncio
    async def test_generate_returns_code(self):
        gen, _ = self._make_gen()
        result = await gen.generate("As a user I want to log in")
        assert result.ok
        assert result.test.code

    @pytest.mark.asyncio
    async def test_generate_source_type_is_user_story(self):
        gen, _ = self._make_gen()
        result = await gen.generate("As a user I want to log in")
        assert result.test.source_type == "user_story"

    @pytest.mark.asyncio
    async def test_generate_test_name_uses_feature(self):
        gen, _ = self._make_gen()
        result = await gen.generate("Log in story", feature_name="login_flow")
        assert "login_flow" in result.test.test_name

    @pytest.mark.asyncio
    async def test_generate_caches_result(self):
        gen, ollama = self._make_gen()
        story = "As a user I want to reset my password"
        await gen.generate(story)
        await gen.generate(story)
        assert ollama.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_generate_writes_file(self):
        gen, _ = self._make_gen()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await gen.generate("Test story", out_dir=Path(tmpdir))
            assert result.written
            assert result.path.exists()

    @pytest.mark.asyncio
    async def test_generate_strips_fences(self):
        gen, _ = self._make_gen(f"```python\n{_VALID_TEST_CODE}\n```")
        result = await gen.generate("story")
        assert "```" not in result.test.code


# ── EdgeCaseMutator ───────────────────────────────────────────────────────────

class TestEdgeCaseMutator:
    def _make_base_test(self) -> GeneratedTest:
        return GeneratedTest(
            test_name="test_auth_login",
            code=_VALID_TEST_CODE,
            summary="Login with SSO",
            source_type="jira",
            ticket_key="AUTH-42",
        )

    def _make_mutator(self, llm_response=None):
        default_resp = json.dumps({
            "description": "Test with empty inputs",
            "code": _VALID_TEST_CODE,
        })
        ollama = _make_ollama(llm_response or default_resp)
        mutator = EdgeCaseMutator(ollama=ollama)
        mutator._cache = _make_cache()
        return mutator, ollama

    @pytest.mark.asyncio
    async def test_mutate_returns_list_of_mutations(self):
        mutator, _ = self._make_mutator()
        base = self._make_base_test()
        mutations = await mutator.mutate(base, count=2)
        assert len(mutations) == 2

    @pytest.mark.asyncio
    async def test_mutate_sets_mutation_type(self):
        mutator, _ = self._make_mutator()
        base = self._make_base_test()
        mutations = await mutator.mutate(base, count=1, mutation_types=["empty_input"])
        assert mutations[0].mutation_type == "empty_input"

    @pytest.mark.asyncio
    async def test_mutate_has_code(self):
        mutator, _ = self._make_mutator()
        base = self._make_base_test()
        mutations = await mutator.mutate(base, count=1, mutation_types=["empty_input"])
        assert mutations[0].code

    @pytest.mark.asyncio
    async def test_mutate_has_description(self):
        mutator, _ = self._make_mutator()
        base = self._make_base_test()
        mutations = await mutator.mutate(base, count=1, mutation_types=["empty_input"])
        assert mutations[0].description == "Test with empty inputs"

    @pytest.mark.asyncio
    async def test_mutate_respects_count_cap(self):
        mutator, _ = self._make_mutator()
        base = self._make_base_test()
        mutations = await mutator.mutate(base, count=99)
        assert len(mutations) <= len(MUTATION_TYPES)

    @pytest.mark.asyncio
    async def test_mutate_caches_result(self):
        mutator, ollama = self._make_mutator()
        base = self._make_base_test()
        await mutator.mutate(base, count=1, mutation_types=["empty_input"])
        await mutator.mutate(base, count=1, mutation_types=["empty_input"])
        assert ollama.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_mutate_fallback_on_plain_python_response(self):
        """LLM returns plain Python (no JSON) — should still produce mutation."""
        mutator, _ = self._make_mutator(llm_response=_VALID_TEST_CODE)
        base = self._make_base_test()
        mutations = await mutator.mutate(base, count=1, mutation_types=["boundary_values"])
        assert len(mutations) == 1
        assert mutations[0].code

    def test_write_mutations(self):
        mutator, _ = self._make_mutator()
        parent = self._make_base_test()
        ms = [
            MutatedTest(parent=parent, mutation_type="empty_input",
                        description="d", code=_VALID_TEST_CODE),
            MutatedTest(parent=parent, mutation_type="boundary_values",
                        description="d", code=_VALID_TEST_CODE),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = mutator.write_mutations(ms, out_dir=Path(tmpdir))
            assert len(paths) == 2
            assert all(p.exists() for p in paths)


# ── MUTATION_TYPES constant ───────────────────────────────────────────────────

class TestMutationTypes:
    def test_mutation_types_is_non_empty_list(self):
        assert isinstance(MUTATION_TYPES, list)
        assert len(MUTATION_TYPES) >= 5

    def test_no_duplicates(self):
        assert len(MUTATION_TYPES) == len(set(MUTATION_TYPES))

    def test_empty_input_present(self):
        assert "empty_input" in MUTATION_TYPES
