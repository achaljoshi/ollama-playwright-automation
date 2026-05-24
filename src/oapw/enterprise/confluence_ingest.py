"""Confluence ingestion pipeline — CQL → fetch → weight → embed → upsert."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from oapw.enterprise.atlassian_client import (
    AtlassianClient,
    ConfluencePage,
    get_atlassian_client,
)
from oapw.enterprise.weighting import weight_pages
from oapw.knowledge.vector_store import KnowledgeStore, get_knowledge_store

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    total: int = 0
    added: int = 0
    skipped: int = 0
    errors: int = 0


class ConfluenceIngestor:
    """Fetches Confluence pages and upserts them into the knowledge store."""

    def __init__(
        self,
        client: AtlassianClient | None = None,
        store: KnowledgeStore | None = None,
    ) -> None:
        self._client = client or get_atlassian_client()
        self._store = store or get_knowledge_store()

    def _page_to_doc(self, page: ConfluencePage, weight: float = 1.0) -> dict:
        text = f"# {page.title}\n\n{page.body[:4000]}"
        return {
            "id": f"confluence:{page.id}",
            "text": text,
            "metadata": {
                "source": "confluence",
                "confluence_id": page.id,
                "title": page.title,
                "url": page.url,
                "space_key": page.space_key,
                "version": page.version,
                "last_modified": page.last_modified,
                "author": page.author,
                "labels": ",".join(page.labels),
                "weight": str(round(weight, 3)),
            },
        }

    async def ingest_page(self, page_id: str) -> bool:
        """Fetch and ingest a single Confluence page. Returns True if successful."""
        try:
            page = await self._client.get_confluence_page(page_id)
            doc = self._page_to_doc(page)
            await self._store.add(doc["id"], doc["text"], doc["metadata"])
            logger.info("Ingested Confluence page %s (%s)", page_id, page.title)
            return True
        except Exception as exc:
            logger.warning("Failed to ingest page %s: %s", page_id, exc)
            return False

    async def ingest_query(
        self,
        cql: str,
        max_results: int = 20,
        component: str | None = None,
    ) -> IngestResult:
        """Fetch pages matching CQL, weight them, and ingest into the knowledge store."""
        result = IngestResult()
        try:
            pages = await self._client.search_confluence(cql, max_results=max_results)
            result.total = len(pages)
            weighted = weight_pages(pages, component=component)
            docs = [self._page_to_doc(w.page, weight=w.score) for w in weighted]
            if docs:
                try:
                    await self._store.add_batch(docs)
                    result.added = len(docs)
                except Exception as batch_exc:
                    logger.warning("Batch ingest failed, falling back: %s", batch_exc)
                    for doc in docs:
                        try:
                            await self._store.add(doc["id"], doc["text"], doc["metadata"])
                            result.added += 1
                        except Exception:
                            result.errors += 1
        except Exception as exc:
            logger.error("CQL search failed: %s", exc)
            result.errors += 1
        return result
