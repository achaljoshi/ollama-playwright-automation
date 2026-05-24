"""Tests for the knowledge layer — embeddings, vector store, RAG retriever.

ChromaDB is mocked so these run without it installed.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from oapw.knowledge.embeddings import EmbeddingService, _EMBED_MODEL
from oapw.knowledge.rag import KnowledgeSnippet, RAGRetriever
from oapw.knowledge.vector_store import SearchResult


# ── EmbeddingService ──────────────────────────────────────────────────────────

class TestEmbeddingService:
    def _make_svc(self, vector=None):
        """Return an EmbeddingService with a mocked Ollama client and a fresh cache."""
        from oapw.cache.manager import CacheManager
        from pathlib import Path
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        cache = CacheManager(data_dir=tmp)
        ollama = MagicMock()
        ollama.embed = AsyncMock(return_value=vector or [0.1, 0.2, 0.3])
        return EmbeddingService(ollama=ollama, cache=cache), ollama, cache

    @pytest.mark.asyncio
    async def test_embed_calls_ollama(self):
        svc, ollama, _ = self._make_svc()
        result = await svc.embed("hello world")
        ollama.embed.assert_awaited_once_with("hello world", model=_EMBED_MODEL)
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_cache_hit_skips_ollama(self):
        svc, ollama, cache = self._make_svc()
        await svc.embed("hello world")        # cold
        await svc.embed("hello world")        # warm
        assert ollama.embed.await_count == 1  # only called once

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        svc, ollama, _ = self._make_svc()
        vectors = [[float(i)] for i in range(3)]
        ollama.embed = AsyncMock(side_effect=vectors)
        result = await svc.embed_batch(["a", "b", "c"])
        assert len(result) == 3

    def test_cache_key_deterministic(self):
        svc, _, _ = self._make_svc()
        assert svc._cache_key("same text") == svc._cache_key("same text")

    def test_cache_key_differs_for_different_text(self):
        svc, _, _ = self._make_svc()
        assert svc._cache_key("text A") != svc._cache_key("text B")


# ── SearchResult ──────────────────────────────────────────────────────────────

class TestSearchResult:
    def test_score_is_complement_of_distance(self):
        r = SearchResult(id="x", text="t", metadata={}, distance=0.3)
        assert abs(r.score - 0.7) < 1e-6

    def test_score_clamped_above_zero(self):
        r = SearchResult(id="x", text="t", metadata={}, distance=1.5)
        assert r.score == 0.0

    def test_score_clamped_at_one(self):
        r = SearchResult(id="x", text="t", metadata={}, distance=0.0)
        assert r.score == 1.0


# ── KnowledgeStore (mocked ChromaDB) ─────────────────────────────────────────

def _make_mock_store(search_results=None):
    """Return a KnowledgeStore whose ChromaDB is replaced by mocks."""
    from oapw.knowledge.vector_store import KnowledgeStore
    from oapw.knowledge.embeddings import EmbeddingService
    from unittest.mock import MagicMock, AsyncMock

    embed_svc = MagicMock()
    embed_svc.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    embed_svc.embed_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    col = MagicMock()
    col.count.return_value = len(search_results or [])

    if search_results:
        col.query.return_value = {
            "ids": [[r["id"] for r in search_results]],
            "documents": [[r["text"] for r in search_results]],
            "metadatas": [[r.get("metadata", {}) for r in search_results]],
            "distances": [[r.get("distance", 0.1) for r in search_results]],
        }
    else:
        col.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    store = KnowledgeStore(data_dir=None, embedding_service=embed_svc)
    store._collection = col
    return store


class TestKnowledgeStore:
    @pytest.mark.asyncio
    async def test_add_upserts(self):
        store = _make_mock_store()
        await store.add("doc1", "some text", {"source": "jira"})
        store._collection.upsert.assert_called_once()
        call_kwargs = store._collection.upsert.call_args[1]
        assert call_kwargs["ids"] == ["doc1"]

    @pytest.mark.asyncio
    async def test_add_batch_skips_empty(self):
        store = _make_mock_store()
        await store.add_batch([])
        store._collection.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        fake = [{"id": "jira:PROJ-1", "text": "ticket text", "metadata": {"source": "jira"}, "distance": 0.05}]
        store = _make_mock_store(search_results=fake)
        results = await store.search("login feature")
        assert len(results) == 1
        assert results[0].id == "jira:PROJ-1"
        assert results[0].score > 0.9

    @pytest.mark.asyncio
    async def test_search_empty_store(self):
        store = _make_mock_store()
        results = await store.search("anything")
        assert results == []

    def test_chromadb_not_installed_raises(self):
        from oapw.knowledge.vector_store import KnowledgeStore
        store = KnowledgeStore(data_dir=None)
        with patch("builtins.__import__", side_effect=ImportError("no module named chromadb")):
            with pytest.raises(RuntimeError, match="chromadb is not installed"):
                store._get_client()

    def test_exists_true(self):
        store = _make_mock_store()
        store._collection.get.return_value = {"ids": ["doc1"]}
        assert store.exists("doc1") is True

    def test_exists_false(self):
        store = _make_mock_store()
        store._collection.get.return_value = {"ids": []}
        assert store.exists("other") is False


# ── RAGRetriever ──────────────────────────────────────────────────────────────

class TestRAGRetriever:
    def _make_retriever(self, snippets=None):
        from oapw.knowledge.vector_store import KnowledgeStore, SearchResult
        store = MagicMock(spec=KnowledgeStore)
        store.search = AsyncMock(return_value=snippets or [])
        return RAGRetriever(store=store)

    @pytest.mark.asyncio
    async def test_retrieve_filters_below_min_score(self):
        low = SearchResult(id="x", text="t", metadata={"source": "jira", "jira_id": "X", "title": "X", "url": ""}, distance=0.85)
        retriever = self._make_retriever([low])
        results = await retriever.retrieve("query", min_score=0.3)
        assert results == []  # distance 0.85 → score 0.15

    @pytest.mark.asyncio
    async def test_retrieve_boosts_linked_jira(self):
        base = SearchResult(id="j:A", text="t", metadata={"source": "jira", "jira_id": "PROJ-1", "title": "T", "url": ""}, distance=0.3)
        retriever = self._make_retriever([base])
        results = await retriever.retrieve("q", linked_jira=["PROJ-1"], min_score=0.1)
        assert len(results) == 1
        assert results[0].score >= 0.7 * 1.2  # boosted (distance=0.3 → 0.7 × 1.2 = 0.84)

    @pytest.mark.asyncio
    async def test_retrieve_returns_top_k(self):
        hits = [
            SearchResult(id=f"d{i}", text=f"t{i}", metadata={"source": "jira", "jira_id": str(i), "title": str(i), "url": ""}, distance=float(i) * 0.05)
            for i in range(6)
        ]
        retriever = self._make_retriever(hits)
        results = await retriever.retrieve("q", top_k=3, min_score=0.0)
        assert len(results) == 3

    def test_format_context_empty(self):
        retriever = RAGRetriever(store=MagicMock())
        assert retriever.format_context([]) == ""

    def test_format_context_includes_title_and_source(self):
        s = KnowledgeSnippet(id="x", text="Some page content", source="confluence", title="Auth Flows", url="https://example.com", score=0.9, metadata={})
        retriever = RAGRetriever(store=MagicMock())
        ctx = retriever.format_context([s])
        assert "Auth Flows" in ctx
        assert "CONFLUENCE" in ctx
        assert "0.90" in ctx
