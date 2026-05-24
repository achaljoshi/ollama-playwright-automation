"""Central configuration — reads from env / .oapw/config.toml with sane defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OapwConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OAPW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Project ──────────────────────────────────────────────────────────────
    project_name: str = Field(default="default", description="Project name for cache namespacing")
    data_dir: Path = Field(default=Path(".oapw"), description="Runtime data / cache root")

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama server URL")
    ollama_default_model: str = Field(default="qwen2.5:3b", description="Default LLM for all tasks")
    ollama_embed_model: str = Field(default="nomic-embed-text", description="Embedding model")
    ollama_timeout: int = Field(default=120, description="HTTP timeout (s) for Ollama calls")

    # ── Browser ───────────────────────────────────────────────────────────────
    browser_type: Literal["chromium", "firefox", "webkit"] = Field(
        default="chromium", description="Playwright browser engine"
    )
    browser_headless: bool = Field(default=True)
    browser_slow_mo: int = Field(default=0, description="Slow-mo delay in ms (useful for debugging)")
    browser_viewport_width: int = Field(default=1280)
    browser_viewport_height: int = Field(default=720)
    browser_timeout: int = Field(default=30_000, description="Default element timeout in ms")

    # ── Cache ─────────────────────────────────────────────────────────────────
    cache_l1_max_size: int = Field(default=512, description="Max entries in L1 in-memory LRU")
    cache_l2_ttl_llm: int = Field(default=30 * 24 * 3600, description="LLM response TTL in seconds")
    cache_l2_ttl_locator: int = Field(default=7 * 24 * 3600, description="Locator cache TTL in seconds")
    cache_l2_ttl_plan: int = Field(default=24 * 3600, description="Plan cache TTL in seconds")

    # ── Hardware profile ──────────────────────────────────────────────────────
    ram_gb: int = Field(default=8, description="Available RAM (GB) — drives model selection")

    # ── Application under test ────────────────────────────────────────────────
    app_base_url: str = Field(default="http://localhost:3000", description="Base URL of the application under test (used by ApiClient)")
    app_api_base_url: str = Field(default="", description="API base URL if different from app_base_url (e.g. http://localhost:8080/api)")

    # ── Atlassian ─────────────────────────────────────────────────────────────
    atlassian_url: str = Field(default="", description="Atlassian Cloud base URL (e.g. https://company.atlassian.net)")
    atlassian_email: str = Field(default="", description="Atlassian account email for API auth")

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def traces_dir(self) -> Path:
        return self.data_dir / "traces"

    @property
    def traceability_db(self) -> Path:
        return self.data_dir / "traceability.db"

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)


_config: OapwConfig | None = None


def get_config() -> OapwConfig:
    global _config
    if _config is None:
        _config = OapwConfig()
    return _config


def reset_config() -> None:
    """Force re-read on next access — useful in tests."""
    global _config
    _config = None
