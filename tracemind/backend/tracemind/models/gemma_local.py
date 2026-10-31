"""Gemma served locally through an OpenAI-compatible /chat/completions server (Ollama, llama.cpp server, ...).

Ollama documents `/v1/chat/completions` with `response_format` JSON mode and tools (no tool_choice); base URL
http://localhost:11434/v1 and a placeholder API key. See docs/models.md.
"""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel

from tracemind.contracts import Message

from .structured import DEFAULT_RETRIES, ModelError, structured_via_prompt

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class GemmaLocalProvider:
    name = "gemma_local"
    supports_tools = False  # server-side tools exist (Ollama) but generate_with_tools is not implemented.

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None,
                 json_mode: bool = True, timeout: float = 300.0, retries: int = DEFAULT_RETRIES,
                 client: httpx.Client | None = None) -> None:
        if not model:
            raise ValueError("model is required")
        self.model = model
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or "ollama"  # local servers ignore it
        self.json_mode = json_mode
        self.retries = retries
        self._client = client or httpx.Client(timeout=timeout)

    def _chat(self, messages: list[Message], opts: dict[str, Any], json_mode: bool) -> str:
        body: dict[str, Any] = {"model": self.model, "messages": [m.model_dump() for m in messages]}
        for k in ("temperature", "max_tokens", "top_p"):
            if k in opts:
                body[k] = opts[k]
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = self._client.post(f"{self.base_url}/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ModelError(f"gemma_local request failed: {e}") from e
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(f"unexpected gemma_local response shape: {str(data)[:300]}") from e

    def generate(self, messages: list[Message], **opts: Any) -> str:
        return self._chat(messages, opts, json_mode=False)

    def generate_structured(self, messages: list[Message], schema: type[BaseModel], **opts: Any) -> BaseModel:
        return structured_via_prompt(lambda m: self._chat(m, opts, self.json_mode), messages, schema, self.retries)
