# T-16: Pipeline compaction path (steps 2–7, 9)

## Goal
Replace the temporary session path in `handle_chat` with the real pipeline: load session state, apply the prefix cache, capture header pins, check the trigger, compact with the configured strategy, persist the compaction record, forward, and log.

## Context
The request pipeline (PRD), and the function each step maps to:
1. Receive (`handle_chat`; no `X-Keel-Session` → `passthrough`, already done).
2. `load_session`: session row, effective strategy, active pins, active compaction records, next turn index.
3. Apply cache (`message_hashes` + `apply_cache` from `keel.session`). Stale records → `store.deactivate_compactions(ids)` and force a recompaction.
4. `capture_constraints`: `X-Keel-Pin` → `store.add_pin`. Auto-extraction is T-31, so leave the hook in place (see step 4 of Implement).
5. `should_compact`: strategy ≠ `"none"` and (force or tokens > `trigger_tokens`).
6. `compact`: `find_span` → `CompactionState` → `run_strategies` → persist `CompactionRecord`.
7. Validation happens inside the strategies (T-29).
8. `inject_pins` is T-22. Call it **only** if a compaction record is in effect and `"pin"` is in `record.strategy.split("+")`.
9. Forward + log via the existing private `_forward_and_log` helper in `pipeline.py` (T-09).

Never compact the system prompt or the last `keep_last_n` messages; never split tool groups (`find_span` already enforces this).

Contracts:
```python
# keel.pipeline
def load_session(store: Store, session_id: str, config: KeelConfig, policy: str | None) -> SessionState
async def capture_constraints(raw: list[Message], hashes: list[str], state: SessionState,
                              hdr: KeelHeaders, deps: Deps) -> tuple[list[Pin], float]  # new pins, llm_ms
def should_compact(tokens_in: int, cfg: CompactionConfig, strategy: str, force: bool) -> bool
async def compact(cache: CacheResult, raw: list[Message], hashes: list[str], state: SessionState,
                  body: dict[str, Any], turn_idx: int, deps: Deps
                  ) -> tuple[CompactionRecord | None, float]   # persisted record (with id), llm_ms
# keel.models
class SessionState(BaseModel):
    session_id: str; compaction: CompactionConfig; strategy: str   # canonical effective
    pins: list[Pin]; compactions: list[CompactionRecord]
    extracted_upto: int = 0; extracted_hash: str | None = None; next_turn_idx: int = 0
# keel.session
def message_hashes(messages) -> list[str]
def find_span(messages, keep_last_n, min_end=0) -> tuple[int, int] | None
@dataclass
class CacheResult: working; record; status: Literal["none","hit","mismatch"]; stale; first_changed
def apply_cache(raw, hashes, records) -> CacheResult
def raw_prefix_len(cache, working_end) -> int
# keel.strategies.base
parse_strategy(spec, validate_enabled=False) -> list[Strategy]; canonical_name(list) -> str
CompactionState(messages, span, evicted, summary_text=None, validator=None, pins_to_inject=False, llm_tokens=0, llm_ms=0.0)
StrategyContext(session_id, agent_model, sampling, config, pins, tokens, llm)
async run_strategies(strategies, state, ctx) -> CompactionState
# keel.upstream: UpstreamError (raised by complete() on failures)
```
Response headers on the session path: `X-Keel-Compacted` (`"true"` if a record is in effect for this request, from a hit or a new compaction), `X-Keel-Tokens-Saved` (`tokens_in_raw - tokens_in_sent`, may be negative), `X-Keel-Pins-Injected` (count), `X-Keel-Cache` (`none|hit|mismatch`).

## Files
Modify: `src/keel/pipeline.py`.
Create: `tests/test_pipeline_compaction.py`.
Read: `src/keel/pipeline.py`, `src/keel/session.py`, `src/keel/strategies/base.py`, `tests/conftest.py`.

## Implement
1. `load_session`:
   - `cfg_c = config.compaction`; `spec = policy or cfg_c.strategy`.
   - `strategy = canonical_name(parse_strategy(spec, config.validate_.enabled))`. A `StrategyError` from a bad `X-Keel-Policy` propagates; `handle_chat` maps it to 400.
   - `store.ensure_session(sid, {"strategy": strategy, "compaction": cfg_c.model_dump()})`.
   - Read `extracted_upto`/`extracted_hash` from `get_session`.
   - Return `SessionState(..., pins=store.list_pins(sid, active_only=True), compactions=store.active_compactions(sid), next_turn_idx=store.next_turn_idx(sid))`.
2. `should_compact`: `strategy != "none" and (force or tokens_in > cfg.trigger_tokens)`.
3. `compact`:
   1. `prev = cache.record`; `span = find_span(cache.working, keep_last_n, min_end=len(prev.compacted) if prev else 0)`. If None → `(None, 0.0)`.
   2. `state0 = CompactionState(messages=list(cache.working), span=span, evicted=[dict(m) for m in cache.working[s:e]])`.
   3. `ctx = StrategyContext(session_id, agent_model=body["model"], sampling={k: body[k] for k in ("temperature", "top_p", "seed") if k in body}, config=deps.config, pins=state.pins, tokens=deps.tokens, llm=deps.upstream)`.
   4. `out = await run_strategies(parse_strategy(state.strategy), state0, ctx)`.
   5. `prefix_len = raw_prefix_len(cache, span[1])`, using the **original** end. `compacted = out.messages[:out.span[1]]`.
   6. `tokens_before` / `tokens_after` = `count_messages(model, cache.working / out.messages).n`.
   7. Build the `CompactionRecord`: `prefix_hash=hashes[prefix_len-1]`, `prefix_hashes=hashes[:prefix_len]`, `evicted=out.evicted`, `summary_text`, `validator`, `llm_tokens`, and `pins_injected=[p.text for p in state.pins] if out.pins_to_inject else []`.
   8. `rec.id = store.insert_compaction(rec)`. Return `(rec, out.llm_ms)`.
