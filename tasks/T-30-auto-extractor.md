# T-30: Auto pin extractor

## Goal
Implement `keel/extract.py`: classify user and tool messages for standing instructions using the fixed small extractor model, returning candidate pins with confidence.

## Context
PRD FR-15: the auto-extractor classifies new user and tool messages for standing instructions and stores them as auto pins with confidence (storage is T-31). Constraints can arrive in user turns **and tool outputs**, not just the system prompt.

The extractor model is fixed across conditions (default `qwen3-1.7b`), called with **temperature 0, seed 0**, and makes one call per user/tool message. Input text is cut to `max_input_chars`, keeping the beginning, since constraint lines sit before bulky filler.

Contract:
```python
class Candidate(BaseModel): text: str; confidence: float
def parse_candidates(text: str) -> list[Candidate]
async def extract_constraints(messages: list[Message], llm: LLMClient, model: str,
                              max_input_chars: int) -> tuple[list[Candidate], float, int]  # cands, ms, tokens
# LLMClient.complete(model, messages, *, temperature, top_p=None, seed=None, max_tokens=1024) -> LLMResult(text, prompt_tokens, completion_tokens, ms)
# keel.models.text_of(msg) -> str
```
Prompt (write it exactly):
```python
EXTRACTOR_SYSTEM = ("You find standing instructions in messages. A standing instruction is a rule, restriction "
    "or policy meant to apply to future actions (for example: never do X, always do Y, only use Z). "
    "One-off requests are not standing instructions. Answer only with JSON.")
EXTRACTOR_USER = ("Message ({role}):\n<message>\n{text}\n</message>\n\n"
    'Reply with JSON only: {{"instructions": [{{"text": "<the instruction, copied verbatim>", '
    '"confidence": <number from 0 to 1>}}]}}. Use an empty list if there are none.')
```

## Files
Modify: `src/keel/extract.py`.
Create: `tests/test_extract.py`.
Read: `src/keel/extract.py`, `src/keel/strategies/base.py`, `src/keel/models.py`.

## Implement
1. `parse_candidates(text)`:
   - Strip `<think>.*?</think>`, find `re.search(r"\{[\s\S]*\}", ...)`, `json.loads`. Any failure → `[]`.
   - Take `data.get("instructions")` if it's a list. For each item that's a dict with a non-blank str `text`: confidence = `float(item.get("confidence", 0.5))`, clamped to [0, 1]; a non-numeric value → 0.5.
   - De-duplicate by `text.strip().casefold()`, keeping the first. Return the candidates with stripped text.
2. `extract_constraints`:
   - For each message with `role in ("user", "tool")` and a non-blank `text_of(m)`: `text = text_of(m)[:max_input_chars]`.
   - Call `llm.complete(model, [system, user], temperature=0.0, seed=0, max_tokens=512)`. Accumulate `ms` and `prompt + completion` tokens; extend the candidates with `parse_candidates(result.text)`.
   - Skip other roles entirely (no call). Return `(candidates, ms, tokens)`. LLM errors propagate.

## Tests
`tests/test_extract.py` with a FakeLLM that returns queued texts and records calls:
- `test_parse_basic()`: `'{"instructions": [{"text": "Never deploy to prod.", "confidence": 0.9}]}'` → 1 candidate, conf 0.9.
- `test_parse_clamps_and_defaults()`: conf 1.7 → 1.0; a missing conf → 0.5; `"high"` → 0.5.
- `test_parse_garbage()`: `"no json here"` → `[]`; `'{"instructions": "x"}'` → `[]`.
- `test_parse_dedupes_and_strips_think()`.
- `test_only_user_and_tool_messages()`: messages [system, user, assistant, tool] → 2 calls; the second call's prompt contains `"Message (tool)"`.
- `test_truncates_input()`: a tool message of 20,000 chars with `max_input_chars=100` → the prompt's `<message>` block holds exactly the first 100 chars.
- `test_fixed_sampling()`: each call has `temperature == 0.0`, `seed == 0`, `model == "judge"`.
- `test_returns_ms_and_tokens()`.

## Acceptance
```bash
uv run pytest tests/test_extract.py -q
uv run ruff check .
```

## Out of scope
Storing pins and the pipeline hook (T-31).

## Depends on
T-04, T-07

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
