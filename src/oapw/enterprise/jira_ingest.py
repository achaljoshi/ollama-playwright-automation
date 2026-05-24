"""Jira ingestion pipeline — JQL → fetch → embed → upsert into knowledge store."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from oapw.enterprise.atlassian_client import AtlassianClient, JiraTicket, get_atlassian_client
from oapw.knowledge.vector_store import KnowledgeStore, get_knowledge_store

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    total: int = 0
    added: int = 0
    skipped: int = 0
    errors: int = 0


class JiraIngestor:
    """Fetches Jira tickets and upserts them into the knowledge store."""

    def __init__(
        self,
        client: AtlassianClient | None = None,
        store: KnowledgeStore | None = None,
    ) -> None:
        self._client = client or get_atlassian_client()
        self._store = store or get_knowledge_store()

    def _ticket_to_doc(self, ticket: JiraTicket) -> dict:
        text_parts = [
            f"JIRA {ticket.key}: {ticket.summary}",
            f"Type: {ticket.issue_type}  Status: {ticket.status}  Priority: {ticket.priority}",
        ]
        if ticket.components:
            text_parts.append(f"Components: {', '.join(ticket.components)}")
        if ticket.labels:
            text_parts.append(f"Labels: {', '.join(ticket.labels)}")
        if ticket.description:
            text_parts.append(f"\nDescription:\n{ticket.description[:2000]}")
        if ticket.acceptance_criteria:
            text_parts.append(f"\nAcceptance Criteria:\n{ticket.acceptance_criteria}")
        return {
            "id": f"jira:{ticket.key}",
            "text": "\n".join(text_parts),
            "metadata": {
                "source": "jira",
                "jira_id": ticket.key,
                "jira_key": ticket.key,
                "title": f"JIRA {ticket.key}: {ticket.summary}",
                "url": ticket.url,
                "status": ticket.status,
                "issue_type": ticket.issue_type,
                "components": ",".join(ticket.components),
                "labels": ",".join(ticket.labels),
            },
        }

    async def ingest_ticket(self, issue_key: str) -> bool:
        """Fetch and ingest a single Jira ticket. Returns True if successful."""
        try:
            ticket = await self._client.get_jira_issue(issue_key)
            doc = self._ticket_to_doc(ticket)
            await self._store.add(doc["id"], doc["text"], doc["metadata"])
            logger.info("Ingested Jira ticket %s", issue_key)
            return True
        except Exception as exc:
            logger.warning("Failed to ingest %s: %s", issue_key, exc)
            return False

    async def ingest_query(
        self,
        jql: str,
        max_results: int = 0,
        progress_cb=None,
    ) -> IngestResult:
        """Fetch all tickets matching a JQL query and ingest them.

        Streams results page-by-page so large result sets (thousands of tickets)
        are processed incrementally without holding everything in memory.

        Args:
            jql:         JQL query string.
            max_results: Cap on total tickets to ingest. 0 (default) = no cap.
            progress_cb: Optional callable(ingested, total_so_far) for progress
                         reporting (called after each page is upserted).
        """
        result = IngestResult()
        try:
            async for page in self._client._iter_jira_pages(jql, page_size=100):
                if not page:
                    continue
                docs = [self._ticket_to_doc(self._client._parse_jira_issue(issue)) for issue in page]
                try:
                    await self._store.add_batch(docs)
                    result.added += len(docs)
                except Exception as batch_exc:
                    logger.warning("Batch ingest failed, falling back: %s", batch_exc)
                    for doc in docs:
                        try:
                            await self._store.add(doc["id"], doc["text"], doc["metadata"])
                            result.added += 1
                        except Exception:
                            result.errors += 1
                result.total += len(page)
                if progress_cb:
                    progress_cb(result.added, result.total)
                if max_results > 0 and result.total >= max_results:
                    break
        except Exception as exc:
            logger.error("JQL search failed: %s", exc)
            result.errors += 1
        return result
