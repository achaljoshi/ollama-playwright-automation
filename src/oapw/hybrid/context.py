"""HybridContext — combined AiPage + ApiClient for hybrid API+UI tests.

In hybrid tests, some actions are done through the browser (UI assertions,
user-journey flows) and others through the API (test data setup, state
verification, authentication bypassing slow UI login).

The key advantage of HybridContext is that the ApiClient is created from
the *same* BrowserContext as the page. This means:
  - Cookies set by API login are immediately available in the browser
  - Browser cookies (e.g. from UI login) are visible to API calls
  - No manual cookie copying required

Usage:
    async with managed_browser() as mgr:
        async with mgr.new_context() as ctx:
            page = await ctx.new_page()
            hybrid = await HybridContext.from_context(ctx, page)

            # Fast API login (no slow UI form)
            token = await hybrid.login_via_api(
                "/api/auth/login",
                email="admin@example.com",
                password="secret",
            )

            # Browser is now logged in too — navigate directly to protected page
            await hybrid.page.goto("/admin/dashboard")

            # Use natural language on the page
            await hybrid.page.ai("Click the Users tab")

            # Verify state via API (faster than scraping the page)
            await hybrid.verify_via_api(
                "/api/users/count", {"total": 42}
            )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from oapw.hybrid.api_client import ApiClient
from oapw.core.config import get_config

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page
    from oapw.core.ai_page import AiPage

logger = logging.getLogger(__name__)


@dataclass
class HybridContext:
    """Pairs an AiPage with a cookie-sharing ApiClient.

    Attributes
    ----------
    page : AiPage
        The AI-enhanced browser page.
    api : ApiClient
        HTTP client that shares cookies with the browser context.
    """

    page: "AiPage"
    api: ApiClient

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    async def from_context(
        cls,
        browser_context: "BrowserContext",
        page: "Page",
        base_url: str = "",
    ) -> "HybridContext":
        """Create a HybridContext from an existing BrowserContext + Page.

        The ApiClient is wired to ``browser_context.request`` so it shares
        the browser's cookie jar automatically.
        """
        from oapw.core.ai_page import AiPage

        cfg = get_config()
        api_base = base_url or cfg.app_api_base_url or cfg.app_base_url
        api = ApiClient(
            request_context=browser_context.request,
            base_url=api_base,
        )
        return cls(page=AiPage(page), api=api)

    # ── Authentication helpers ────────────────────────────────────────────────

    async def login_via_api(
        self,
        login_path: str,
        email: str,
        password: str,
        *,
        email_field: str = "email",
        password_field: str = "password",
        token_field: str = "token",
    ) -> str | None:
        """POST credentials to ``login_path``, extract token, inject as Bearer header.

        Because the ApiClient shares cookies with the browser context, any
        session cookie set by the server is automatically available in the
        browser page — no manual injection required.

        Returns the token string if one was present in the response body,
        else None (cookie-based auth doesn't need a token).
        """
        body = {email_field: email, password_field: password}
        logger.debug("HybridContext.login_via_api: POST %s", login_path)
        resp = await self.api.post(login_path, json=body)

        token: str | None = None
        if resp.ok:
            try:
                data = await resp.json()
                token = data.get(token_field) if isinstance(data, dict) else None
                if token:
                    self.api.set_bearer_token(token)
                    logger.debug("Bearer token injected from login response")
            except Exception:
                pass  # Cookie-based auth — no token in body
        else:
            logger.warning("login_via_api: non-2xx response %d", resp.status)
        return token

    # ── State helpers ─────────────────────────────────────────────────────────

    async def setup_resource(self, path: str, data: dict) -> dict:
        """POST to ``path`` to create a test resource, return the response body.

        Useful for setting up prerequisite state before a UI test without
        navigating through creation forms.

        Example:
            user = await hybrid.setup_resource("/api/users", {
                "name": "Alice", "email": "alice@example.com", "role": "admin"
            })
            user_id = user["id"]
        """
        return await self.api.post_json(path, json=data)

    async def teardown_resource(self, path: str) -> None:
        """DELETE ``path`` to clean up test state after a test."""
        await self.api.delete(path)

    async def verify_via_api(
        self, path: str, expected: dict[str, Any], use_cache: bool = False
    ) -> None:
        """Assert that the API response at ``path`` contains ``expected`` key-values.

        ``use_cache`` is False by default so post-mutation state is always fresh.

        Raises ``AssertionError`` if any key doesn't match.
        """
        actual = await self.api.get_json(path, use_cache=use_cache)
        mismatches = []
        for key, value in expected.items():
            if actual.get(key) != value:
                mismatches.append(
                    f"  {key}: expected={value!r}, actual={actual.get(key)!r}"
                )
        if mismatches:
            raise AssertionError(
                f"API state mismatch at {path}:\n" + "\n".join(mismatches)
            )

    async def get_resource(self, path: str, use_cache: bool = False) -> Any:
        """Fetch a resource from the API (short-cut to ``api.get_json``)."""
        return await self.api.get_json(path, use_cache=use_cache)

    # ── Network interception ──────────────────────────────────────────────────

    async def capture_api_response(
        self, url_pattern: str, action_fn
    ) -> Any:
        """Intercept the first matching network response while running ``action_fn``.

        Useful for capturing tokens or IDs that only appear in network traffic.

        Example:
            login_resp = await hybrid.capture_api_response(
                "**/api/auth/login",
                lambda: hybrid.page.ai("Click the Sign In button"),
            )
            token = login_resp["token"]
        """
        captured: list[Any] = []

        async def _handle(response):
            if url_pattern.replace("**", "") in response.url:
                try:
                    captured.append(await response.json())
                except Exception:
                    captured.append(None)

        page = self.page._page  # type: ignore[attr-defined]
        page.on("response", _handle)
        try:
            await action_fn()
        finally:
            page.remove_listener("response", _handle)

        return captured[0] if captured else None
