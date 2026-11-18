# T-06: Token registry

## Goal
Implement `TokenRegistry`: counts tokens with a model's local Hugging Face `tokenizer.json` when configured, otherwise falls back to ceil(chars/4), and cuts text into head and tail token windows.

## Context
PRD FR-4: count tokens with the upstream model's tokenizer when known; otherwise fall back to characters / 4 and log the fallback. Keel must make no network calls except to configured upstreams, so tokenizers load **only from local file paths** (`config.tokenizers: dict[model, path]`). Never use `from_pretrained`.

Message cost rule: each message costs `count_text(text_of(m)) + 4`; a `tools` list adds `count_text(json.dumps(tools, sort_keys=True))` once.

`text_of` (already in `keel.models`): it returns the content (a str, or text parts joined by "\n") followed by "\n" + name + " " + arguments for each tool call.

Contract:
```python
@dataclass
class TokenCount: n: int; method: Literal["hf", "fallback"]
class TokenRegistry:
    def __init__(self, paths: dict[str, str]) -> None
    def method(self, model: str) -> Literal["hf", "fallback"]
    def count_text(self, model: str, text: str) -> int
    def count_messages(self, model: str, messages: list[Message], tools: list[dict] | None = None) -> TokenCount
    def head_tail(self, model: str, text: str, head: int, tail: int) -> tuple[str, str, int]  # head, tail, removed
```

## Files
Modify: `src/keel/tokens.py`.
Create: `tests/test_tokens.py`.
Read: `src/keel/tokens.py`, `src/keel/models.py`.

## Implement
1. `__init__` stores `paths` and an empty cache `dict[str, Tokenizer | None]`.
2. `_get(model) -> Tokenizer | None`: if `model` is cached, return the cached value. If `model` is not in `paths`, or the file doesn't exist, or `tokenizers.Tokenizer.from_file` raises, cache `None` and log one warning per model via `logging.getLogger("keel")` (`"tokenizer fallback for %s"`). Otherwise cache and return the tokenizer.
3. `method(model)`: `"hf"` if `_get(model)` is not None, else `"fallback"`.
4. `count_text`: an empty string gives 0. HF: `len(tok.encode(text, add_special_tokens=False).ids)`. Fallback: `math.ceil(len(text) / 4)`.
5. `count_messages`: `sum(count_text(model, text_of(m)) + 4 for m in messages)`, plus the tools cost if `tools` is given. Return `TokenCount(n, method(model))`.
6. `head_tail`:
   - HF: `ids = encode(text).ids`. If `len(ids) <= head + tail`, return `(text, "", 0)`. Otherwise `head_text = tok.decode(ids[:head])`, `tail_text = tok.decode(ids[-tail:]) if tail > 0 else ""`, `removed = len(ids) - head - tail`.
   - Fallback: work in characters with `h = head*4` and `t = tail*4`. If `len(text) <= h + t`, return `(text, "", 0)`. Otherwise `head_text = text[:h]`, `tail_text = text[-t:] if t else ""`, `removed = count_text(model, text[h:len(text)-t])`.

## Tests
`tests/test_tokens.py`. Build a tiny local tokenizer in a fixture:
```python
from tokenizers import Tokenizer, models, pre_tokenizers
@pytest.fixture
def tok_path(tmp_path):
    vocab = {"[UNK]": 0, "hello": 1, "world": 2, "a": 3, "b": 4}
    tok = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    p = tmp_path / "tokenizer.json"; tok.save(str(p)); return str(p)
```
- `test_hf_count(tok_path)`: `TokenRegistry({"m": tok_path}).count_text("m", "hello world hello") == 3`, and `method("m") == "hf"`.
- `test_fallback_count()`: registry `{}`; `count_text("x", "abcdefghi") == 3` (ceil(9/4)); `count_text("x", "") == 0`; `method("x") == "fallback"`.
- `test_missing_file_falls_back(tmp_path)`: a path that doesn't exist → `method == "fallback"`, and no exception.
- `test_count_messages_overhead()`: fallback model with two messages of 8 chars each → `n == 2 + 4 + 2 + 4 == 12`; with `tools=[{"a": 1}]` the count grows by `ceil(len(json.dumps([{"a": 1}], sort_keys=True))/4)`.
- `test_head_tail_hf(tok_path)`: text `"a b a b a b a b"` (8 tokens), head 2, tail 1 → `removed == 5`, `head_text.split() == ["a", "b"]`, `tail_text.split() == ["b"]`.
- `test_head_tail_short_text_untouched()`: fallback, text of 10 chars, head 200 → `(text, "", 0)`.
- `test_head_tail_fallback()`: fallback, text `"x"*100`, head 5, tail 5 → head is 20 chars, tail is 20 chars, `removed == 15`.

## Acceptance
```bash
uv run pytest tests/test_tokens.py -q
uv run ruff check .
```

## Out of scope
Network download of tokenizers, the pipeline, and truncate strategy logic.

## Depends on
T-04

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
