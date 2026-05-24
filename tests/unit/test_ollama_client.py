"""Unit tests for OllamaClient helpers (no live Ollama needed)."""

from oapw.core.ollama_client import OllamaClient


def test_prompt_hash_deterministic():
    h1 = OllamaClient.prompt_hash("hello", "qwen2.5:3b", 0.1)
    h2 = OllamaClient.prompt_hash("hello", "qwen2.5:3b", 0.1)
    assert h1 == h2


def test_prompt_hash_sensitive_to_model():
    h1 = OllamaClient.prompt_hash("hello", "qwen2.5:3b", 0.1)
    h2 = OllamaClient.prompt_hash("hello", "llama3:8b", 0.1)
    assert h1 != h2


def test_prompt_hash_sensitive_to_temp():
    h1 = OllamaClient.prompt_hash("hello", "qwen2.5:3b", 0.0)
    h2 = OllamaClient.prompt_hash("hello", "qwen2.5:3b", 0.5)
    assert h1 != h2


def test_prompt_hash_is_hex():
    h = OllamaClient.prompt_hash("test", "m", 0.1)
    assert len(h) == 32
    int(h, 16)
