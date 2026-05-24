"""Atlassian Cloud REST client — Jira + Confluence via httpx.

Credentials:
  OAPW_ATLASSIAN_URL   — your Atlassian Cloud base URL (e.g. https://company.atlassian.net)
  OAPW_ATLASSIAN_EMAIL — your Atlassian account email
  API token stored in OS keyring under key ("oapw:atlassian", email)
  To save: oapw auth atlassian --email you@company.com

Responses cached in L2 (1-day TTL) to stay under rate limits.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class JiraTicket:
    id: str
    key: str
    summary: str
    description: str
    status: str
    issue_type: str
    priority: str
    components: list[str]
    labels: list[str]
    acceptance_criteria: str
    url: str
    linked_confluence: list[str] = field(default_factory=list)


@dataclass
class ConfluencePage:
    id: str
    title: str
    space_key: str
    body: str
    url: str
    version: int
    last_modified: str
    author: str
    labels: list[str] = field(default_factory=list)
    linked_jira: list[str] = field(default_factory=list)


_JIRA_FIELDS = "summary,description,status,issuetype,priority,components,labels"
_CONF_EXPAND = "body.storage,version,metadata.labels,history"
_ATLASSIAN_TTL = 24 * 3600  # 1 day


class AtlassianClient:
    """Async REST client for Atlassian Cloud (Jira + Confluence)."""

    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        cache=None,
    ) -> None:
        from oapw.core.config import get_config
        cfg = get_config()
        self._base_url = (base_url or getattr(cfg, "atlassian_url", "") or "").rstrip("/")
        self._email = email or getattr(cfg, "atlassian_email", "") or ""
        self._api_token = api_token or self._load_token()
        self._cache = cache
        self._http: httpx.AsyncClient | None = None

    def _load_token(self) -> str:
        try:
            import keyring
            return keyring.get_password("oapw:atlassian", self._email or "default") or ""
        except Exception:
            return ""

    @classmethod
    def save_token(cls, email: str, token: str) -> None:
        """Persist an API token to the OS keyring."""
        import keyring
        keyring.set_password("oapw:atlassian", email, token)

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            auth_b64 = base64.b64encode(
                f"{self._email}:{self._api_token}".encode()
            ).decode()
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Basic {auth_b64}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._http

    def _get_cache(self):
        if self._cache is None:
            from oapw.cache.manager import get_cache
            self._cache = get_cache()
        return self._cache

    def _cache_key(self, path: str, params: dict | None = None) -> str:
        raw = f"atlassian:{path}:{params or {}}"
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()

    def _assert_configured(self) -> None:
        if not self._base_url or not self._api_token:
            raise RuntimeError(
                "Atlassian credentials not configured. "
                "Set OAPW_ATLASSIAN_URL and OAPW_ATLASSIAN_EMAIL, then run: "
                "oapw auth atlassian --email you@company.com"
            )

    async def _get(self, path: str, params: dict | None = None) -> Any:
        key = self._cache_key(path, params)
        cached = self._get_cache().get("confluence", key)
        if cached is not None:
            return cached

        self._assert_configured()
        resp = await self._get_http().get(path, params=params)
        resp.raise_for_status()
        data = resp.json()
        self._get_cache().set("confluence", key, data, ttl=_ATLASSIAN_TTL)
        return data

    async def _post(self, path: str, body: dict) -> Any:
        """POST request (not cached — used for search endpoints)."""
        self._assert_configured()
        resp = await self._get_http().post(path, json=body)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ── Jira ─────────────────────────────────────────────────────────────────

    async def get_jira_issue(self, issue_key: str) -> JiraTicket:
        data = await self._get(
            f"/rest/api/3/issue/{issue_key}",
            params={"fields": _JIRA_FIELDS},
        )
        fields = data.get("fields", {})
        desc = _adf_to_text(fields.get("description") or {})
        return JiraTicket(
            id=data["id"],
            key=data["key"],
            summary=fields.get("summary", ""),
            description=desc,
            status=(fields.get("status") or {}).get("name", ""),
            issue_type=(fields.get("issuetype") or {}).get("name", ""),
            priority=(fields.get("priority") or {}).get("name", ""),
            components=[c["name"] for c in (fields.get("components") or [])],
            labels=fields.get("labels") or [],
            acceptance_criteria=_extract_ac(desc),
            url=f"{self._base_url}/browse/{data['key']}",
        )

    async def search_jira(self, jql: str, max_results: int = 50) -> list[JiraTicket]:
        """Search Jira using JQL.

        Tries POST /rest/api/3/search/jql first (Jira Cloud 2024+),
        falls back to POST /rest/api/3/search, then GET /rest/api/3/search.
        """
        fields_list = _JIRA_FIELDS.split(",")
        body = {"jql": jql, "maxResults": max_results, "fields": fields_list}

        data: dict | None = None
        last_error: Exception | None = None

        for endpoint, use_post, payload in [
            ("/rest/api/3/search/jql", True, body),
            ("/rest/api/3/search",     True, body),
            ("/rest/api/3/search",     False, None),
        ]:
            try:
                if use_post:
                    data = await self._post(endpoint, payload)  # type: ignore[arg-type]
                else:
                    data = await self._get(
                        endpoint,
                        params={"jql": jql, "maxResults": max_results, "fields": _JIRA_FIELDS},
                    )
                break
            except Exception as exc:
                last_error = exc
                logger.debug("Jira search via %s failed: %s", endpoint, exc)
                continue

        if data is None:
            raise RuntimeError(f"JQL search failed: {last_error}")

        tickets: list[JiraTicket] = []
        for issue in data.get("issues", []):
            fields = issue.get("fields", {})
            desc = _adf_to_text(fields.get("description") or {})
            tickets.append(JiraTicket(
                id=issue["id"],
                key=issue["key"],
                summary=fields.get("summary", ""),
                description=desc,
                status=(fields.get("status") or {}).get("name", ""),
                issue_type=(fields.get("issuetype") or {}).get("name", ""),
                priority=(fields.get("priority") or {}).get("name", ""),
                components=[c["name"] for c in (fields.get("components") or [])],
                labels=fields.get("labels") or [],
                acceptance_criteria=_extract_ac(desc),
                url=f"{self._base_url}/browse/{issue['key']}",
            ))
        return tickets

    # ── Confluence ────────────────────────────────────────────────────────────

    async def get_confluence_page(self, page_id: str) -> ConfluencePage:
        data = await self._get(
            f"/wiki/rest/api/content/{page_id}",
            params={"expand": _CONF_EXPAND},
        )
        body = _html_to_text(
            (data.get("body", {}).get("storage", {}).get("value") or "")
        )
        history = data.get("history", {}).get("lastUpdated", {})
        return ConfluencePage(
            id=data["id"],
            title=data.get("title", ""),
            space_key=(data.get("space") or {}).get("key", ""),
            body=body,
            url=f"{self._base_url}/wiki{data.get('_links', {}).get('webui', '')}",
            version=(data.get("version") or {}).get("number", 0),
            last_modified=history.get("when", ""),
            author=(history.get("by") or {}).get("displayName", ""),
            labels=[
                lbl["name"]
                for lbl in (
                    data.get("metadata", {})
                    .get("labels", {})
                    .get("results") or []
                )
            ],
        )

    async def search_confluence(
        self, cql: str, max_results: int = 20
    ) -> list[ConfluencePage]:
        data = await self._get(
            "/wiki/rest/api/content/search",
            params={"cql": cql, "limit": max_results, "expand": _CONF_EXPAND},
        )
        pages: list[ConfluencePage] = []
        for item in data.get("results", []):
            body = _html_to_text(
                (item.get("body", {}).get("storage", {}).get("value") or "")
            )
            history = item.get("history", {}).get("lastUpdated", {})
            pages.append(ConfluencePage(
                id=item["id"],
                title=item.get("title", ""),
                space_key=(item.get("space") or {}).get("key", ""),
                body=body,
                url=f"{self._base_url}/wiki{item.get('_links', {}).get('webui', '')}",
                version=(item.get("version") or {}).get("number", 0),
                last_modified=history.get("when", ""),
                author=(history.get("by") or {}).get("displayName", ""),
                labels=[
                    lbl["name"]
                    for lbl in (
                        item.get("metadata", {})
                        .get("labels", {})
                        .get("results") or []
                    )
                ],
            ))
        return pages

    async def find_linked_confluence(self, issue_key: str) -> list[str]:
        """Return Confluence page IDs linked to a Jira issue via remote links."""
        try:
            data = await self._get(f"/rest/api/3/issue/{issue_key}/remotelink")
            page_ids: list[str] = []
            for link in data:
                url = link.get("object", {}).get("url", "")
                m = re.search(r"/pages/(\d+)", url)
                if m:
                    page_ids.append(m.group(1))
            return page_ids
        except Exception:
            return []


# ── Text extraction helpers ───────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    """Strip HTML tags to plain text."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def _adf_to_text(adf: dict | list | str) -> str:
    """Convert Atlassian Document Format JSON to plain text."""
    parts: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            elif "content" in node:
                _walk(node["content"])
                if node.get("type") in ("paragraph", "heading", "listItem", "bulletList"):
                    parts.append("\n")

    _walk(adf)
    return " ".join(p for p in parts if p.strip())


def _extract_ac(text: str) -> str:
    """Extract acceptance criteria section from an issue description."""
    m = re.search(
        r"(acceptance criteria|ac:|given|when|then)(.{0,1500})",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(0).strip()[:1500] if m else ""


_client: AtlassianClient | None = None


def get_atlassian_client() -> AtlassianClient:
    global _client
    if _client is None:
        _client = AtlassianClient()
    return _client


def reset_atlassian_client() -> None:
    global _client
    _client = None
