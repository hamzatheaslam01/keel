# T-34: Proxy overhead test (p95 < 20 ms, truncate+pin)

## Goal
Add a performance test proving that Keel's own processing time (`proxy_ms`, which excludes upstream and internal LLM calls) has p95 under 20 ms for `truncate+pin` on realistic histories.

## Context
PRD non-functional requirement: proxy overhead under 20 ms p95 for truncate+pin, excluding upstream calls. `proxy_ms` is already recorded per request (`total - upstream_ms - llm_ms`) in the `requests` table.

Use an in-process mock upstream via `httpx.MockTransport` (lower overhead than respx) passed to `UpstreamClient(upstreams, transport=...)`, and build the app with `create_app(config, store=store, upstream=client)`. Tokens use the fallback counter (no tokenizer files).

Register a pytest marker `perf`. CI runs `-m "not perf"` (T-05), so this test only runs when selected.

## Files
Modify: `pyproject.toml` (add `markers = ["perf: performance tests"]` under `[tool.pytest.ini_options]`).
Create: `tests/test_perf.py`.
Read: `pyproject.toml`, `tests/conftest.py`, `src/keel/app.py`.

## Implement
1. `MockTransport` handler: return `httpx.Response(200, json=chat_json("ok"))` for any request.
2. Config: strategy `truncate+pin`, `keep_last_n=4`, truncate head 50 / tail 20 / older_than 2, `trigger_tokens=10**9`.
3. History: a system prompt plus 40 messages: 10 groups of (user, assistant tool_call, tool output of 3,000 chars, assistant text). Add 2 pins via the API.
4. Send 1 forced request, then 50 requests where the history grows by one user + one assistant message each time (these become cache hits and pin injections).
5. Read `proxy_ms` for the session from the store; compute the nearest-rank p95 over the 50 non-forced requests and over all 51. Print both.

## Tests
`tests/test_perf.py`:
- `@pytest.mark.perf async def test_truncate_pin_overhead_p95_under_20ms()`: assert p95 (all 51) < 20.0. Also assert at least one request has `cache_status == "hit"` and that the compaction record's `compacted` contains `"[truncated"`.

## Acceptance
```bash
uv run pytest tests/test_perf.py -m perf -q -s
uv run pytest -q -m "not perf"
uv run ruff check .
```
If the p95 assertion fails, profile with `python -X importtime` / `cProfile` and fix the hot spot (likely repeated `json.dumps` in hashing or token counting) in the module responsible. Only touch `session.py` or `tokens.py`; otherwise write the issue to `docs/BLOCKERS.md`. Record the measured p95 in PROGRESS.

## Out of scope
Optimising summarize/validate paths; changing contracts.

## Depends on
T-21, T-22

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
