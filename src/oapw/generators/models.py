"""Data models for the test generator layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class GeneratedTest:
    """A complete pytest test file produced by a generator.

    Attributes
    ----------
    test_name:
        Suggested file name without extension, e.g. ``test_auth_login``.
    code:
        Complete, runnable pytest Python source.
    summary:
        One-line human description of what is being tested.
    source_type:
        Where the generation originated: ``"jira"``, ``"user_story"``, or ``"smoke"``.
    ticket_key:
        Jira ticket key if ``source_type == "jira"``, else empty.
    jira_ids:
        Jira keys referenced by this test (used for traceability).
    confluence_ids:
        Confluence page IDs referenced (used for traceability).
    model:
        Ollama model used for generation.
    generated_at:
        ISO 8601 UTC timestamp.
    out_path:
        Absolute path to the written file, or None if not written to disk.
    """

    test_name: str
    code: str
    summary: str
    source_type: str                  # "jira" | "user_story" | "smoke"
    ticket_key: str = ""
    jira_ids: list[str] = field(default_factory=list)
    confluence_ids: list[str] = field(default_factory=list)
    model: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    out_path: Path | None = None


@dataclass
class MutatedTest:
    """An edge-case variant of a ``GeneratedTest``.

    Attributes
    ----------
    parent:
        The ``GeneratedTest`` this mutation was derived from.
    mutation_type:
        Category of mutation applied, e.g. ``"empty_input"``, ``"boundary"``,
        ``"special_chars"``, ``"max_length"``, ``"invalid_format"``.
    description:
        Human-readable explanation of what this mutation tests.
    code:
        Complete pytest source for the mutation.
    """

    parent: GeneratedTest
    mutation_type: str
    description: str
    code: str

    @property
    def test_name(self) -> str:
        return f"{self.parent.test_name}_{self.mutation_type}"


@dataclass
class GenerationResult:
    """Result wrapper returned by generator public methods."""

    test: GeneratedTest
    written: bool = False
    path: Path | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
