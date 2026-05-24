"""Tests for the hybrid API+UI layer — ApiClient and HybridContext.

All Playwright internals are mocked so tests run without a browser.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from oapw.hybrid.api_client import ApiClient, _cache_key, _CachedApiResponse
from oapw.cache.manager import CacheManager
from pathlib import Path
import tempfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pw_response(status: int = 200, body: dict | None = None) -> MagicMock:
    """Build a mock Playwright APIResponse."""
    r = MagicMock()
    r.status = status
    r.ok = 200 <= status < 300
    r.url = "http://localhost:3000/api/test"
    r.headers = {}
    r.json = AsyncMock(return_value=body or {})
    r.text = AsyncMock(return_value=json.dumps(body or {}))
    r.body = AsyncMock(return_value=json.dumps(body or {}).encode())
    return r


def _make_request_context(responses: dict | None = None) -> MagicMock:
    """Build a mock Playwright APIRequestContext."""
    ctx = MagicMock()
    resp_map = responses or {}

    async def _method_handler(url, **kwargs):
        body = resp_map.get(url, {"ok": True})
        return _make_pw_response(200, body)

    ctx.get = AsyncMock(side_effect=_method_handler)
    ctx.post = AsyncMock(side_effect=_method_handler)
    ctx.put = AsyncMock(side_effect=_method_handler)
    ctx.patch = AsyncMock(side_effect=_method_handler)
    ctx.delete = AsyncMock(side_effect=_method_handler)
    return ctx


def _make_client(responses=None) -> tuple[ApiClient, MagicMock]:
    tmp = Path(tempfile.mkdtemp())
    cache = CacheManager(data_dir=tmp)
    ctx = _make_request_context(responses)
    client = ApiClient(
        request_context=ctx,
        base_url="http://localhost:3000",
        cache=cache,
    )
    return client, ctx


# ── ApiClient — basic HTTP methods ────────────────────────────────────────────

class TestApiClientGet:
    @pytest.mark.asyncio
    async def test_get_calls_request_context(self):
        client, ctx = _make_client()
        await client.get("/api/users")
        ctx.get.assert_awaited_once()
        call_url = ctx.get.call_args[0][0]
        assert call_url == "http://localhost:3000/api/users"

    @pytest.mark.asyncio
    async def test_get_json_returns_parsed_body(self):
        client, _ = _make_client({"http://localhost:3000/api/users": [{"id": 1}]})
        result = await client.get_json("/api/users")
        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_get_caches_200_response(self):
        client, ctx = _make_client({"http://localhost:3000/api/me": {"name": "Alice"}})
        result1 = await client.get_json("/api/me")
        result2 = await client.get_json("/api/me")
        # Only one real HTTP call — second from cache
        assert ctx.get.await_count == 1
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_get_skips_cache_when_disabled(self):
        client, ctx = _make_client()
        await client.get_json("/api/me", use_cache=False)
        await client.get_json("/api/me", use_cache=False)
        assert ctx.get.await_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(self):
        client, ctx = _make_client({"http://localhost:3000/api/item": {"v": 1}})
        await client.get_json("/api/item")       # populates cache
        client.invalidate("/api/item")
        await client.get_json("/api/item")       # should hit server again
        assert ctx.get.await_count == 2


class TestApiClientPost:
    @pytest.mark.asyncio
    async def test_post_sends_json_body(self):
        client, ctx = _make_client()
        await client.post("/api/login", json={"email": "u@t.com", "password": "s"})
        ctx.post.assert_awaited_once()
        kwargs = ctx.post.call_args[1]
        assert kwargs["data"] == {"email": "u@t.com", "password": "s"}

    @pytest.mark.asyncio
    async def test_post_json_returns_response_body(self):
        client, _ = _make_client({"http://localhost:3000/api/login": {"token": "abc123"}})
        result = await client.post_json("/api/login", json={"email": "u", "password": "p"})
        assert result["token"] == "abc123"

    @pytest.mark.asyncio
    async def test_post_does_not_cache(self):
        client, ctx = _make_client()
        await client.post_json("/api/login", json={})
        await client.post_json("/api/login", json={})
        assert ctx.post.await_count == 2  # no caching for POST


class TestApiClientAuth:
    @pytest.mark.asyncio
    async def test_set_bearer_token_injects_header(self):
        client, ctx = _make_client()
        client.set_bearer_token("my-jwt-token")
        await client.get("/api/protected")
        headers = ctx.get.call_args[1]["headers"]
        assert headers.get("Authorization") == "Bearer my-jwt-token"

    def test_clear_auth_removes_header(self):
        client, _ = _make_client()
        client.set_bearer_token("tok")
        client.clear_auth()
        assert "Authorization" not in client._extra_headers

    def test_set_custom_header(self):
        client, _ = _make_client()
        client.set_header("X-Tenant-ID", "abc")
        assert client._extra_headers["X-Tenant-ID"] == "abc"


class TestApiClientPutDeletePatch:
    @pytest.mark.asyncio
    async def test_put_json(self):
        client, ctx = _make_client()
        await client.put_json("/api/users/1", json={"name": "Bob"})
        ctx.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_patch_json(self):
        client, ctx = _make_client()
        await client.patch_json("/api/users/1", json={"active": False})
        ctx.patch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete(self):
        client, ctx = _make_client()
        await client.delete("/api/users/1")
        ctx.delete.assert_awaited_once()


class TestApiClientUrlHandling:
    @pytest.mark.asyncio
    async def test_absolute_url_not_prefixed(self):
        client, ctx = _make_client()
        await client.get("https://other-service.com/api/data")
        url = ctx.get.call_args[0][0]
        assert url == "https://other-service.com/api/data"

    @pytest.mark.asyncio
    async def test_relative_path_prefixed_with_base_url(self):
        client, ctx = _make_client()
        await client.get("/health")
        url = ctx.get.call_args[0][0]
        assert url == "http://localhost:3000/health"


# ── _cache_key ────────────────────────────────────────────────────────────────

class TestCacheKey:
    def test_deterministic(self):
        assert _cache_key("GET", "/api/x", None) == _cache_key("GET", "/api/x", None)

    def test_differs_by_method(self):
        assert _cache_key("GET", "/api/x", None) != _cache_key("POST", "/api/x", None)

    def test_differs_by_params(self):
        assert _cache_key("GET", "/api/x", {"a": 1}) != _cache_key("GET", "/api/x", {"a": 2})

    def test_params_order_independent(self):
        assert (
            _cache_key("GET", "/api/x", {"a": 1, "b": 2})
            == _cache_key("GET", "/api/x", {"b": 2, "a": 1})
        )


# ── HybridContext ─────────────────────────────────────────────────────────────

class TestHybridContext:
    def _make_hybrid(self, login_response=None):
        from oapw.hybrid.context import HybridContext
        from oapw.core.ai_page import AiPage

        tmp = Path(tempfile.mkdtemp())
        cache = CacheManager(data_dir=tmp)
        resp = login_response or {"token": "tok123"}
        ctx_mock = _make_request_context({"http://localhost:3000/api/auth/login": resp})
        api = ApiClient(ctx_mock, base_url="http://localhost:3000", cache=cache)

        page_mock = MagicMock()
        ai_page = MagicMock(spec=AiPage)
        ai_page._page = page_mock

        return HybridContext(page=ai_page, api=api), ctx_mock

    @pytest.mark.asyncio
    async def test_login_via_api_sets_bearer_token(self):
        hybrid, _ = self._make_hybrid({"token": "jwt-abc"})
        token = await hybrid.login_via_api("/api/auth/login", "u@t.com", "pass")
        assert token == "jwt-abc"
        assert hybrid.api._extra_headers.get("Authorization") == "Bearer jwt-abc"

    @pytest.mark.asyncio
    async def test_login_via_api_no_token_returns_none(self):
        # Cookie-based auth — no token in response
        hybrid, _ = self._make_hybrid({"message": "ok"})
        token = await hybrid.login_via_api("/api/auth/login", "u@t.com", "pass")
        assert token is None
        assert "Authorization" not in hybrid.api._extra_headers

    @pytest.mark.asyncio
    async def test_verify_via_api_passes_on_match(self):
        hybrid, ctx_mock = self._make_hybrid()
        ctx_mock.get = AsyncMock(
            return_value=_make_pw_response(200, {"status": "ok", "count": 5})
        )
        # Should not raise
        await hybrid.verify_via_api("/api/health", {"status": "ok"})

    @pytest.mark.asyncio
    async def test_verify_via_api_raises_on_mismatch(self):
        hybrid, ctx_mock = self._make_hybrid()
        ctx_mock.get = AsyncMock(
            return_value=_make_pw_response(200, {"status": "error"})
        )
        with pytest.raises(AssertionError, match="API state mismatch"):
            await hybrid.verify_via_api("/api/health", {"status": "ok"})

    @pytest.mark.asyncio
    async def test_setup_resource_posts_data(self):
        hybrid, ctx_mock = self._make_hybrid()
        ctx_mock.post = AsyncMock(
            return_value=_make_pw_response(200, {"id": "u1", "email": "a@b.com"})
        )
        result = await hybrid.setup_resource("/api/users", {"email": "a@b.com"})
        assert result["id"] == "u1"

    @pytest.mark.asyncio
    async def test_teardown_resource_calls_delete(self):
        hybrid, ctx_mock = self._make_hybrid()
        ctx_mock.delete = AsyncMock(return_value=_make_pw_response(204, {}))
        await hybrid.teardown_resource("/api/users/u1")
        ctx_mock.delete.assert_awaited_once()
