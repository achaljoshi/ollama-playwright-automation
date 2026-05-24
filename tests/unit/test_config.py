"""Tests for OapwConfig."""

import os
import pytest
from oapw.core.config import OapwConfig, get_config, reset_config


def test_defaults():
    cfg = OapwConfig()
    assert cfg.ollama_base_url == "http://localhost:11434"
    assert cfg.ollama_default_model == "qwen2.5:3b"
    assert cfg.browser_type == "chromium"
    assert cfg.cache_l1_max_size == 512


def test_env_override(monkeypatch):
    monkeypatch.setenv("OAPW_OLLAMA_DEFAULT_MODEL", "llama3:8b")
    monkeypatch.setenv("OAPW_BROWSER_HEADLESS", "false")
    cfg = OapwConfig()
    assert cfg.ollama_default_model == "llama3:8b"
    assert cfg.browser_headless is False


def test_singleton_reset(monkeypatch, tmp_path):
    reset_config()
    monkeypatch.setenv("OAPW_DATA_DIR", str(tmp_path / "oapw"))
    cfg = get_config()
    assert str(tmp_path / "oapw") in str(cfg.data_dir)
    reset_config()


def test_cache_dir_property(tmp_path):
    cfg = OapwConfig(data_dir=tmp_path / "oapw")
    assert cfg.cache_dir == tmp_path / "oapw" / "cache"
    assert cfg.traces_dir == tmp_path / "oapw" / "traces"


def test_ensure_dirs(tmp_path):
    cfg = OapwConfig(data_dir=tmp_path / "oapw")
    cfg.ensure_dirs()
    assert cfg.cache_dir.is_dir()
    assert cfg.traces_dir.is_dir()
