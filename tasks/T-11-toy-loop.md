# T-11: Toy tool-calling loop

## Goal
Write a minimal tool-calling agent loop (`python -m bench.toy_loop`) that talks to a running Keel. The week-1 exit check runs it against llama.cpp; this task tests it against an in-process app with a mocked upstream.

## Context
Week-1 exit criterion: "A toy tool-calling loop runs through Keel against llama.cpp and its requests show up in SQLite." The loop is an OpenAI-style client. It sends `messages` + `tools`, appends the assistant reply, answers any `tool_calls` with a fixed tool result, and repeats until the model replies without tool calls or `max_steps` is reached.

Contract (`bench/toy_loop.py`):
```python
async def run_toy_loop(client: httpx.AsyncClient, model: str, session: str, max_steps: int = 3) -> list[Message]
def main(argv: list[str] | None = None) -> int
```
`Message = dict[str, Any]`. Keel listens on `POST /v1/chat/completions`, and the header `X-Keel-Session: <id>` makes it log the request under that session.

## Files
Modify: `bench/toy_loop.py`.
Create: `tests/test_toy_loop.py`.
Read: `bench/toy_loop.py`, `tests/conftest.py`.

## Implement
1. Constants:
   - `TOOLS = [{"type": "function", "function": {"name": "get_time", "description": "Current UTC time", "parameters": {"type": "object", "properties": {"tz": {"type": "string"}}, "required": []}}}]`
   - `SYSTEM = "You are a helpful assistant. Use tools when useful."`
   - `USER = "What time is it in UTC? Use the get_time tool."`
   - `TOOL_RESULT = "2026-01-01T00:00:00Z"`
2. `run_toy_loop`:
   - `messages = [system, user]`. For each step up to `max_steps`: POST `/v1/chat/completions` with `{"model", "messages", "tools": TOOLS, "temperature": 0}` and header `X-Keel-Session: session`.
   - Call `raise_for_status()`, take `choices[0].message`, and keep only the keys `role`, `content`, `tool_calls` (`role` defaults to `"assistant"`, `content` None → `""`). Append it.
   - If it has `tool_calls`, append one `{"role": "tool", "tool_call_id": call["id"], "content": TOOL_RESULT}` per call and continue; otherwise stop.
   - Return the full `messages`.
3. `main`: argparse `--base-url` (default `http://127.0.0.1:8400`), `--model` (default `qwen3-1.7b`), `--session` (default `toy-1`), `--max-steps` (default 3).
   - Run with `asyncio.run` and `httpx.AsyncClient(base_url=..., timeout=300)`.
   - Print each message as `role: content` (tool calls as `-> name(arguments)`).
   - Return 0. On `httpx.HTTPError`, print it and return 1.
4. Add `if __name__ == "__main__": raise SystemExit(main())`.

## Tests
`tests/test_toy_loop.py` (async; use `config`, `store`, `make_client`, `chat_json` from conftest; respx for the upstream at `UP`):
- `test_toy_loop_two_steps(store)`: the upstream route has `side_effect` returning first `chat_json(content=None, tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}])`, then `chat_json("It is midnight UTC.")`. Run `run_toy_loop(client, "m1", "toy-1")`. Assert the last message content is `"It is midnight UTC."`, a `tool` message with `tool_call_id == "call_1"` exists, `store.next_turn_idx("toy-1") == 2`, and the second upstream request body contains the tool message.
- `test_toy_loop_stops_at_max_steps()`: the upstream always returns a tool call; `max_steps=2` → exactly 2 upstream calls.

## Acceptance
```bash
uv run pytest tests/test_toy_loop.py -q
uv run python -m bench.toy_loop --help
uv run ruff check .
```

## Out of scope
Any change to `src/keel`. Running against a real llama.cpp (that is HUMAN task H-05).

## Depends on
T-10

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
