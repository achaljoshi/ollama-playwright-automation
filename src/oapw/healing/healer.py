"""Healer orchestrator — coordinates healing strategies on locator failure.

Called by LocatorResolver when a cached locator is no longer valid.
Tries strategies cheapest-first: fingerprint → role/text variant → LLM.
Records every attempt to HealingRecorder for metrics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oapw.core.config import get_config
from oapw.core.ollama_client import OllamaClient, get_ollama_client
from oapw.healing.fingerprint import ElementFingerprint
from oapw.healing.recorder import HealingEvent, HealingRecorder
from oapw.healing.strategies import (
    FingerprintStrategy,
    LLMHealStrategy,
    RoleTextStrategy,
)

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class Healer:
    def __init__(
        self,
        ollama: OllamaClient | None = None,
        model: str | None = None,
        recorder: HealingRecorder | None = None,
    ) -> None:
        self._model = model or get_config().ollama_default_model
        ollama = ollama or get_ollama_client()
        self._fp_strategy = FingerprintStrategy()
        self._rt_strategy = RoleTextStrategy()
        self._llm_strategy = LLMHealStrategy(ollama=ollama, model=self._model)
        self._recorder = recorder or HealingRecorder()

    async def heal(
        self,
        intent: str,
        original_locator: str,
        target_fp: ElementFingerprint,
        page: "Page",
    ) -> "Locator | None":
        """Attempt to find an element whose locator has gone stale.

        Returns a verified Locator if healing succeeds, else None.
        """
        url = page.url
        winner: "Locator | None" = None
        winning_strategy = "none"
        winning_confidence = 0.0
        winning_reasoning = ""

        # Strategy 1: fingerprint similarity
        attempt = await self._fp_strategy.attempt(intent, target_fp, page)
        if attempt.locator:
            winner = attempt.locator
            winning_strategy = attempt.strategy
            winning_confidence = attempt.confidence
            winning_reasoning = attempt.reasoning
        else:
            # Strategy 2: role + text variants
            attempt = await self._rt_strategy.attempt(intent, target_fp, page)
            if attempt.locator:
                winner = attempt.locator
                winning_strategy = attempt.strategy
                winning_confidence = attempt.confidence
                winning_reasoning = attempt.reasoning
            else:
                # Strategy 3: LLM (cached)
                attempt = await self._llm_strategy.attempt(
                    intent, original_locator, target_fp, page
                )
                if attempt.locator:
                    winner = attempt.locator
                    winning_strategy = attempt.strategy
                    winning_confidence = attempt.confidence
                    winning_reasoning = attempt.reasoning

        self._recorder.record(
            HealingEvent(
                intent=intent,
                page_url=url,
                original_locator=original_locator,
                healed_locator=str(winner) if winner else None,
                strategy=winning_strategy,
                success=winner is not None,
                confidence=winning_confidence,
                reasoning=winning_reasoning,
            )
        )
        return winner

    def stats(self) -> dict:
        return self._recorder.stats()
