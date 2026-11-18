# T-10: Trace API, pin API and `keel serve`

## Goal
Add the trace endpoints, the pin endpoints and the `keel serve` CLI command.

## Context
PRD API:

| Method | Path | Purpose |
|---|---|---|
| POST | /v1/sessions/{id}/pins | Add a pin `{text}` (optional `source_turn`) |
| GET | /v1/sessions/{id}/pins | List pins |
| DELETE | /v1/sessions/{id}/pins/{pin_id} | Deactivate a pin |
| GET | /v1/traces | List sessions, newest first |
| GET | /v1/traces/{session_id} | Requests and compactions for one session |

CLI: `keel serve --config keel.yaml` loads the config and runs uvicorn on `server.host:server.port`.

Store methods you call (already implemented):
```python
ensure_session(session_id, config: dict) -> None; get_session(session_id) -> dict | None   # {id, created_at, config, extracted_upto, extracted_hash}
list_sessions(limit=100) -> list[dict]   # {id, created_at, n_requests, n_compactions}
list_requests(session_id) -> list[dict]; list_compactions(session_id) -> list[CompactionRecord]
add_pin(Pin) -> Pin; list_pins(session_id, active_only=False) -> list[Pin]; deactivate_pin(session_id, pin_id) -> bool
```
`Pin(id, session_id, text, source="explicit", source_turn=None, confidence=1.0, active=True)`.
`error_body(message, type_, code)` is in `keel.pipeline`. `app.state.deps` holds `Deps(config, store, upstream, tokens)`.

Trace detail JSON shape (the viewer depends on it):
```json
{"session": {"id": "...", "created_at": "...", "config": {}, "extracted_upto": 0, "extracted_hash": null},
 "requests": [ {"id": 1, "turn_idx": 0, "...": "all requests columns"} ],
 "compactions": [ {"...": "CompactionRecord.model_dump()"} ],
 "pins": [ {"...": "Pin.model_dump()"} ]}
```

## Files
Modify: `src/keel/app.py`, `src/keel/cli.py`.
Create: `tests/test_trace_pin_api.py`.
Read: `src/keel/app.py`, `src/keel/cli.py`, `src/keel/store.py`, `tests/conftest.py`.

## Implement
1. Pin routes:
   - POST: body `{"text": str, "source_turn": int | null}`. Blank or missing text → 400 `invalid_request_error`. Call `ensure_session(id, {"strategy": cfg.compaction.strategy})`, then `add_pin(Pin(session_id=id, text=text.strip(), source="explicit", source_turn=...))`. Return 201 with `pin.model_dump()`.
   - GET: returns `{"data": [p.model_dump() for p in list_pins(id)]}`.
   - DELETE: `deactivate_pin` is False → 404 `not_found`; otherwise `{"id": pin_id, "active": false}`.
2. `GET /v1/traces?limit=100` → `{"data": list_sessions(limit)}`.
3. `GET /v1/traces/{session_id}` → the shape above; an unknown session → 404 `not_found`.
4. `cli.main`:
   - `serve`: `cfg = load_config(args.config)` (`ConfigError` → print to stderr, return 2), then `uvicorn.run(create_app(cfg), host=cfg.server.host, port=cfg.server.port)`, return 0.
   - `bench run` / `bench report`: keep raising `NotImplementedError` (T-19, T-23).
   - `main` returns an int. Also add `if __name__ == "__main__": raise SystemExit(main())`.

## Tests
`tests/test_trace_pin_api.py` (async; use the `config`, `store` and `make_client` fixtures plus `chat_json` from conftest, and respx for the upstream):
- `test_add_list_deactivate_pin()`: POST `{"text": " never deploy prod "}` → 201, `text == "never deploy prod"`, `source == "explicit"`. GET → 1 pin. DELETE → `active` false. GET → the pin has `active` false. DELETE an unknown id → 404.
- `test_add_pin_blank_400()`.
- `test_add_pin_dedupes()`: POST the same text twice → the same `id`.
- `test_traces_list_and_detail()`: send 2 chat requests with `X-Keel-Session: s1` (upstream mocked) and add one pin. `/v1/traces` has `s1` with `n_requests == 2`. `/v1/traces/s1` has 2 requests, 0 compactions, 1 pin, and `session.config` is a dict.
- `test_trace_unknown_404()`.
- `test_cli_serve_bad_config(tmp_path, capsys)`: `main(["serve", "--config", str(tmp_path/"missing.yaml")]) == 2`.

## Acceptance
```bash
uv run pytest tests/test_trace_pin_api.py -q
uv run pytest -q
uv run ruff check .
uv run keel serve --help
```

## Out of scope
Pin injection into requests (T-22), the X-Keel-Pin header (T-16), bench CLI subcommands.

## Depends on
T-09

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
