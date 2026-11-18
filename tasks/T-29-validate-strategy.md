# T-29: Validate strategy (judge + verbatim repair)

## Goal
Implement `validate`: after `summarize`, a fixed small judge model checks whether the summary still states each active pin. On a miss, it appends the missing pins verbatim to the summary message and logs the result.

## Context
PRD FR-14: validate strategy with the fixed judge model and verbatim repair. PRD step 7: "a small judge checks that the summary still states each pin; on a miss, append the missing pins verbatim and log the miss." It costs one LLM call per compaction.

The judge model is `ctx.config.validate_.judge_model` (default `qwen3-1.7b`), the same in every condition, called with **temperature 0 and seed 0**. Validate always runs after summarize (canonical order). After summarize, the summary message is at `state.messages[state.span[0]]` and `state.summary_text` holds the summary text.

`state.summary_text` must stay the **pre-repair** text. Only the message content gets the appended block.

```python
SUMMARY_PREFIX = "[Summary of earlier conversation]"
class Pin(BaseModel): id: int | None; session_id: str; text: str; ...
@dataclass
class CompactionState:
    messages: list[Message]; span: tuple[int, int]; evicted: list[Message]
    summary_text: str | None = None; validator: dict[str, Any] | None = None
    pins_to_inject: bool = False; llm_tokens: int = 0; llm_ms: float = 0.0
# ctx.pins: list[Pin] (active); ctx.llm.complete(model, messages, *, temperature, top_p=None, seed=None, max_tokens=1024) -> LLMResult(text, prompt_tokens, completion_tokens, ms)
class ValidateStrategy: name = "validate"; order = 30
    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState
```
Judge prompt (write it exactly):
```python
JUDGE_SYSTEM = "You check whether a summary preserves specific instructions. Answer only with JSON."
JUDGE_USER = ("Summary:\n<summary>\n{summary}\n</summary>\n\nInstructions:\n{numbered}\n\n"
              "For each instruction, is it stated (same meaning) in the summary? "
              'Reply with JSON only: {{"covered": [true or false for each instruction, in order]}}')
REPAIR_HEADER = "Standing instructions (verbatim):"
```
`validator` dict, as written:
```python
{"judge_model": str, "pins": [{"id": int | None, "text": str, "covered": bool}], "missing": int,
 "parse_error": bool, "prompt_tokens": int, "completion_tokens": int}
# skip cases: {"judge_model": ..., "pins": [], "missing": 0, "parse_error": False, "skipped": "no_pins" | "no_summary"}
```

## Files
Modify: `src/keel/strategies/validate.py`.
Create: `tests/test_validate_strategy.py`.
Read: `src/keel/strategies/validate.py`, `src/keel/strategies/base.py`, `src/keel/strategies/summarize.py`.

## Implement
1. If `state.summary_text is None` → return the state with the `no_summary` skip dict. If `ctx.pins` is empty → return the `no_pins` skip dict. Neither case makes an LLM call.
2. `numbered = "\n".join(f"{i+1}. {p.text}" for i, p in enumerate(ctx.pins))`. Call the judge with `[system, user]`, `temperature=0.0`, `seed=0`, `max_tokens=256`.
3. Parse the reply:
   - Remove `<think>.*?</think>` and find the first `{...}` with `re.search(r"\{[\s\S]*\}", text)`. `json.loads` must give a dict whose `covered` is a list of bools with length equal to the pin count.
   - Anything else → `parse_error=True` and every pin treated as not covered (conservative).
4. `missing = [p for p, c in zip(pins, covered) if not c]`. If any are missing: `msg = state.messages[span[0]]`, new content `msg["content"] + "\n\n" + REPAIR_HEADER + "\n" + "\n".join(f"- {p.text}" for p in missing)`. Replace that message in a copied list.
5. Return a new state: `validator` dict filled; `llm_tokens += prompt + completion`; `llm_ms += ms`; `summary_text` unchanged; `span` unchanged.

## Tests
`tests/test_validate_strategy.py`, using a FakeLLM that returns a configurable text and records calls (same shape as in T-15). The state starts after a summary: `messages = [sys, {"role": "user", "content": SUMMARY_PREFIX + "\nS"}, u]`, `span=(1, 2)`, `summary_text="S"`.
- `test_all_covered_no_repair()`: judge returns `{"covered": [true, true]}` with 2 pins → content unchanged, `missing == 0`, `parse_error False`.
- `test_missing_pin_repaired()`: `[true, false]` → content ends with `"Standing instructions (verbatim):\n- <pin2 text>"`, `missing == 1`, `summary_text == "S"`.
- `test_parse_error_repairs_all()`: judge returns `"I think yes"` → `parse_error True`, `missing == 2`, both pins appended.
- `test_wrong_length_is_parse_error()`: `{"covered": [true]}` with 2 pins → parse_error.
- `test_think_block_ignored()`: `"<think>{bad}</think>{\"covered\": [true, true]}"` → no parse error.
- `test_no_pins_skips_call()`: 0 LLM calls, `validator["skipped"] == "no_pins"`.
- `test_no_summary_skips()`.
- `test_judge_model_and_determinism()`: the call uses `model == config.validate_.judge_model`, `temperature == 0.0`, `seed == 0`, even when `ctx.agent_model` differs.
- `test_tokens_accumulate()`: `llm_tokens` grows by prompt + completion.

## Acceptance
```bash
uv run pytest tests/test_validate_strategy.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
Pipeline changes (validate already runs inside `run_strategies`), the report.

## Depends on
T-15

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
