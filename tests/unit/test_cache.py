"""Tests for L1, L2, and CacheManager."""

import time
import pytest
from pathlib import Path

from oapw.cache.l1_memory import L1Cache
from oapw.cache.l2_disk import L2Cache
from oapw.cache.manager import CacheManager


# ── L1 ────────────────────────────────────────────────────────────────────────

class TestL1Cache:
    def test_basic_set_get(self):
        c = L1Cache(max_size=10)
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_miss_returns_none(self):
        c = L1Cache(max_size=10)
        assert c.get("missing") is None

    def test_ttl_expiry(self):
        c = L1Cache(max_size=10)
        c.set("k", "v", ttl=1)
        assert c.get("k") == "v"
        time.sleep(1.1)
        assert c.get("k") is None

    def test_lru_eviction(self):
        c = L1Cache(max_size=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)  # evicts "a"
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_stats(self):
        c = L1Cache(max_size=10)
        c.set("x", 42)
        c.get("x")    # hit
        c.get("y")    # miss
        s = c.stats
        assert s["hits"] == 1
        assert s["misses"] == 1

    def test_delete(self):
        c = L1Cache(max_size=10)
        c.set("k", "v")
        c.delete("k")
        assert c.get("k") is None


# ── L2 ────────────────────────────────────────────────────────────────────────

class TestL2Cache:
    def test_basic_set_get(self, tmp_path):
        c = L2Cache(tmp_path / "c.db")
        c.set("k", {"val": 1})
        assert c.get("k") == {"val": 1}

    def test_miss_returns_none(self, tmp_path):
        c = L2Cache(tmp_path / "c.db")
        assert c.get("missing") is None

    def test_ttl_expiry(self, tmp_path):
        c = L2Cache(tmp_path / "c.db")
        c.set("k", "v", ttl=1)
        assert c.get("k") == "v"
        time.sleep(1.1)
        assert c.get("k") is None

    def test_prune(self, tmp_path):
        c = L2Cache(tmp_path / "c.db")
        c.set("a", 1, ttl=1)
        c.set("b", 2)          # no expiry
        time.sleep(1.1)
        removed = c.prune()
        assert removed == 1
        assert c.size() == 1

    def test_overwrite(self, tmp_path):
        c = L2Cache(tmp_path / "c.db")
        c.set("k", "old")
        c.set("k", "new")
        assert c.get("k") == "new"

    def test_clear(self, tmp_path):
        c = L2Cache(tmp_path / "c.db")
        c.set("k", "v")
        c.clear()
        assert c.size() == 0


# ── CacheManager ─────────────────────────────────────────────────────────────

class TestCacheManager:
    def _manager(self, tmp_path: Path) -> CacheManager:
        from oapw.core.config import OapwConfig
        cfg = OapwConfig(data_dir=tmp_path / "oapw")
        return CacheManager(data_dir=cfg.cache_dir)

    def test_read_through(self, tmp_path):
        m = self._manager(tmp_path)
        m.set("llm", "hash123", {"response": "hello"})
        # Bust L1 by creating fresh manager pointing at same db
        m2 = CacheManager(data_dir=(tmp_path / "oapw" / "cache"))
        val = m2.get("llm", "hash123")
        assert val == {"response": "hello"}

    def test_miss(self, tmp_path):
        m = self._manager(tmp_path)
        assert m.get("llm", "nope") is None

    def test_delete(self, tmp_path):
        m = self._manager(tmp_path)
        m.set("locator", "k", "css=button")
        m.delete("locator", "k")
        assert m.get("locator", "k") is None

    def test_stats_keys(self, tmp_path):
        m = self._manager(tmp_path)
        s = m.stats()
        assert "l1" in s and "l2" in s
