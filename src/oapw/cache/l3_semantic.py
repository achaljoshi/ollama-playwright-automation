"""L3 semantic cache — ChromaDB-backed fuzzy lookup for LLM responses.

Answers: "Have I answered a semantically similar prompt before?"
Falls back gracefully when ChromaDB or the embedding service is unavailable.

Threshold is intentionally high (0.92) to avoid false positives — we only
reuse a cached response when the prompt is near-identical in meaning.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_L3_COLLECTION = "oapw_llm_cache"
_DEFAULT_THRESHOLD = 0.92


@dataclass
class L3CacheHit:
    key: str
    value: dict
    score: float


class L3Cache:
    """Semantic LLM response cache backed by ChromaDB."""

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
            try:
                from oapw.knowledge.embeddings import get_embedding_service
                self._embedding_service = get_embedding_service()
            except Exception:
                return None
        return self._embedding_service

    def _get_collection(self):
        if self._collection is None:
            try:
                import chromadb
                if self._data_dir:
                    client = chromadb.PersistentClient(
                        path=str(self._data_dir),
                        settings=chromadb.Settings(anonymized_telemetry=False),
                    )
                else:
                    client = chromadb.EphemeralClient()
                self._client = client
                self._collection = client.get_or_create_collection(
                    name=_L3_COLLECTION,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as exc:
                logger.debug("L3 cache unavailable: %s", exc)
                return None
        return self._collection

    async def get(
        self, prompt: str, threshold: float = _DEFAULT_THRESHOLD
    ) -> L3CacheHit | None:
        """Return a cached response for a semantically similar prompt, if any."""
        svc = self._get_embedding_service()
        if not svc:
            return None
        col = self._get_collection()
        if col is None or col.count() == 0:
            return None
        try:
            emb = await svc.embed(prompt)
            results = col.query(
                query_embeddings=[emb],
                n_results=1,
                include=["documents", "metadatas", "distances"],
            )
            if not results["ids"][0]:
                return None
            dist = results["distances"][0][0]
            score = max(0.0, 1.0 - dist)
            if score < threshold:
                return None
            value = json.loads(results["documents"][0][0])
            return L3CacheHit(key=results["ids"][0][0], value=value, score=score)
        except Exception as exc:
            logger.debug("L3 cache get error: %s", exc)
            return None

    async def set(self, prompt: str, value: dict) -> None:
        """Store a prompt+response pair for future fuzzy lookup."""
        svc = self._get_embedding_service()
        if not svc:
            return
        col = self._get_collection()
        if col is None:
            return
        try:
            key = hashlib.blake2b(prompt.encode(), digest_size=16).hexdigest()
            emb = await svc.embed(prompt)
            col.upsert(
                ids=[key],
                embeddings=[emb],
                documents=[json.dumps(value)],
                metadatas=[{"prompt_preview": prompt[:200]}],
            )
        except Exception as exc:
            logger.debug("L3 cache set error: %s", exc)

    def clear(self) -> None:
        try:
            if self._client:
                self._client.delete_collection(_L3_COLLECTION)
                self._collection = None
        except Exception:
            pass

    def count(self) -> int:
        try:
            col = self._get_collection()
            return col.count() if col else 0
        except Exception:
            return 0


_l3: L3Cache | None = None


def get_l3_cache() -> L3Cache:
    global _l3
    if _l3 is None:
        from oapw.core.config import get_config
        _l3 = L3Cache(data_dir=str(get_config().data_dir / "chroma_l3"))
    return _l3


def reset_l3_cache() -> None:
    global _l3
    _l3 = None
