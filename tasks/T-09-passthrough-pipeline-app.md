# T-09: Passthrough pipeline and app routes

## Goal
Build the first runnable vertical slice: a FastAPI app whose `POST /v1/chat/completions` forwards requests unchanged to the routed upstream and logs every request to SQLite. Add `GET /v1/models` and `GET /healthz`. Test everything against a respx-mocked upstream.

## Context
PRD FR-1: OpenAI-compatible chat endpoint, including `tools`, `tool_calls` and `tool` role messages. FR-3: pure passthrough when `X-Keel-Session` is absent. FR-10: write every request to SQLite.

In this task, requests that *do* carry a session are also forwarded unchanged. They get logged with the session id and `cache_status="none"`. Compaction comes in T-16.

Messages are raw dicts. Never rebuild them through pydantic, so unknown fields pass through untouched.

Contracts you implement now (`src/keel/pipeline.py`):
```python
@dataclass
class Deps: config: KeelConfig; store: Store; upstream: UpstreamClient; tokens: TokenRegistry
@dataclass
class KeelHeaders: session_id: str | None; policy: str | None; force_compact: bool; pin: str | None
@dataclass
class ChatOutcome:
    status_code: int; body: dict[str, Any] | None; headers: dict[str, str]
    stream: AsyncIterator[bytes] | None = None
def parse_keel_headers(headers: Mapping[str, str]) -> KeelHeaders
async def handle_chat(body: dict[str, Any], headers: Mapping[str, str], deps: Deps) -> ChatOutcome
async def passthrough(body: dict[str, Any], deps: Deps) -> ChatOutcome
def error_body(message: str, type_: str, code: int) -> dict[str, Any]
    # {"error": {"message": ..., "type": ..., "code": ...}}
```
`src/keel/app.py`:
```python
def create_app(config: KeelConfig, store: Store | None = None, upstream: UpstreamClient | None = None,
               tokens: TokenRegistry | None = None) -> FastAPI
```
Interfaces you use (already implemented):
```python
UpstreamClient(upstreams, transport=None); .route(model) -> UpstreamConfig (raises UnknownModelError)
.models() -> list[str]; async .forward(body) -> (httpx.Response, upstream_ms)   # no raise on 4xx/5xx
TokenRegistry(paths).count_messages(model, messages, tools) -> TokenCount(n, method)
Store(path).ensure_session(id, config_dict); .next_turn_idx(id) -> int; .insert_request(RequestRecord) -> int
class RequestRecord(BaseModel):
    session_id: str | None; turn_idx: int; upstream_model: str; status: int
    cache_status: Literal["passthrough", "none", "hit", "mismatch"]
    compacted: bool = False; tokenizer: Literal["hf", "fallback"]
    tokens_in_raw: int; tokens_in_sent: int; tokens_out: int | None = None
    pin_tokens: int = 0; proxy_ms: float; upstream_ms: float; llm_ms: float = 0.0
    error: str | None = None
```
Header names are case-insensitive: `X-Keel-Session`, `X-Keel-Policy`, `X-Keel-Force-Compact` (true only if the value is `"true"`, case-insensitive), `X-Keel-Pin`.

## Files
Modify: `src/keel/pipeline.py`, `src/keel/app.py`.
Create: `tests/conftest.py`, `tests/test_passthrough.py`.
Read: `src/keel/pipeline.py`, `src/keel/app.py`, `src/keel/upstream.py`, `src/keel/models.py`.

## Implement
1. `error_body` as in the contract.
2. `parse_keel_headers`: read via a lowercase-key dict. An empty string means None.
3. Private helper `async def _forward_and_log(body, messages_sent, deps, *, session_id, turn_idx, cache_status, t0, tokens_raw, compacted=False, pin_tokens=0, llm_ms=0.0, extra_headers=None) -> ChatOutcome`. Later tasks reuse it.
   1. `sent = {**body, "messages": messages_sent}`; count `tokens_in_sent` with `count_messages(model, messages_sent, body.get("tools"))`.
   2. `resp, up_ms = await deps.upstream.forward(sent)`.
   3. Parse `resp.json()`. If that raises `ValueError`: status 502, body `error_body("upstream returned non-JSON", "upstream_bad_response", 502)`.
   4. `tokens_out = body_json.get("usage", {}).get("completion_tokens")`.
   5. `proxy_ms = (perf_counter() - t0)*1000 - up_ms - llm_ms`, floored at 0.
   6. Insert a `RequestRecord` (error = the upstream error message, if any, else None).
   7. Return `ChatOutcome(resp.status_code, body_json, headers)` where headers = `{"X-Keel-Cache": cache_status}` plus `extra_headers`.
