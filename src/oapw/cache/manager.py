"""CacheManager — unified L1→L2 read-through / write-through interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oapw.cache.l1_memory import L1Cache
from oapw.cache.l2_disk import L2Cache
from oapw.core.config import get_config


class CacheManager:
    """
    Read order: L1 (memory) → L2 (SQLite).
    Write order: L1 + L2 simultaneously.

    Callers work with named buckets so TTL policy is centralised here.
    """

    # Bucket → default TTL in seconds (None = no expiry)
    _BUCKET_TTL: dict[str, int | None] = {
        "llm": None,          # caller supplies TTL from config
        "locator": None,
        "embedding": None,
        "plan": None,
        "jira": None,
        "confluence": None,
        "negative": 5 * 60,  # 5 min — stops retry storms
    }

    def __init__(self, data_dir: Path | None = None) -> None:
        cfg = get_config()
        root = (data_dir or cfg.cache_dir)
        self._l1 = L1Cache(max_size=cfg.cache_l1_max_size)
        self._l2 = L2Cache(db_path=root / "cache.db")

    # ── Core ops ──────────────────────────────────────────────────────────────

    def get(self, bucket: str, key: str) -> Any | None:
        full_key = f"{bucket}:{key}"
        v = self._l1.get(full_key)
        if v is not None:
            return v
        v = self._l2.get(full_key)
        if v is not None:
            # Warm L1 (no TTL — will naturally expire via LRU eviction)
            self._l1.set(full_key, v)
        return v

    def set(self, bucket: str, key: str, value: Any, ttl: int | None = None) -> None:
        full_key = f"{bucket}:{key}"
        effective_ttl = ttl if ttl is not None else self._BUCKET_TTL.get(bucket)
        self._l1.set(full_key, value, ttl=effective_ttl)
        self._l2.set(full_key, value, ttl=effective_ttl)

    def delete(self, bucket: str, key: str) -> None:
        full_key = f"{bucket}:{key}"
        self._l1.delete(full_key)
        self._l2.delete(full_key)

    # ── Convenience wrappers with config-driven TTLs ──────────────────────────

    def get_llm(self, key: str) -> Any | None:
        return self.get("llm", key)

    def set_llm(self, key: str, value: Any) -> None:
        cfg = get_config()
        self.set("llm", key, value, ttl=cfg.cache_l2_ttl_llm)

    def get_locator(self, key: str) -> Any | None:
        return self.get("locator", key)

    def set_locator(self, key: str, value: Any) -> None:
        cfg = get_config()
        self.set("locator", key, value, ttl=cfg.cache_l2_ttl_locator)

    def get_plan(self, key: str) -> Any | None:
        return self.get("plan", key)

    def set_plan(self, key: str, value: Any) -> None:
        cfg = get_config()
        self.set("plan", key, value, ttl=cfg.cache_l2_ttl_plan)

    def get_embedding(self, key: str) -> Any | None:
        return self.get("embedding", key)

    def set_embedding(self, key: str, value: Any) -> None:
        self.set("embedding", key, value, ttl=None)  # embeddings never expire

    def get_jira(self, key: str) -> Any | None:
        return self.get("jira", key)

    def set_jira(self, key: str, value: Any) -> None:
        self.set("jira", key, value, ttl=24 * 3600)  # 1 day

    def get_confluence(self, key: str) -> Any | None:
        return self.get("confluence", key)

    def set_confluence(self, key: str, value: Any) -> None:
        self.set("confluence", key, value, ttl=24 * 3600)  # 1 day

    # ── Maintenance ───────────────────────────────────────────────────────────

    def prune(self) -> int:
        return self._l2.prune()

    def clear_all(self) -> None:
        self._l1.clear()
        self._l2.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "l1": self._l1.stats,
            "l2": self._l2.stats,
        }


_manager: CacheManager | None = None


def get_cache() -> CacheManager:
    global _manager
    if _manager is None:
        _manager = CacheManager()
    return _manager


def reset_cache() -> None:
    global _manager
    _manager = None
