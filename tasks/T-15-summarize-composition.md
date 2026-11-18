# T-15: Summarize strategy and `+` composition

## Goal
Implement strategy composition (`parse_strategy`, `canonical_name`, `run_strategies`) and the `summarize` strategy, which replaces the compactable span with one LLM-written summary message.

## Context
Strategies compose with `+` (e.g. `summarize+pin`). Composition rules:
- Split on `+` and strip spaces.
- `none` means the empty list and cannot be combined with anything.
- Unknown names and duplicates are errors.
- `validate` requires `summarize`.
- If `validate_enabled=True` and `summarize` is present, add `validate` when it's missing.
- Execution follows canonical `order`, whatever order was written: truncate 10, summarize 20, validate 30, pin 40.

Each strategy may only rewrite `messages[span[0]:span[1]]`. Afterwards it must set `span = (start, start + new_count)`.

The summarizer uses the **agent's own model** by default (`config.compaction.summarizer == "same_as_agent"`); otherwise it uses the named model. It copies the request's `temperature`/`top_p`/`seed` from `ctx.sampling`, with temperature defaulting to 0.7 when absent. Its prompt is fixed and generic, and **never mentions constraints or rules**. The point is to measure realistic naive compaction.

```python
# keel.models
SUMMARY_PREFIX = "[Summary of earlier conversation]"
# keel.strategies.base (already defined)
class LLMResult(BaseModel): text: str; prompt_tokens: int; completion_tokens: int; ms: float
class LLMClient(Protocol):
    async def complete(self, model, messages, *, temperature, top_p=None, seed=None, max_tokens=1024) -> LLMResult
@dataclass
class CompactionState:
    messages: list[Message]; span: tuple[int, int]; evicted: list[Message]
    summary_text: str | None = None; validator: dict[str, Any] | None = None
    pins_to_inject: bool = False; llm_tokens: int = 0; llm_ms: float = 0.0
@dataclass
class StrategyContext:
    session_id: str; agent_model: str; sampling: dict[str, Any]
    config: KeelConfig; pins: list[Pin]; tokens: TokenRegistry; llm: LLMClient
class StrategyError(ValueError): ...
def parse_strategy(spec: str, validate_enabled: bool = False) -> list[Strategy]
def canonical_name(strategies: list[Strategy]) -> str     # "none" when empty; names joined by "+" in order
async def run_strategies(strategies, state, ctx) -> CompactionState
```
Strategy classes: `TruncateStrategy` (keel.strategies.truncate), `SummarizeStrategy` (.summarize), `ValidateStrategy` (.validate) and `PinStrategy` (.pin). Each has a no-arg constructor, `name` and `order`.

## Files
Modify: `src/keel/strategies/base.py`, `src/keel/strategies/summarize.py`.
Create: `tests/test_summarize_composition.py`.
Read: `src/keel/strategies/base.py`, `src/keel/strategies/summarize.py`, `src/keel/models.py`.

## Implement
1. `base.parse_strategy`:
   - Build the registry lazily inside the function (import the four modules there) as `{"truncate": TruncateStrategy, ...}`.
   - Handle an empty or `"none"` spec → `[]`.
   - Apply the rules above, raising `StrategyError` with a message.
   - Return instances sorted by `order`.
2. `canonical_name` and `run_strategies` (sequential `state = await s.apply(state, ctx)`).
3. `summarize.py` constants:
```python
SUMMARIZER_SYSTEM = "You compress conversation history for an AI agent so it can keep working with less context."
SUMMARIZER_INSTRUCTION = ("Summarize the conversation below. Keep the facts, decisions, tool results and open "
    "tasks the agent needs to continue. Write plain prose or short bullets, at most 300 words.\n\n"
    "<conversation>\n{transcript}\n</conversation>")
SUMMARIZER_PROMPT_HASH = hashlib.sha256((SUMMARIZER_SYSTEM + SUMMARIZER_INSTRUCTION).encode()).hexdigest()[:12]
```
4. `render_transcript(messages) -> str`, one line block per message:
   - system → `SYSTEM: {content}`; user → `USER: {content}`
   - assistant → `ASSISTANT: {content}` (skipped if empty), plus one `ASSISTANT called {name}({arguments})` per tool call
   - tool → `TOOL RESULT: {content}`

   Use `text`-type parts for list content. Separate blocks with `"\n"`.
