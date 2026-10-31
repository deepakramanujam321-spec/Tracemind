import json
import os

import httpx
import pytest
from pydantic import BaseModel

from tracemind.contracts import Message
from tracemind.models import (
    GemmaApiProvider,
    GemmaLocalProvider,
    ModelConfigError,
    StructuredOutputError,
    provider_from_env,
)


class Out(BaseModel):
    x: int


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gemma_api_request_format_and_parse():
    seen = {}

    def h(req):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["x-goog-api-key"], json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": "hidden", "thought": True}, {"text": "hello"}]}}]})

    p = GemmaApiProvider("MODEL", "KEY", client=client(h))
    out = p.generate([Message(role="system", content="S"), Message(role="user", content="U"),
                      Message(role="assistant", content="A")], temperature=0.1)
    assert out == "hello"
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/models/MODEL:generateContent"
    assert seen["key"] == "KEY"
    assert seen["body"]["systemInstruction"] == {"parts": [{"text": "S"}]}
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model"]
    assert seen["body"]["generationConfig"] == {"temperature": 0.1}
    assert p.supports_tools is False


def test_structured_retry_then_success_and_exhaustion():
    replies = iter(["not json", '```json\n{"x": "bad"}\n```', 'Sure: {"x": 3}'])

    def h(req):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": next(replies)}]}}]})

    assert GemmaApiProvider("m", "k", client=client(h)).generate_structured([Message(role="user", content="q")], Out).x == 3

    def bad(req):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "nope"}]}}]})

    with pytest.raises(StructuredOutputError):
        GemmaApiProvider("m", "k", retries=1, client=client(bad)).generate_structured([Message(role="user", content="q")], Out)


def test_gemma_local_openai_format():
    seen = {}

    def h(req):
        seen["url"], seen["body"], seen["auth"] = str(req.url), json.loads(req.content), req.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}]})

    p = GemmaLocalProvider("tag", client=client(h))
    assert p.generate_structured([Message(role="user", content="q")], Out).x == 1
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["body"]["response_format"] == {"type": "json_object"} and seen["body"]["model"] == "tag"
    assert seen["auth"] == "Bearer ollama"


def test_http_error_becomes_model_error():
    from tracemind.models import ModelError
    p = GemmaLocalProvider("t", client=client(lambda r: httpx.Response(500)))
    with pytest.raises(ModelError):
        p.generate([Message(role="user", content="q")])


def test_factory():
    assert provider_from_env({"MODEL_PROVIDER": "gemma_local", "MODEL_NAME": "m", "MODEL_BASE_URL": "http://h/v1"}).name == "gemma_local"
    assert provider_from_env({"MODEL_PROVIDER": "gemma_api", "MODEL_NAME": "m", "MODEL_API_KEY": "k"}).name == "gemma_api"
    for env in ({}, {"MODEL_PROVIDER": "gemma_api"}, {"MODEL_PROVIDER": "gemma_api", "MODEL_NAME": "m"},
                {"MODEL_PROVIDER": "x", "MODEL_NAME": "m"}):
        with pytest.raises(ModelConfigError):
            provider_from_env(env)


@pytest.mark.skipif(not os.environ.get("MODEL_API_KEY"), reason="opt-in: set MODEL_PROVIDER/MODEL_NAME/MODEL_API_KEY")
def test_live_integration():
    p = provider_from_env()
    assert p.generate_structured([Message(role="user", content='Return {"x": 7}')], Out).x == 7
