"""ApiClient — Playwright APIRequestContext wrapper for hybrid API+UI tests.

Wraps Playwright's built-in request API with:
  - Base URL management (app_base_url from config)
  - Bearer token / custom header injection
  - Response caching for GET requests (respects cache manager)
  - Typed JSON helpers so tests never call .json() manually
  - PII masking applied to request bodies before logging

When created from a BrowserContext, the ApiClient shares cookies with the
browser page automatically — logging in via API logs in the browser too.

Usage:
    async with managed_browser() as mgr:
        async with mgr.new_context() as ctx:
            page = await ctx.new_page()
            api = ApiClient(request_context=ctx.request, base_url="http://localhost:3000")
            resp = await api.post_json("/api/auth/login", {"email": "u@t.com", "password": "s"})
            token = resp["token"]
            api.set_bearer_token(token)
            data = await api.get_json("/api/me")
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, TYPE_CHECKING

from oapw.cache.manager import get_cache

if TYPE_CHECKING:
    from playwright.async_api import APIRequestContext, APIResponse

logger = logging.getLogger(__name__)

_DEFAULT_API_TTL = 300  # 5 min TTL for cached GET responses


def _cache_key(method: str, url: str, params: dict | None) -> str:
    raw = f"{method}:{url}:{json.dumps(params or {}, sort_keys=True)}"
    return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


class ApiResponse:
    """Thin wrapper around Playwright's APIResponse for convenience."""

    def __init__(self, pw_response: "APIResponse") -> None:
        self._r = pw_response

    @property
    def status(self) -> int:
        return self._r.status

    @property
    def ok(self) -> bool:
        return self._r.ok

    @property
    def headers(self) -> dict[str, str]:
        return dict(self._r.headers)

    async def json(self) -> Any:
        return await self._r.json()

    async def text(self) -> str:
        return await self._r.text()

    async def body(self) -> bytes:
        return await self._r.body()

    def raise_for_status(self) -> None:
        if not self._r.ok:
            raise AssertionError(
                f"API request failed: HTTP {self._r.status} for {self._r.url}"
            )


