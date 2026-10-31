# Model providers (Team C)

Providers: `gemma_api` (Gemini API `generateContent`), `gemma_local` (OpenAI-compatible server such as Ollama).
Env: `MODEL_PROVIDER`, `MODEL_NAME` (required, no default), `MODEL_BASE_URL`, `MODEL_API_KEY`.
**Live verification (2026-10-31):** `gemma-4-31b-it` and `gemma-4-26b-a4b-it` were called through the Gemini API
`generateContent` endpoint with the `x-goog-api-key` header; both returned text. The opt-in live test
(`tests/test_models.py::test_live_integration`, runs only when `MODEL_API_KEY` is set) and a structured-output call passed,
and a full investigation and remediation ran on `gemma-4-31b-it`. Observed: responses contain a `thought: true` part by default
(the provider drops it); `generationConfig.thinkingConfig.thinkingLevel` (`minimal`|`high`) is accepted; calls can take
minutes with thinking enabled, hence `MODEL_TIMEOUT_S` and bounded retries on timeout/429/5xx. `gemma_local` (OpenAI-compatible,
Ollama-style) is **not** live-tested.

## gemma_api (Google AI Gemini API)
- Docs say Gemma 4 model ids on the Gemini API are `gemma-4-31b-it` and `gemma-4-26b-a4b-it`; REST:
  `POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent`, body with `contents[].parts[].text`,
  `systemInstruction`, `generationConfig`, `tools[].functionDeclarations`. Auth header `x-goog-api-key` (documented in the Gemini
  API structured-output page; the Gemma page itself does not show the header).
- The Gemma page notes it is deprecated in favour of newer docs (gemma.ai) -- re-check ids before launch.
- Structured output: Gemma support for `responseMimeType`/response schema is NOT documented, so we use JSON-in-prompt +
  Pydantic validation + bounded retry (default 2 retries).
- `supports_tools=False`: Gemma function calling is documented, but `generate_with_tools` is not implemented.
- Thought parts (`thought: true`) are dropped from returned text.

## gemma_local (OpenAI-compatible)
- Ollama: `/v1/chat/completions`, base `http://localhost:11434/v1`, API key ignored (placeholder `ollama`);
  `response_format` JSON mode supported (`json_schema` not confirmed); tools supported without `tool_choice`.
- Ollama library `gemma4` tags: `latest`/`e4b`, `e2b`, `12b`, `26b`, `31b` (+ mlx/cloud). Tool calling and configurable thinking listed.
- We send `response_format: {"type":"json_object"}` (disable with `json_mode=False` for servers lacking it) AND validate/retry.
- llama.cpp server also exposes an OpenAI-compatible endpoint; not researched in detail here.
- `supports_tools=False` (not implemented).

## Sources
- https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ollama.com/library/gemma4
- https://docs.ollama.com/api/openai-compatibility
