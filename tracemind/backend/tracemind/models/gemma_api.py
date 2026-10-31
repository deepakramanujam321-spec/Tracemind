"""Gemma 4 via the Gemini API (generateContent). See docs/models.md for sources.

Documented (ai.google.dev/gemma/docs/core/gemma_on_gemini_api): POST
{base}/models/{model}:generateContent with `contents`, `systemInstruction`, `generationConfig`.
Auth header `x-goog-api-key` is documented in the Gemini API docs. Structured-output (response schema) support for
Gemma is NOT documented, so JSON-in-prompt + validation is used.
"""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel

from tracemind.contracts import Message

from .structured import DEFAULT_RETRIES, ModelError, structured_via_prompt

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GemmaApiProvider:
    name = "gemma_api"
    supports_tools = False  # Gemma function calling is documented, but generate_with_tools is not implemented here.

    def __init__(self, model: str, api_key: str, base_url: str | None = None, timeout: float = 120.0,
                 retries: int = DEFAULT_RETRIES, client: httpx.Client | None = None) -> None:
        if not model or not api_key:
            raise ValueError("model and api_key are required")
        self.model, self.api_key = model, api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.retries = retries
        self._client = client or httpx.Client(timeout=timeout)

    def _payload(self, messages: list[Message], opts: dict[str, Any]) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages if m.role != "system"
        ]
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        gen = {k: opts[k] for k in ("temperature", "maxOutputTokens", "topP") if k in opts}
        if gen:
            body["generationConfig"] = gen
        return body

    def generate(self, messages: list[Message], **opts: Any) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        try:
            r = self._client.post(url, json=self._payload(messages, opts),
                                  headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ModelError(f"gemma_api request failed: {e}") from e
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(f"unexpected gemma_api response shape: {str(data)[:300]}") from e
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    def generate_structured(self, messages: list[Message], schema: type[BaseModel], **opts: Any) -> BaseModel:
        return structured_via_prompt(lambda m: self.generate(m, **opts), messages, schema, self.retries)
