# T-22: Pin strategy and pin injection

## Goal
Implement the `pin` strategy and `inject_pins`, so that after any compaction the active pin store is re-injected as one system message right after the original system prompt, headed `Standing instructions (pinned):`.

## Context
PRD pipeline step 8: "Inject pins as one system message right after the original system prompt, headed Standing instructions (pinned)." The strategy table says pin "re-injects the pin store after any compaction".

How it works here:
- `PinStrategy.apply` only sets `state.pins_to_inject = True` and leaves the messages unchanged.
- The pipeline (T-16, already written) calls `inject_pins(working, state.pins)` when a compaction record is in effect for the request and `"pin"` is in `record.strategy.split("+")`.
- Pins are **not** cached inside the compaction record's `compacted` list, so a pin added later appears on the next request.

```python
PIN_HEADER = "Standing instructions (pinned):"      # keel.models
class Pin(BaseModel): id; session_id; text; source; source_turn; confidence; active
class PinStrategy:  name = "pin"; order = 40
    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState
def inject_pins(working: list[Message], pins: list[Pin]) -> tuple[list[Message], str | None]   # keel.pipeline
```
Message format:
```
Standing instructions (pinned):
- <pin 1 text>
- <pin 2 text>
```
`{"role": "system", "content": <that text>}`. Insert it at index 1 if `working[0]["role"] == "system"`, else at index 0. Pins appear in the given order (store order = id ascending). If there are no pins, return `(working, None)` unchanged.

## Files
Modify: `src/keel/strategies/pin.py`, `src/keel/pipeline.py` (only `inject_pins`).
Create: `tests/test_pin_injection.py`.
Read: `src/keel/strategies/pin.py`, `src/keel/pipeline.py`, `tests/conftest.py`.

## Implement
1. `PinStrategy.apply`: `return dataclasses.replace(state, pins_to_inject=True)`.
2. `inject_pins` per the contract. Return a new list; the input is not mutated.

## Tests
`tests/test_pin_injection.py`:
- `test_inject_after_system()`: `[sys, u]` with 2 pins → `[sys, pinmsg, u]`. The content equals `"Standing instructions (pinned):\n- a\n- b"` and the returned text equals the content.
- `test_inject_without_system()`: `[u]` → the pin message comes first.
- `test_no_pins_noop()`.
- `test_pin_strategy_flag()`: `apply` sets the flag; the messages are identical.

Integration (async; `config` with `strategy = "summarize+pin"`, `keep_last_n = 4`; upstream respx side effect as in T-16: the summarizer call → `"SUMMARY"`, else `"ok"`; record bodies):
- `test_no_injection_before_compaction()`: add a pin via `POST /v1/sessions/s1/pins`, then send `hist(10)` without force → the upstream messages contain no `PIN_HEADER`.
- `test_injected_on_compaction_and_cache_hit(store)`:
  - Send forced `hist(10)`. The agent payload's `messages[1]` is the pin message. Headers: `x-keel-pins-injected: 1`. The request row has `pin_tokens > 0`. The compaction record has `pins_injected == [pin text]`.
  - Then send `hist(12)` without force → a cache hit, and the pin message is again at index 1.
- `test_pin_added_later_appears_and_deactivated_disappears()`: after a forced compaction, add a second pin via the `X-Keel-Pin` header → the next request carries 2 bullet lines. Deactivate the first pin via DELETE → the next request carries 1.
- `test_truncate_pin_injects()`: strategy `truncate+pin` with force → the pin message is present and the summarizer is not called.

(`hist(n)` is the same helper as in T-16: a system message plus n alternating user/assistant messages. Define it in this test file.)

## Acceptance
```bash
uv run pytest tests/test_pin_injection.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
Auto-extracted pins (T-31), validate (T-29), the pin API (already done).

## Depends on
T-16

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
