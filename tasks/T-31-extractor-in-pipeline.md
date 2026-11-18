# T-31: Extractor in pipeline step 4

## Goal
Fill the `_auto_extract` hook in `keel/pipeline.py`. When `pins.auto_extract` is on, run the extractor on user and tool messages that are new since the last request in the session, store the results as `auto` pins, and advance the session's extraction cursor.

## Context
PRD pipeline step 4: "Capture constraints: add explicit pins (API or header) and, if enabled, run the auto-extractor on messages new since the last request." It runs **before** compaction (steps 5–6), so a constraint is captured from the raw history before the summary can drop it. The client resends full history, so "new" is tracked with a cursor on the session row: `extracted_upto` (count of raw messages already scanned) and `extracted_hash` (the chained hash of message `extracted_upto - 1`). If the hash at that index no longer matches (the client edited history), rescan from 0.

Pins with `confidence >= pins.min_confidence` are stored active; lower ones are stored inactive, for P/R analysis. `store.add_pin` de-duplicates active pins with the same text.

Interfaces:
```python
# keel.extract
async def extract_constraints(messages, llm, model, max_input_chars) -> tuple[list[Candidate], float, int]   # Candidate(text, confidence)
# keel.store.Store
add_pin(Pin) -> Pin; set_extracted(session_id, upto: int, last_hash: str | None) -> None
# keel.models.Pin(session_id, text, source="auto", source_turn=<raw index>, confidence, active)
# SessionState has extracted_upto: int, extracted_hash: str | None (loaded by load_session)
# PinsConfig: auto_extract: bool, extractor_model: str, min_confidence: float, max_input_chars: int
# keel.upstream.UpstreamError; handle_chat already maps UpstreamError from compaction to 502 keel_compaction_failed
```
Current hook (T-16) in `capture_constraints`:
```python
if deps.config.pins.auto_extract:
    pins, ms = await _auto_extract(raw, hashes, state, deps)   # currently returns ([], 0.0)
```

## Files
Modify: `src/keel/pipeline.py`.
Create: `tests/test_extract_pipeline.py`.
Read: `src/keel/pipeline.py`, `src/keel/extract.py`, `tests/conftest.py`.

## Implement
1. `_auto_extract(raw, hashes, state, deps) -> tuple[list[Pin], float]`:
   1. `start = state.extracted_upto` if `0 < extracted_upto <= len(raw)` and `hashes[extracted_upto-1] == state.extracted_hash`; otherwise 0.
   2. For each `i in range(start, len(raw))` with role `user` or `tool`: `cands, ms, _ = await extract_constraints([raw[i]], deps.upstream, cfg.extractor_model, cfg.max_input_chars)` (one message per call, so `source_turn = i`). For each candidate: `deps.store.add_pin(Pin(session_id=sid, text=c.text, source="auto", source_turn=i, confidence=c.confidence, active=c.confidence >= cfg.min_confidence))`.
   3. Afterwards: `deps.store.set_extracted(sid, len(raw), hashes[-1] if raw else None)`.
   4. Return the new pins and the total ms.
2. Make sure `capture_constraints`'s `UpstreamError` / `httpx.HTTPError` produce the same 502 `keel_compaction_failed` path as compaction failures, with a request row logged. Move the try block up if needed.

## Tests
`tests/test_extract_pipeline.py` (async; conftest fixtures; `config.pins.auto_extract = True`, `extractor_model = "judge"`, strategy `summarize+pin`). Upstream respx side effect:
- model `judge` → `chat_json('{"instructions": [{"text": "Never deploy to prod.", "confidence": 0.9}]}')` if the message block contains `"prod"`, otherwise `chat_json('{"instructions": []}')`;
- the summarizer → `"SUMMARY"`;
- else `"ok"`.
- `test_extracts_from_user_turn(store)`: history `[sys, u("check logs"), u("Never deploy to prod."), a("ok")]` → 1 active auto pin with `source_turn == 2`; extractor calls = 2 (user messages only).
- `test_extracts_from_tool_output(store)`: a tool message containing "prod" → a pin with `source_turn` equal to the tool message index.
- `test_only_new_messages_scanned()`: the second request with 2 more messages → only those 2 are scanned (count the judge calls).
- `test_edit_rescans_from_zero()`: edit message 1 → all user/tool messages are rescanned. The pin store still holds a single active copy (dedupe).
- `test_low_confidence_inactive(store)`: conf 0.3 → the pin is stored with `active False` and is not injected after compaction.
- `test_auto_pin_injected_after_compaction()`: forced compaction → the upstream agent payload has the pin message containing "Never deploy to prod."
- `test_extractor_failure_502()`: the judge route returns 500 → 502 `keel_compaction_failed`.
- `test_disabled_makes_no_calls()`: `auto_extract False` → 0 judge calls.

## Acceptance
```bash
uv run pytest tests/test_extract_pipeline.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
Changing `extract.py`, the report, the runner (it already scores auto pins).

## Depends on
T-16, T-19, T-30

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
