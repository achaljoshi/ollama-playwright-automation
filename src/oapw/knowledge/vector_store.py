"""ChromaDB vector store — L3 knowledge layer for RAG retrieval.

ChromaDB is optional; a helpful RuntimeError is raised if it is not installed.
Collection: oapw_knowledge (cosine similarity space).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_COLLECTION = "oapw_knowledge"


@dataclass
class SearchResult:
    id: str
    text: str
    metadata: dict[str, Any]
    distance: float
    score: float = field(init=False)

    def __post_init__(self) -> None:
        self.score = max(0.0, min(1.0, 1.0 - self.distance))


class KnowledgeStore:
    """ChromaDB-backed vector store for Jira/Confluence knowledge base."""

    def __init__(
        self,
        data_dir: str | None = None,
        embedding_service=None,
    ) -> None:
        self._data_dir = data_dir
        self._embedding_service = embedding_service
        self._client = None
        self._collection = None

    def _get_embedding_service(self):
        if self._embedding_service is None:
            from oapw.knowledge.embeddings import get_embedding_service
            self._embedding_service = get_embedding_service()
        return self._embedding_service

    def _get_client(self):
        if self._client is None:
            try:
                import chromadb
            except ImportError as exc:
                raise RuntimeError(
                    "chromadb is not installed. Run: poetry add chromadb"
                ) from exc
            if self._data_dir:
                self._client = chromadb.PersistentClient(
                    path=str(self._data_dir),
                    settings=chromadb.Settings(anonymized_telemetry=False),
                )
            else:
                self._client = chromadb.EphemeralClient()
        return self._client

    def _get_collection(self):
        if self._collection is None:
            self._collection = self._get_client().get_or_create_collection(
                name=_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    async def add(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or update a single document."""
        emb = await self._get_embedding_service().embed(text)
        self._get_collection().upsert(
            ids=[doc_id],
            embeddings=[emb],
            documents=[text[:8000]],
            metadatas=[metadata or {}],
        )

    async def add_batch(self, docs: list[dict[str, Any]]) -> None:
        """Add multiple documents in one batch."""
        if not docs:
            return
        embeddings = await self._get_embedding_service().embed_batch(
            [d["text"] for d in docs]
        )
        self._get_collection().upsert(
            ids=[d["id"] for d in docs],
            embeddings=embeddings,
            documents=[d["text"][:8000] for d in docs],
            metadatas=[d.get("metadata", {}) for d in docs],
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        where: dict | None = None,
    ) -> list[SearchResult]:
        """Semantic search — returns top_k most similar documents."""
        emb = await self._get_embedding_service().embed(query)
        col = self._get_collection()
        n = min(top_k, max(1, col.count()))

        kwargs: dict[str, Any] = {"query_embeddings": [emb], "n_results": n}
        if where:
            kwargs["where"] = where

        results = col.query(**kwargs)
        return [
            SearchResult(
                id=results["ids"][0][i],
                text=results["documents"][0][i],
                metadata=results["metadatas"][0][i],
                distance=results["distances"][0][i],
            )
            for i in range(len(results["ids"][0]))
        ]

    def exists(self, doc_id: str) -> bool:
        try:
            return len(self._get_collection().get(ids=[doc_id])["ids"]) > 0
        except Exception:
            return False

    def delete(self, doc_id: str) -> None:
        try:
            self._get_collection().delete(ids=[doc_id])
        except Exception:
            pass

    def count(self) -> int:
        try:
            return self._get_collection().count()
        except Exception:
            return 0

    def clear(self) -> None:
        try:
            self._get_client().delete_collection(_COLLECTION)
            self._collection = None
        except Exception:
            pass


_store: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _store
    if _store is None:
        from oapw.core.config import get_config
        _store = KnowledgeStore(data_dir=str(get_config().data_dir / "chroma"))
    return _store


def reset_knowledge_store() -> None:
    global _store
    _store = None
