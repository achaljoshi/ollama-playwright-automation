"""Eval-suite fixtures — isolate cache to a temp directory so no stale L2 data bleeds between runs."""

import os
import pytest
from oapw.cache.manager import reset_cache
from oapw.core.config import reset_config


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point the cache DB at a fresh temp dir for every eval test."""
    monkeypatch.setenv("OAPW_DATA_DIR", str(tmp_path))
    reset_config()
    reset_cache()
    yield
    reset_cache()
    reset_config()
