"""Tests for AtlassianClient — mocked httpx, credential helpers, text extractors."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from oapw.enterprise.atlassian_client import (
    AtlassianClient,
    _html_to_text,
    _adf_to_text,
    _extract_ac,
)


class TestHtmlToText:
    def test_strips_tags(self):
        assert _html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_removes_script(self):
        result = _html_to_text("<script>alert(1)</script>content")
        assert "alert" not in result
        assert "content" in result

    def test_collapses_whitespace(self):
        result = _html_to_text("<p>  spaced  </p>")
        assert "  " not in result


class TestAdfToText:
    def test_simple_paragraph(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Hello ADF"}],
                }
            ],
        }
        result = _adf_to_text(adf)
        assert "Hello ADF" in result

    def test_empty_dict(self):
        assert _adf_to_text({}) == ""

    def test_string_passthrough(self):
        assert "hi" in _adf_to_text("hi")

    def test_nested_content(self):
        adf = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "A"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "B"}]},
            ],
        }
        result = _adf_to_text(adf)
        assert "A" in result and "B" in result


class TestExtractAc:
    def test_extracts_acceptance_criteria_header(self):
        text = "Some description.\nAcceptance Criteria:\n- User can log in\n- User sees dashboard"
        result = _extract_ac(text)
        assert "log in" in result

    def test_extracts_given_when_then(self):
        text = "When the user clicks submit, then the form is saved"
        result = _extract_ac(text)
        assert "submit" in result

    def test_empty_text_returns_empty(self):
        assert _extract_ac("") == ""

    def test_no_ac_returns_empty(self):
        assert _extract_ac("just a normal description with no criteria") == ""

    def test_truncates_at_1500(self):
        text = "Acceptance Criteria: " + "x" * 2000
        result = _extract_ac(text)
        assert len(result) <= 1500


class TestAtlassianClientCredentials:
    def test_no_creds_raises_on_get(self):
        client = AtlassianClient(base_url="", email="", api_token="", cache=MagicMock())
        client._cache.get.return_value = None

        import asyncio
        with pytest.raises(RuntimeError, match="not configured"):
            asyncio.run(client._get("/some/path"))

    def test_save_token_uses_keyring(self):
        with patch("keyring.set_password") as mock_set:
            AtlassianClient.save_token("user@example.com", "secret-token")
            mock_set.assert_called_once_with("oapw:atlassian", "user@example.com", "secret-token")

    def test_load_token_from_keyring(self):
        with patch("keyring.get_password", return_value="loaded-token"):
            client = AtlassianClient(base_url="https://co.atlassian.net", email="u@co.com")
            assert client._api_token == "loaded-token"

    def test_load_token_keyring_unavailable(self):
        with patch("keyring.get_password", side_effect=Exception("no keyring")):
            client = AtlassianClient(base_url="https://co.atlassian.net", email="u@co.com")
            assert client._api_token == ""


class TestAtlassianClientCaching:
    def test_cache_hit_skips_http(self):
        cache = MagicMock()
        cache.get.return_value = {"issues": []}
        client = AtlassianClient(base_url="https://x.atlassian.net", email="e", api_token="t", cache=cache)

        import asyncio
        result = asyncio.run(client._get("/rest/api/3/search", {"jql": "project=X"}))
        assert result == {"issues": []}
        # HTTP client should not have been created
        assert client._http is None
