"""Tests for L3 semantic cache — graceful degradation when ChromaDB unavailable."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from oapw.cache.l3_semantic import L3Cache


def _make_l3(collection=None, embed_svc=None):
    """Build an L3Cache with injected mocks."""
    svc = embed_svc or MagicMock()
    svc.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    l3 = L3Cache(data_dir=None, embedding_service=svc)
    if collection is not None:
        l3._collection = collection
    return l3


class TestL3CacheUnavailable:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_embedding_service(self):
        l3 = L3Cache(data_dir=None, embedding_service=None)
        # Mock get_embedding_service to raise
        with patch("oapw.cache.l3_semantic.L3Cache._get_embedding_service", return_value=None):
            result = await l3.get("any prompt")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_silently_skips_without_embedding_service(self):
        l3 = L3Cache(data_dir=None, embedding_service=None)
        with patch("oapw.cache.l3_semantic.L3Cache._get_embedding_service", return_value=None):
            await l3.set("prompt", {"key": "value"})  # should not raise

    @pytest.mark.asyncio
    async def test_chromadb_import_error_graceful(self):
        l3 = L3Cache(data_dir=None)
        with patch.dict("sys.modules", {"chromadb": None}):
            col = l3._get_collection()
        assert col is None


class TestL3CacheHit:
    @pytest.mark.asyncio
    async def test_get_returns_hit_above_threshold(self):
        col = MagicMock()
        col.count.return_value = 1
        payload = {"answer": 42}
        col.query.return_value = {
            "ids": [["abc"]],
            "documents": [[json.dumps(payload)]],
            "metadatas": [[{"prompt_preview": "test"}]],
            "distances": [[0.05]],  # score = 0.95
        }
        l3 = _make_l3(collection=col)
        hit = await l3.get("some prompt", threshold=0.9)
        assert hit is not None
        assert hit.value == payload
        assert hit.score > 0.9

    @pytest.mark.asyncio
    async def test_get_returns_none_below_threshold(self):
        col = MagicMock()
        col.count.return_value = 1
        col.query.return_value = {
            "ids": [["abc"]],
            "documents": [[json.dumps({"x": 1})]],
            "metadatas": [[{}]],
            "distances": [[0.3]],  # score = 0.7
        }
        l3 = _make_l3(collection=col)
        hit = await l3.get("some prompt", threshold=0.92)
        assert hit is None

    @pytest.mark.asyncio
    async def test_get_empty_collection_returns_none(self):
        col = MagicMock()
        col.count.return_value = 0
        l3 = _make_l3(collection=col)
        hit = await l3.get("query")
        assert hit is None

    @pytest.mark.asyncio
    async def test_set_upserts_document(self):
        col = MagicMock()
        l3 = _make_l3(collection=col)
        await l3.set("prompt text", {"result": "ok"})
        col.upsert.assert_called_once()
        kwargs = col.upsert.call_args[1]
        assert len(kwargs["ids"]) == 1
        stored = json.loads(kwargs["documents"][0])
        assert stored == {"result": "ok"}

    def test_count_zero_on_empty(self):
        col = MagicMock()
        col.count.return_value = 0
        l3 = _make_l3(collection=col)
        assert l3.count() == 0

    def test_clear_deletes_collection(self):
        client = MagicMock()
        l3 = _make_l3()
        l3._client = client
        l3._collection = MagicMock()
        l3.clear()
        client.delete_collection.assert_called_once()
        assert l3._collection is None