4. `capture_constraints`:
   - If `hdr.pin`: `store.add_pin(Pin(session_id=sid, text=hdr.pin.strip(), source="explicit", source_turn=state.next_turn_idx))`; collect the new pins.
   - If `deps.config.pins.auto_extract`: call `await _auto_extract(raw, hashes, state, deps)`, a private function that **for now returns `([], 0.0)`** (T-31 fills it).
   - Return `(new_pins, llm_ms)`.
5. Rewrite the session branch of `handle_chat`:
   1. `state = load_session(...)` (`StrategyError` → 400 `invalid_request_error`).
   2. `raw = body["messages"]`; `hashes = message_hashes(raw)`; `cache = apply_cache(raw, hashes, state.compactions)`.
   3. `force = hdr.force_compact`. If `cache.stale`: `deactivate_compactions([r.id ...])`, log a warning with `first_changed`, set `force = True`.
   4. `new_pins, llm_ms = await capture_constraints(...)`; then `state.pins = store.list_pins(sid, active_only=True)`.
   5. `tc = count_messages(model, cache.working, tools)`; `tokens_raw = count_messages(model, raw, tools).n`.
   6. `working = cache.working`; `record = cache.record`.
   7. If `should_compact(tc.n, state.compaction, state.strategy, force)`: try `rec, ms = await compact(...)`. On `(UpstreamError, httpx.HTTPError)`: log a request row with status 502 and the error, and return 502 `error_body(str(e), "keel_compaction_failed", 502)`. If `rec`: `working = rec.compacted + raw[rec.prefix_len:]`, `record = rec`, `compacted_now = True`, `llm_ms += ms`.
   8. If `record` is set and `"pin"` is in `record.strategy.split("+")`: `working, pin_text = inject_pins(working, state.pins)`; `pin_tokens = count_text(model, pin_text) + 4` if `pin_text`.
   9. `return await _forward_and_log(body, working, deps, session_id=sid, turn_idx=state.next_turn_idx, cache_status=cache.status, t0=t0, tokens_raw=tokens_raw, compacted=compacted_now, pin_tokens=pin_tokens, llm_ms=llm_ms, extra_headers={...})` with the 3 X-Keel headers above. (`X-Keel-Tokens-Saved` uses the raw count minus the `tokens_in_sent` that `_forward_and_log` computes; compute the sent count before calling, or extend the helper to add the header.)

## Tests
`tests/test_pipeline_compaction.py` (async; fixtures `config`, `store`, `make_client`, `chat_json`, `UP` from conftest; respx). Set `config.compaction.strategy = "summarize"` and `keep_last_n = 4`.

Upstream side effect: if the request's `messages[0].content` starts with `"You compress conversation history"`, return `chat_json("SUMMARY TEXT")`; otherwise `chat_json("ok")`. Record every request body in a list.

History helper `hist(n)`: `[{"role": "system", "content": "SYS"}]` plus `n` alternating user/assistant messages `"u0"`, `"a1"`, …
- `test_forced_compaction_writes_record(store)`: send `hist(10)` (11 messages) with `X-Keel-Force-Compact: true`. 2 upstream calls (summarizer + agent). The agent call's messages are `[SYS, summary, last 4 messages]`. `store.list_compactions(sid)` has 1 record with `prefix_len == 7`, `summary_text == "SUMMARY TEXT"`, `len(evicted) == 6`. Headers: `x-keel-compacted: true`, `x-keel-cache: none`.
- `test_cache_hit_reuses_summary()`: after the forced call, send `hist(12)`, which is the same prefix plus 2 more. Only 1 new upstream call (no summarizer); the agent receives `[SYS, summary, raw[7:13]]`; `x-keel-cache: hit`; still 1 compaction record.
- `test_mismatch_recompacts_from_change(store)`: after the forced call, send `hist(10)` with message 3 edited, and no force header. The old record is now inactive, a new record exists, the summarizer was called again, and `x-keel-cache: mismatch`.
- `test_tool_group_not_split()`: history `[SYS, u, a, u, call(c1), tool(c1), a, u]` with keep_last_n 3, forced. The agent payload's kept tail starts with the call message, and the tool message directly follows it.
- `test_strategy_none_ignores_force()`: strategy `none` with force → 1 upstream call; messages unchanged.
- `test_trigger_tokens_without_force()`: `trigger_tokens = 5` → it compacts without the header.
- `test_policy_header_override()`: config strategy `none`, `X-Keel-Policy: summarize`, force → compacts. `X-Keel-Policy: bogus` → 400.
- `test_compaction_failure_returns_502(store)`: the summarizer call returns 500 → response 502 with `error.type == "keel_compaction_failed"`; a request row with status 502 is logged.
- `test_header_pin_stored(store)`: `X-Keel-Pin: never deploy prod` → `store.list_pins(sid)` has 1 explicit pin.
- `test_request_rows_have_cache_status(store)`: after a forced call plus a hit call, the rows' `cache_status` are `["none", "hit"]` and `compacted` is `[1, 0]`.

## Acceptance
```bash
uv run pytest tests/test_pipeline_compaction.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
`inject_pins` body (T-22), auto-extraction (T-31), streaming (T-33), truncate/validate bodies.

## Depends on
T-09, T-14, T-15

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
