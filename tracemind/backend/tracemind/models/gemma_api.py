"""Gemma 4 via the Gemini API (generateContent). See docs/models.md for sources.

Documented (ai.google.dev/gemma/docs/core/gemma_on_gemini_api): POST
{base}/models/{model}:generateContent with `contents`, `systemInstruction`, `generationConfig`.
Auth header `x-goog-api-key` is documented in the Gemini API docs. Structured-output (response schema) support for
Gemma is NOT documented, so JSON-in-prompt + validation is used.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel

from tracemind.contracts import Message

from .structured import DEFAULT_RETRIES, ModelError, structured_via_prompt

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GemmaApiProvider:
    name = "gemma_api"
    supports_tools = False  # Gemma function calling is documented, but generate_with_tools is not implemented here.

    def __init__(self, model: str, api_key: str, base_url: str | None = None, timeout: float = 300.0,
                 retries: int = DEFAULT_RETRIES, client: httpx.Client | None = None,
                 thinking_level: str | None = None, transport_retries: int = 2) -> None:
        if not model or not api_key:
            raise ValueError("model and api_key are required")
        self.model, self.api_key = model, api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.retries = retries
        self.thinking_level = thinking_level  # documented: generationConfig.thinkingConfig.thinkingLevel (minimal|high)
        self.transport_retries = transport_retries
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
        if self.thinking_level:
            gen["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        if gen:
            body["generationConfig"] = gen
        return body

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with bounded retry on transient failures only (timeout, 429, 5xx); other 4xx fail immediately."""
        last: Exception | None = None
        for attempt in range(self.transport_retries + 1):
            try:
                r = self._client.post(url, json=payload,
                                      headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"transient {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r.json()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500 and e.response.status_code != 429:
                    raise
                last = e
            if attempt < self.transport_retries:
                time.sleep(2 * (attempt + 1))
        raise last  # type: ignore[misc]

    def generate(self, messages: list[Message], **opts: Any) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        try:
            data = self._post(url, self._payload(messages, opts))
        except (httpx.HTTPError, ValueError) as e:
            raise ModelError(f"gemma_api request failed: {e}") from e
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(f"unexpected gemma_api response shape: {str(data)[:300]}") from e
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    def generate_structured(self, messages: list[Message], schema: type[BaseModel], **opts: Any) -> BaseModel:
        return structured_via_prompt(lambda m: self.generate(m, **opts), messages, schema, self.retries)
