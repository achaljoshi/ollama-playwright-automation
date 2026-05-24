"""Shared test fixtures."""

import pytest
from oapw.core.config import reset_config
from oapw.cache.manager import reset_cache


@pytest.fixture(autouse=True)
def reset_singletons():
    """Ensure config and cache singletons are fresh for every test."""
    reset_config()
    reset_cache()
    yield
    reset_config()
    reset_cache()
