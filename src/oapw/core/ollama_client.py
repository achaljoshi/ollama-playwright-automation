"""Async Ollama client — thin wrapper over the Ollama HTTP API with structured-output support."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Type, TypeVar

import httpx
from pydantic import BaseModel

from oapw.core.config import get_config

T = TypeVar("T", bound=BaseModel)


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str | None = None, timeout: int | None = None) -> None:
        cfg = get_config()
        self._base_url = (base_url or cfg.ollama_base_url).rstrip("/")
        self._timeout = timeout or cfg.ollama_timeout

    # ── Health ────────────────────────────────────────────────────────────────

    async def is_running(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self._base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self._base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]

    async def model_exists(self, model: str) -> bool:
        models = await self.list_models()
        # Accept both "qwen2.5:3b" and "qwen2.5:3b-instruct-q4_0" style names
        return any(m == model or m.startswith(model.split(":")[0]) for m in models)

    # ── Generate ──────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.1,
        json_mode: bool = False,
    ) -> str:
        cfg = get_config()
        payload: dict[str, Any] = {
            "model": model or cfg.ollama_default_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(f"{self._base_url}/api/generate", json=payload)
            if r.status_code != 200:
                raise OllamaError(f"Ollama generate failed {r.status_code}: {r.text[:200]}")
            return r.json()["response"]

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.1,
    ) -> T:
        raw = await self.generate(
            prompt=prompt,
            model=model,
            system=system,
            temperature=temperature,
            json_mode=True,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise OllamaError(f"LLM returned invalid JSON: {e}\nRaw: {raw[:300]}") from e
        return schema.model_validate(data)

    # ── Embeddings ────────────────────────────────────────────────────────────

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        cfg = get_config()
        payload = {
            "model": model or cfg.ollama_embed_model,
            "prompt": text,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(f"{self._base_url}/api/embeddings", json=payload)
            if r.status_code != 200:
                raise OllamaError(f"Ollama embed failed {r.status_code}: {r.text[:200]}")
            return r.json()["embedding"]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def prompt_hash(prompt: str, model: str, temperature: float) -> str:
        key = f"{model}:{temperature}:{prompt}"
        return hashlib.blake2b(key.encode(), digest_size=16).hexdigest()


_client: OllamaClient | None = None


def get_ollama_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
