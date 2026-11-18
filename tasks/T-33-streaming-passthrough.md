# T-33: Streaming passthrough

## Goal
Support `stream: true`: run pipeline steps 1–8 as usual, then stream the upstream SSE bytes to the client unchanged, and write the trace row once the stream ends.

## Context
PRD FR-17: streaming passthrough (`stream: true`). Compaction happens before forwarding, so a streamed request may also compact. Its internal LLM calls (summarizer, judge, extractor) stay non-streaming.

Today `handle_chat` returns 501 `keel_stream_unsupported` for `stream: true`. Remove that.

```python
class UpstreamClient:
    async def forward_stream(self, body: dict[str, Any]) -> AsyncIterator[bytes]   # implement now
@dataclass
class ChatOutcome:
    status_code: int; body: dict[str, Any] | None; headers: dict[str, str]
    stream: AsyncIterator[bytes] | None = None
# pipeline has private _forward_and_log(body, messages_sent, deps, *, session_id, turn_idx, cache_status, t0, tokens_raw, compacted, pin_tokens, llm_ms, extra_headers) -> ChatOutcome
```
OpenAI SSE format: lines `data: {json}\n\n`, ending with `data: [DONE]\n\n`. The final chunk may carry `"usage"` (when the client sets `stream_options.include_usage`). Take `tokens_out` from the last chunk that has `usage.completion_tokens`, else None.

## Files
Modify: `src/keel/upstream.py`, `src/keel/pipeline.py`, `src/keel/app.py`.
Create: `tests/test_streaming.py`.
Read: `src/keel/upstream.py`, `src/keel/pipeline.py`, `src/keel/app.py`, `tests/conftest.py`.

## Implement
1. `forward_stream(body)`:
   - Route the same way as `forward` (same URL, `extra_body` merge and auth).
   - `async with self._client.stream("POST", url, json=payload, headers=..., timeout=up.timeout_s) as resp:`. If `resp.status_code >= 400`: `await resp.aread()` and raise `UpstreamError(f"{status}: {text[:500]}")`. Otherwise `async for chunk in resp.aiter_raw(): yield chunk`.
2. Pipeline:
   - Add a private `_stream_and_log(...)` that mirrors `_forward_and_log`. It returns `ChatOutcome(200, None, headers, stream=gen())`.
   - `gen()` yields the upstream chunks while collecting them (cap at 2 MB). In `finally`, it parses `tokens_out` from the collected `data:` lines and inserts the `RequestRecord` (with `upstream_ms` = time from the first byte requested to the end, and `proxy_ms` = pre-forward time only).
   - On `UpstreamError` raised before the first chunk, return a normal error outcome. To make that possible, start the generator and pull the first chunk before returning.
3. Use it in both `passthrough` and the session path when `body.get("stream") is True`.
4. `app.py`: if `outcome.stream` is set → `StreamingResponse(outcome.stream, media_type="text/event-stream", headers=outcome.headers)`.

## Tests
`tests/test_streaming.py` (async; respx returns `httpx.Response(200, headers={"content-type": "text/event-stream"}, content=SSE)` with):
```python
SSE = (b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
       b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
       b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
       b'data: [DONE]\n\n')
```
- `test_stream_passthrough_bytes(store)`: no session, `stream: true` → the response body bytes equal `SSE`; content type is text/event-stream; one request row with `tokens_out == 2` and `cache_status == "passthrough"`.
- `test_stream_with_session_and_compaction(store)`: strategy `summarize`, force header, `stream: true`. The summarizer call (non-stream, JSON) is distinguished in the respx side effect by `stream` being absent or false in the body. The streamed body arrives, a compaction record exists, and `x-keel-compacted: true`.
- `test_stream_upstream_error()`: the upstream returns 500 for the stream → the client gets a 502 or 500 JSON error (no hang), and a row is logged with the error.
- `test_non_stream_unchanged()`: a normal request still returns JSON.

## Acceptance
```bash
uv run pytest tests/test_streaming.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
Streaming internal LLM calls; SSE re-encoding (the bytes must pass through untouched).

## Depends on
T-16

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