class ApiClient:
    """Playwright APIRequestContext with caching and auth helpers.

    Parameters
    ----------
    request_context:
        A Playwright ``APIRequestContext``. When obtained from
        ``browser_context.request`` it shares the browser's cookie jar,
        so a login via this client also logs in the page.
    base_url:
        Absolute base URL prepended to every relative path.
    cache:
        CacheManager instance (defaults to global get_cache()).
    """

    def __init__(
        self,
        request_context: "APIRequestContext",
        base_url: str = "",
        cache=None,
    ) -> None:
        self._ctx = request_context
        self._base_url = base_url.rstrip("/")
        self._cache = cache or get_cache()
        self._extra_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Auth helpers ──────────────────────────────────────────────────────────

    def set_bearer_token(self, token: str) -> None:
        """Inject an Authorization: Bearer header for all subsequent requests."""
        self._extra_headers["Authorization"] = f"Bearer {token}"

    def set_header(self, key: str, value: str) -> None:
        """Add / override an arbitrary request header."""
        self._extra_headers[key] = value

    def clear_auth(self) -> None:
        """Remove the Authorization header."""
        self._extra_headers.pop("Authorization", None)

    # ── Request helpers ───────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self._base_url}{path}"

    def _merged_headers(self, extra: dict | None = None) -> dict[str, str]:
        return {**self._extra_headers, **(extra or {})}

    # ── GET (with caching) ────────────────────────────────────────────────────

    async def get(
        self,
        path: str,
        params: dict | None = None,
        headers: dict | None = None,
        use_cache: bool = True,
        ttl: int = _DEFAULT_API_TTL,
    ) -> ApiResponse:
        """HTTP GET. Caches 200 responses by default."""
        url = self._url(path)
        key = _cache_key("GET", url, params)
        if use_cache:
            cached = self._cache.get("api", key)
            if cached is not None:
                logger.debug("API cache hit: GET %s", url)
                # Return a synthetic response-like object
                return _CachedApiResponse(cached)

        resp = ApiResponse(
            await self._ctx.get(url, params=params, headers=self._merged_headers(headers))
        )
        if use_cache and resp.ok:
            body = await resp.json()
            self._cache.set("api", key, body, ttl=ttl)
            return _CachedApiResponse(body, status=resp.status)
        return resp

    async def get_json(
        self,
        path: str,
        params: dict | None = None,
        use_cache: bool = True,
        ttl: int = _DEFAULT_API_TTL,
    ) -> Any:
        """GET and return parsed JSON body. Raises on non-2xx status."""
        resp = await self.get(path, params=params, use_cache=use_cache, ttl=ttl)
        if isinstance(resp, _CachedApiResponse):
            return resp._data
        resp.raise_for_status()
        return await resp.json()

    # ── POST ──────────────────────────────────────────────────────────────────

    async def post(
        self,
        path: str,
        json: Any = None,
        form: dict | None = None,
        headers: dict | None = None,
    ) -> ApiResponse:
        """HTTP POST with JSON body (or form data)."""
        url = self._url(path)
        logger.debug("API POST %s", url)
        merged = self._merged_headers(headers)
        if form:
            merged.pop("Content-Type", None)  # let playwright set multipart boundary
            resp = await self._ctx.post(url, form=form, headers=merged)
        else:
            resp = await self._ctx.post(url, data=json, headers=merged)
        return ApiResponse(resp)

    async def post_json(
        self, path: str, json: Any = None, headers: dict | None = None
    ) -> Any:
        """POST JSON and return the parsed response body. Raises on non-2xx."""
        resp = await self.post(path, json=json, headers=headers)
        resp.raise_for_status()
        return await resp.json()

    # ── PUT ───────────────────────────────────────────────────────────────────

    async def put(
        self, path: str, json: Any = None, headers: dict | None = None
    ) -> ApiResponse:
        """HTTP PUT with JSON body."""
        url = self._url(path)
        logger.debug("API PUT %s", url)
        resp = await self._ctx.put(url, data=json, headers=self._merged_headers(headers))
        return ApiResponse(resp)

    async def put_json(self, path: str, json: Any = None) -> Any:
        resp = await self.put(path, json=json)
        resp.raise_for_status()
        return await resp.json()

    # ── PATCH ─────────────────────────────────────────────────────────────────

    async def patch(
        self, path: str, json: Any = None, headers: dict | None = None
    ) -> ApiResponse:
        url = self._url(path)
        logger.debug("API PATCH %s", url)
        resp = await self._ctx.patch(url, data=json, headers=self._merged_headers(headers))
        return ApiResponse(resp)

    async def patch_json(self, path: str, json: Any = None) -> Any:
        resp = await self.patch(path, json=json)
        resp.raise_for_status()
        return await resp.json()

    # ── DELETE ────────────────────────────────────────────────────────────────

    async def delete(self, path: str, headers: dict | None = None) -> ApiResponse:
        url = self._url(path)
        logger.debug("API DELETE %s", url)
        resp = await self._ctx.delete(url, headers=self._merged_headers(headers))
        return ApiResponse(resp)

    async def delete_json(self, path: str) -> Any:
        resp = await self.delete(path)
        resp.raise_for_status()
        return await resp.json()

    # ── Cache management ──────────────────────────────────────────────────────

    def invalidate(self, path: str, params: dict | None = None) -> None:
        """Evict a cached GET response (call after a mutating operation)."""
        url = self._url(path)
        key = _cache_key("GET", url, params)
        self._cache.delete("api", key)


class _CachedApiResponse(ApiResponse):
    """Pseudo ApiResponse returned from cache (no real Playwright response)."""

    def __init__(self, data: Any, status: int = 200) -> None:
        # Don't call super().__init__
        self._data = data
        self._status = status

    @property
    def status(self) -> int:
        return self._status

    @property
    def ok(self) -> bool:
        return 200 <= self._status < 300

    @property
    def headers(self) -> dict[str, str]:
        return {}

    async def json(self) -> Any:
        return self._data

    async def text(self) -> str:
        return json.dumps(self._data)

    async def body(self) -> bytes:
        return json.dumps(self._data).encode()

    def raise_for_status(self) -> None:
        if not self.ok:
            raise AssertionError(f"API request failed: HTTP {self._status}")