5. `SummarizeStrategy.apply`:
   - `s, e = state.span`; if `e <= s`, return state unchanged.
   - `model = ctx.agent_model` if summarizer is `same_as_agent`, else the configured summarizer.
   - Call `ctx.llm.complete(model, [{"role": "system", "content": SUMMARIZER_SYSTEM}, {"role": "user", "content": SUMMARIZER_INSTRUCTION.format(transcript=...)}], temperature=ctx.sampling.get("temperature", 0.7), top_p=ctx.sampling.get("top_p"), seed=ctx.sampling.get("seed"), max_tokens=1024)`.
   - Clean the text by removing `<think>.*?</think>` (re.S) and stripping.
   - Summary message: `{"role": "user", "content": f"{SUMMARY_PREFIX}\n{text}"}`. New messages: `messages[:s] + [summary] + messages[e:]`.
   - Return a new state: `span=(s, s+1)`, `summary_text=text`, `llm_tokens += prompt + completion`, `llm_ms += ms`. All other fields carry over.
   - LLM errors propagate (the pipeline turns them into a 502).

## Tests
`tests/test_summarize_composition.py`. Use a fake LLM:
```python
class FakeLLM:
    def __init__(self, text="Summary: user asked to fix payments."): self.text, self.calls = text, []
    async def complete(self, model, messages, *, temperature, top_p=None, seed=None, max_tokens=1024):
        self.calls.append(dict(model=model, messages=messages, temperature=temperature, top_p=top_p, seed=seed))
        return LLMResult(text=self.text, prompt_tokens=100, completion_tokens=20, ms=5.0)
```
Build the context with `KeelConfig()`, `TokenRegistry({})`, `pins=[]`, `agent_model="m1"`, `sampling={"temperature": 0.7, "seed": 3}`.
- `test_parse_canonical_order()`: `canonical_name(parse_strategy("pin+summarize")) == "summarize+pin"`; `"truncate+pin"` stays; `""` and `"none"` → `[]` with name `"none"`.
- `test_parse_errors()`: `"none+pin"`, `"foo"`, `"pin+pin"` and `"validate"` each raise `StrategyError`.
- `test_validate_enabled_adds_validate()`: `parse_strategy("summarize+pin", validate_enabled=True)` gives the name `"summarize+validate+pin"`. With `"truncate"` and validate_enabled, nothing is added.
- `test_summarize_replaces_span()`: messages `[sys, u1, a1, call, tool, u2, a2]` with span (1, 5) → 4 messages: `[sys, summary, u2, a2]`. The summary content starts with `SUMMARY_PREFIX`; `span == (1, 2)`; `llm_tokens == 120`; `evicted` is unchanged.
- `test_summarizer_uses_agent_model_and_sampling()`: the fake call has `model == "m1"`, `temperature == 0.7`, `seed == 3`; the user prompt contains `TOOL RESULT:` and `ASSISTANT called`.
- `test_summarizer_named_model()`: `config.compaction.summarizer = "big"` → `model == "big"`.
- `test_summarize_strips_think()`: fake text `"<think>x</think>\nS"` → `summary_text == "S"`.
- `test_prompt_never_mentions_constraints()`: `SUMMARIZER_SYSTEM + SUMMARIZER_INSTRUCTION`, casefolded, contains none of `constraint`, `rule`, `instruction`, `policy`, `never`.
- `test_run_strategies_sequence()`: `run_strategies(parse_strategy("summarize"), ...)` gives the same result as calling apply directly.

## Acceptance
```bash
uv run pytest tests/test_summarize_composition.py -q
uv run ruff check .
```

## Out of scope
The truncate, validate and pin strategy bodies (T-21, T-29, T-22); pipeline wiring (T-16).

## Depends on
T-04, T-06

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