4. `passthrough(body, deps)`: `t0`, count raw tokens, then `_forward_and_log(body, body["messages"], deps, session_id=None, turn_idx=0, cache_status="passthrough", ...)`.
5. `handle_chat`:
   1. `t0 = perf_counter()`.
   2. Validate that `body` is a dict with a str `model` and a list `messages`; otherwise 400 `invalid_request_error`.
   3. If `body.get("stream")`: 501 `error_body("streaming not supported yet", "keel_stream_unsupported", 501)`.
   4. `hdr = parse_keel_headers(headers)`. No session → `return await passthrough(body, deps)`.
   5. Session path (temporary, T-16 replaces it): `deps.store.ensure_session(sid, {"strategy": deps.config.compaction.strategy})`, `turn_idx = next_turn_idx(sid)`, then `_forward_and_log(..., session_id=sid, turn_idx=turn_idx, cache_status="none", extra_headers={"X-Keel-Compacted": "false", "X-Keel-Tokens-Saved": "0", "X-Keel-Pins-Injected": "0"})`.
   6. Wrap all upstream use: `UnknownModelError` → 404 `model_not_found`; `httpx.HTTPError` → 502 `upstream_unreachable`. Both are still logged with `upstream_ms=0` and the error text.
6. `create_app`:
   - Build any missing deps: `Store(config.server.db)`, `UpstreamClient(config.upstreams)`, `TokenRegistry(config.tokenizers)`. Store `Deps` on `app.state.deps`.
   - Routes:
     - `POST /v1/chat/completions`: invalid JSON → 400 `invalid_request_error`. Otherwise `outcome = await handle_chat(await request.json(), request.headers, deps)` → `JSONResponse(outcome.body, status_code=outcome.status_code, headers=outcome.headers)`.
     - `GET /v1/models` → `{"object": "list", "data": [{"id": m, "object": "model", "owned_by": route(m).name}]}`.
     - `GET /healthz` → `{"status": "ok"}`.

## Tests
`tests/conftest.py` (shared by later tasks; keep these names):
```python
UP = "http://upstream.test/v1"
def chat_json(content="ok", tool_calls=None, prompt_tokens=10, completion_tokens=2) -> dict:
    msg = {"role": "assistant", "content": content}
    if tool_calls: msg["tool_calls"] = tool_calls
    return {"id": "c1", "object": "chat.completion", "model": "m1",
            "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens}}
@pytest.fixture
def config() -> KeelConfig:   # one upstream "up" at UP serving ["m1", "judge"], db ":memory:"
@pytest.fixture
def store() -> Store:         # Store(":memory:")
@pytest.fixture
def make_client(store):       # returns factory(cfg) -> httpx.AsyncClient over ASGITransport(create_app(cfg, store=store)), base_url "http://keel"
```
If respx intercepts the ASGI calls, add `respx_mock.route(host="keel").pass_through()` in the tests.

`tests/test_passthrough.py` (all async, using respx to mock `POST {UP}/chat/completions`):
- `test_passthrough_body_unchanged()`: send a body with `tools`, an assistant `tool_calls` message, a `tool` message and an unknown field `"foo": 1`. Assert the upstream received exactly that body (compare the parsed JSON). The response JSON equals `chat_json()`; status 200; `x-keel-cache: passthrough`.
- `test_passthrough_logged_without_session(store)`: one row with `session_id IS NULL`, `cache_status == "passthrough"`, `tokens_out == 2`, `tokenizer == "fallback"`.
- `test_session_request_logged(store)`: header `X-Keel-Session: s1`, two requests → rows with turn_idx 0 and 1; the `sessions` table has `s1`; `x-keel-compacted: false`.
- `test_upstream_error_passed_through()`: upstream 500 with JSON `{"error": {"message": "boom"}}` → status 500, the same JSON, and a logged row with status 500.
- `test_unknown_model_404()`: `model: "nope"` → 404 with `error.type == "model_not_found"`.
- `test_stream_501()`.
- `test_invalid_body_400()`: missing `messages`.
- `test_models_and_healthz()`: `/v1/models` lists `m1` and `judge`; `/healthz` returns ok.
- `test_parse_keel_headers_case_insensitive()`: `{"x-keel-session": "a", "X-KEEL-FORCE-COMPACT": "True"}` → session "a", force True.

## Acceptance
```bash
uv run pytest tests/test_passthrough.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
Compaction, cache, pins, the trace API, the CLI.

## Depends on
T-06, T-07, T-08

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
