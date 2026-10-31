"""Test-only ModelProvider. Responses are keyed by (schema name, agent) because agents run in parallel."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from tracemind.contracts import Message


class ScriptedProvider:
    name = "scripted"
    supports_tools = False

    def __init__(self) -> None:
        self.scripts: dict[tuple[str, str | None], Any] = {}
        self.calls: list[tuple[str, list[Message]]] = []

    def script(self, schema: str, response: dict | BaseException, agent: str | None = None) -> ScriptedProvider:
        self.scripts[(schema, agent)] = response
        return self

    def generate(self, messages: list[Message], **opts: Any) -> str:
        return "scripted"

    def generate_structured(self, messages: list[Message], schema: type[BaseModel], **opts: Any) -> BaseModel:
        system = messages[0].content
        self.calls.append((schema.__name__, messages))
        for agent in ("trace_investigator", "code_analyst", "skeptic", "adjudicator"):
            if f"You are the {agent} agent" in system:
                break
        else:
            agent = None
        resp = self.scripts.get((schema.__name__, agent), self.scripts.get((schema.__name__, None)))
        if resp is None:
            raise AssertionError(f"no script for {schema.__name__}/{agent}")
        if isinstance(resp, BaseException):
            raise resp
        return schema.model_validate(resp)
