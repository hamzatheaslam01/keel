# T-21: Truncate strategy

## Goal
Implement `truncate`: inside the compactable span, replace each tool output older than N turns with its head and tail tokens plus a `[truncated k tokens]` marker. User and assistant text stay intact.

## Context
PRD: "truncate: Replaces tool outputs older than N turns with head + tail + a [truncated k tokens] marker; leaves user and assistant text intact. Extra LLM calls: 0."

The age of a tool message = the number of `assistant` messages **after** it in the whole working list. A message is truncated when its age ≥ `older_than_turns`. Only messages inside `state.span` may change, and the message count stays the same, so `span` is unchanged.

```python
class TruncateConfig(BaseModel): older_than_turns: int = 3; head_tokens: int = 200; tail_tokens: int = 100
# ctx.config.compaction.truncate is a TruncateConfig; ctx.agent_model is the model name
# ctx.tokens.head_tail(model, text, head, tail) -> (head_text, tail_text, removed_tokens)  (removed == 0 means short enough)
@dataclass
class CompactionState:
    messages: list[Message]; span: tuple[int, int]; evicted: list[Message]
    summary_text: str | None = None; validator: dict[str, Any] | None = None
    pins_to_inject: bool = False; llm_tokens: int = 0; llm_ms: float = 0.0
class TruncateStrategy:  name = "truncate"; order = 10
    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState
```
Marker format, written exactly: `f"{head}\n[truncated {removed} tokens]\n{tail}"`. When `tail_tokens` is 0, drop the trailing `\n{tail}`.

## Files
Modify: `src/keel/strategies/truncate.py`.
Create: `tests/test_truncate.py`.
Read: `src/keel/strategies/truncate.py`, `src/keel/strategies/base.py`, `src/keel/tokens.py`.

## Implement
1. `s, e = state.span`; `cfg = ctx.config.compaction.truncate`.
2. Precompute `after[i]` = the number of assistant messages at index > i (one backward pass).
3. Copy the list. For each `i` in `range(s, e)` where `messages[i]["role"] == "tool"`, `isinstance(content, str)` and `after[i] >= cfg.older_than_turns`:
   - `head, tail, removed = ctx.tokens.head_tail(ctx.agent_model, content, cfg.head_tokens, cfg.tail_tokens)`.
   - If `removed > 0`, replace the message with `{**msg, "content": marker}`.
4. Return `dataclasses.replace(state, messages=new_messages)`. Never mutate the input dicts.

## Tests
`tests/test_truncate.py`. The context uses `TokenRegistry({})` (fallback: 4 chars per token), `KeelConfig()` with `truncate` head 5 / tail 5 / older_than 2, `agent_model "m"`, and a dummy llm (never called).
- `test_old_tool_output_truncated()`: messages `[sys, u, call(c1), tool(c1, "x"*400), a, u, a, u]` with span (1, 6). The tool message has 2 assistant messages after it, so it is truncated: the content starts with 20 `x`, contains `"[truncated 90 tokens]"`, and ends with 20 `x`. The tool_call_id is preserved.
- `test_recent_tool_output_kept()`: the same messages with only 1 assistant after the tool → unchanged.
- `test_user_and_assistant_untouched()`: a long user message in the span stays identical.
- `test_outside_span_untouched()`: an old tool message at an index ≥ span end stays identical.
- `test_short_tool_output_untouched()`: content of 30 chars → unchanged.
- `test_span_and_count_unchanged()`: `len(out.messages) == len(in)` and `out.span == in.span`; the input list's dicts are not mutated.
- `test_composes_with_pin_via_parse()`: `canonical_name(parse_strategy("pin+truncate")) == "truncate+pin"`.

## Acceptance
```bash
uv run pytest tests/test_truncate.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
The pipeline (it already runs strategies), summarize, pin injection.

## Depends on
T-15

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
