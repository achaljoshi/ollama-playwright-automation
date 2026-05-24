"""RAG retriever — semantic search over the knowledge base with provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class KnowledgeSnippet:
    id: str
    text: str
    source: str        # "jira" | "confluence"
    title: str
    url: str
    score: float
    metadata: dict[str, Any]


class RAGRetriever:
    """Retrieves relevant knowledge snippets for LLM context injection."""

    def __init__(self, store=None) -> None:
        self._store = store

    def _get_store(self):
        if self._store is None:
            from oapw.knowledge.vector_store import get_knowledge_store
            self._store = get_knowledge_store()
        return self._store

    async def retrieve(
        self,
        query: str,
        source: str | None = None,
        linked_jira: list[str] | None = None,
        top_k: int = 3,
        min_score: float = 0.3,
    ) -> list[KnowledgeSnippet]:
        """Find the top_k most relevant knowledge snippets for a query."""
        where: dict | None = {"source": source} if source else None
        results = await self._get_store().search(query, top_k=top_k * 2, where=where)

        snippets: list[KnowledgeSnippet] = []
        for r in results:
            if r.score < min_score:
                continue
            score = r.score
            if linked_jira and r.metadata.get("jira_id") in linked_jira:
                score = min(1.0, score * 1.2)
            snippets.append(KnowledgeSnippet(
                id=r.id,
                text=r.text,
                source=r.metadata.get("source", "unknown"),
                title=r.metadata.get("title", r.id),
                url=r.metadata.get("url", ""),
                score=score,
                metadata=r.metadata,
            ))

        snippets.sort(key=lambda s: s.score, reverse=True)
        return snippets[:top_k]

    def format_context(
        self,
        snippets: list[KnowledgeSnippet],
        max_chars: int = 3000,
    ) -> str:
        """Format snippets as a markdown block for LLM context injection."""
        if not snippets:
            return ""
        lines = ["## Relevant context from knowledge base\n"]
        total = 0
        for s in snippets:
            header = f"### {s.title} [{s.source.upper()}] (relevance: {s.score:.2f})"
            if s.url:
                header += f"\nURL: {s.url}"
            body = s.text[:500]
            entry = f"{header}\n{body}\n\n"
            if total + len(entry) > max_chars:
                break
            lines.append(entry)
            total += len(entry)
        return "\n".join(lines)


_retriever: RAGRetriever | None = None


def get_rag_retriever() -> RAGRetriever:
    global _retriever
    if _retriever is None:
        _retriever = RAGRetriever()
    return _retriever


def reset_rag_retriever() -> None:
    global _retriever
    _retriever = None
