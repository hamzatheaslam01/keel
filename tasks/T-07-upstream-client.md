# T-07: Upstream client and routing

## Goal
Implement `UpstreamClient`: route a request by its `model` field to a configured OpenAI-compatible upstream, forward chat completions unchanged, and provide the internal `complete()` call that strategies use.

## Context
PRD FR-2: forward to one or more configured upstreams (llama.cpp server, Ollama, any OpenAI-compatible API), selected by the request's `model` field. Each upstream may define `extra_body`. It is merged *under* every request body (the request's own keys win), and it's how Qwen3 thinking gets turned off: `{"chat_template_kwargs": {"enable_thinking": false}}`.

```python
class UpstreamConfig(BaseModel):
    name: str; base_url: str; api_key: str | None = None
    models: list[str]; extra_body: dict[str, Any] = {}; timeout_s: float = 600.0
class LLMResult(BaseModel):          # keel.strategies.base
    text: str; prompt_tokens: int; completion_tokens: int; ms: float
```
Contract:
```python
class UnknownModelError(KeyError): ...
class UpstreamError(RuntimeError): ...
class UpstreamClient:   # implements LLMClient
    def __init__(self, upstreams: list[UpstreamConfig], transport: httpx.AsyncBaseTransport | None = None)
    def route(self, model: str) -> UpstreamConfig
    def models(self) -> list[str]
    async def forward(self, body: dict[str, Any]) -> tuple[httpx.Response, float]   # response, upstream_ms
    async def forward_stream(self, body: dict[str, Any]) -> AsyncIterator[bytes]  # stays a stub (T-33)
    async def complete(self, model, messages, *, temperature, top_p=None, seed=None, max_tokens=1024) -> LLMResult
    async def aclose(self) -> None
```

## Files
Modify: `src/keel/upstream.py`.
Create: `tests/test_upstream.py`.
Read: `src/keel/upstream.py`, `src/keel/config.py`, `src/keel/strategies/base.py`.

## Implement
1. `__init__`: keep the upstream list. Build `self._client = httpx.AsyncClient(transport=transport)` (passing `transport=None` lets respx intercept).
2. `route(model)`: return the first upstream whose `models` contains `model`. Otherwise raise `UnknownModelError(model)`.
3. `models()`: every model name across upstreams, in order, de-duplicated.
4. `forward(body)`:
   - `up = route(body["model"])`; `url = up.base_url.rstrip("/") + "/chat/completions"`; `payload = {**up.extra_body, **body}`.
   - Headers: `Authorization: Bearer <api_key>` if `api_key` is set.
   - `t0 = time.perf_counter()`; `resp = await self._client.post(url, json=payload, headers=headers, timeout=up.timeout_s)`; `ms = (perf_counter() - t0) * 1000`.
   - Return `(resp, ms)`. Do **not** raise on status ≥ 400; the caller passes errors through.
5. `complete(...)`:
   - body = `{"model", "messages", "temperature", "max_tokens"}`, plus `top_p` and `seed` only when not None, and `"stream": False`.
   - Call `forward`. If status ≥ 400, raise `UpstreamError(f"{status}: {resp.text[:500]}")`. Wrap any `httpx.HTTPError` in `UpstreamError`.
   - Parse `choices[0].message.content` (None → `""`) and `usage.prompt_tokens` / `usage.completion_tokens` (missing → 0).
   - Return `LLMResult(text, prompt_tokens, completion_tokens, ms)`.
6. `aclose()` closes the httpx client.

## Tests
`tests/test_upstream.py`. Use `respx` (already a dev dependency) with `@respx.mock` or `respx.mock()`.

Config fixture: upstream `a` at `http://up-a.test/v1` serving `["m1", "m2"]` with `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`; upstream `b` at `http://up-b.test/v1/` (trailing slash) serving `["m3"]` with `api_key="k"`.

Mocked response JSON:
```json
{"id":"x","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"hi"},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":2,"total_tokens":9}}
```
- `test_route_and_models()`: `route("m3").name == "b"`; `models() == ["m1", "m2", "m3"]`; `route("zz")` raises `UnknownModelError`.
- `test_forward_merges_extra_body()`: mock POST `http://up-a.test/v1/chat/completions`. Assert the sent JSON has `chat_template_kwargs` and the original `messages`, and that a body key overrides the same `extra_body` key. Returns status 200 and `ms >= 0`.
- `test_forward_auth_and_trailing_slash()`: route `b` hits `http://up-b.test/v1/chat/completions` with header `authorization: Bearer k`.
- `test_forward_passes_error_status()`: the mock returns 500 → `forward` returns a response with status 500 and no exception.
- `test_complete_parses_usage()`: the result has `text == "hi"`, `prompt_tokens == 7`, `completion_tokens == 2`; the sent body has `seed` when given and lacks `top_p` when it is None.
- `test_complete_raises_on_error()`: 503 → `UpstreamError`.
- `test_complete_wraps_connect_error()`: the route has `side_effect=httpx.ConnectError("x")` → `UpstreamError`.

## Acceptance
```bash
uv run pytest tests/test_upstream.py -q
uv run ruff check .
```

## Out of scope
Streaming (T-33), the FastAPI app, retries.

## Depends on
T-04

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
