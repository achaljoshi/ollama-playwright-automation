"""Embedding service — delegates to Ollama nomic-embed-text with L2 cache backing."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oapw.core.ollama_client import OllamaClient
    from oapw.cache.manager import CacheManager

_EMBED_MODEL = "nomic-embed-text"


class EmbeddingService:
    """Generates and caches text embeddings via Ollama."""

    def __init__(
        self,
        ollama: "OllamaClient | None" = None,
        cache: "CacheManager | None" = None,
    ) -> None:
        self._ollama = ollama
        self._cache = cache

    def _get_ollama(self) -> "OllamaClient":
        if self._ollama is None:
            from oapw.core.ollama_client import get_ollama_client
            self._ollama = get_ollama_client()
        return self._ollama

    def _get_cache(self) -> "CacheManager":
        if self._cache is None:
            from oapw.cache.manager import get_cache
            self._cache = get_cache()
        return self._cache

    def _cache_key(self, text: str) -> str:
        h = hashlib.blake2b(text.encode(), digest_size=16).hexdigest()
        return f"embed:{_EMBED_MODEL}:{h}"

    async def embed(self, text: str) -> list[float]:
        """Return the embedding vector for text, using L2 cache."""
        key = self._cache_key(text)
        cached = self._get_cache().get_llm(key)
        if cached and isinstance(cached, list):
            return cached
        vector = await self._get_ollama().embed(text, model=_EMBED_MODEL)
        self._get_cache().set_llm(key, vector)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts, using per-item cache."""
        results: list[list[float]] = []
        for text in texts:
            results.append(await self.embed(text))
        return results


_svc: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _svc
    if _svc is None:
        _svc = EmbeddingService()
    return _svc


def reset_embedding_service() -> None:
    global _svc
    _svc = None
