"""Provider-agnostic JSON-in-prompt structured output with Pydantic validation and bounded retry."""
from __future__ import annotations

import json
import re
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from tracemind.contracts import Message

DEFAULT_RETRIES = 2  # retries after the first attempt


class ModelError(RuntimeError):
    """Transport/API failure or exhausted structured-output retries."""


class StructuredOutputError(ModelError):
    pass


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> object:
    """Parse a JSON value from model text, tolerating code fences and surrounding prose."""
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    last: Exception | None = None
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError as e:
            last = e
    raise ValueError(f"no valid JSON found ({last})")


def schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "Respond with ONLY a single JSON object (no prose, no markdown fences) that validates against "
        "this JSON Schema:\n" + json.dumps(schema.model_json_schema())
    )


def structured_via_prompt(
    generate: Callable[[list[Message]], str],
    messages: list[Message],
    schema: type[BaseModel],
    retries: int = DEFAULT_RETRIES,
) -> BaseModel:
    msgs = [*messages, Message(role="user", content=schema_instruction(schema))]
    err = ""
    for _ in range(retries + 1):
        text = generate(msgs)
        try:
            return schema.model_validate(extract_json(text))
        except (ValueError, ValidationError) as e:
            err = str(e)[:800]
            msgs = [
                *msgs,
                Message(role="assistant", content=text),
                Message(role="user", content=f"That was invalid: {err}\nReturn ONLY corrected JSON."),
            ]
    raise StructuredOutputError(f"structured output failed after {retries + 1} attempts: {err}")
