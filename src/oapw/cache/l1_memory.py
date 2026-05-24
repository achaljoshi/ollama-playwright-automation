"""L1 in-memory LRU cache — sub-millisecond hot path within a single process."""

from __future__ import annotations

import time
from typing import Any

from cachetools import LRUCache

from oapw.core.config import get_config


class L1Cache:
    def __init__(self, max_size: int | None = None) -> None:
        size = max_size or get_config().cache_l1_max_size
        self._cache: LRUCache = LRUCache(maxsize=size)
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        val = self._cache.get(key)
        if val is None:
            self._misses += 1
            return None
        # Check TTL stored alongside value
        value, expires_at = val
        if expires_at is not None and time.monotonic() > expires_at:
            del self._cache[key]
            self._misses += 1
            return None
        self._hits += 1
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.monotonic() + ttl if ttl is not None else None
        self._cache[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
            "max_size": self._cache.maxsize,
        }
