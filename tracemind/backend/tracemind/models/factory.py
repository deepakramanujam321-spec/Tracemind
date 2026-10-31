"""Env-driven provider factory. No endpoint or model id is assumed beyond the documented URL defaults."""
from __future__ import annotations

import os
from collections.abc import Mapping

from tracemind.contracts import ModelProvider

from .gemma_api import GemmaApiProvider
from .gemma_local import GemmaLocalProvider


class ModelConfigError(ValueError):
    pass


def provider_from_env(env: Mapping[str, str] | None = None) -> ModelProvider:
    e = os.environ if env is None else env
    kind = (e.get("MODEL_PROVIDER") or "").strip().lower()
    model = (e.get("MODEL_NAME") or "").strip()
    base = (e.get("MODEL_BASE_URL") or "").strip() or None
    key = (e.get("MODEL_API_KEY") or "").strip() or None
    if not kind:
        raise ModelConfigError("MODEL_PROVIDER is required (gemma_api | gemma_local)")
    if not model:
        raise ModelConfigError("MODEL_NAME is required (no default model id is assumed; see docs/models.md)")
    if kind == "gemma_api":
        if not key:
            raise ModelConfigError("MODEL_API_KEY is required for gemma_api")
        extra = {}
        if (e.get("MODEL_TIMEOUT_S") or "").strip():
            extra["timeout"] = float(e["MODEL_TIMEOUT_S"])
        if (e.get("MODEL_THINKING_LEVEL") or "").strip():
            extra["thinking_level"] = e["MODEL_THINKING_LEVEL"].strip()
        return GemmaApiProvider(model=model, api_key=key, base_url=base, **extra)
    if kind == "gemma_local":
        return GemmaLocalProvider(model=model, base_url=base, api_key=key)
    raise ModelConfigError(f"unknown MODEL_PROVIDER {kind!r} (gemma_api | gemma_local)")
