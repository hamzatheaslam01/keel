# T-14: Message hashing, prefix cache, compactable span

## Goal
Implement `keel/session.py`: per-message chained hashes, the prefix-cache lookup that swaps an already-compacted prefix for its stored compacted form, and the rule for which span of messages may be compacted.

## Context
The chat API is stateless. The client resends the full history on every request. When Keel compacts, it stores a `CompactionRecord` keyed by a hash of the **raw** message prefix it replaced. On every later request in the session it recognises that prefix and swaps in the stored compacted form. Hashes are per message and chained, so a mismatch shows exactly which message changed. On a mismatch, the caller deactivates stale records and recompacts from the first changed message.

Hard rules (PRD FR-6):
- Never compact the system prompt.
- Never compact the last `keep_last_n` messages.
- Never separate an assistant `tool_calls` message from its `tool` result messages.

```python
class CompactionRecord(BaseModel):   # keel.models
    id: int | None = None; session_id: str; turn_idx: int; strategy: str
    prefix_len: int               # raw[0:prefix_len] is replaced by `compacted`
    prefix_hash: str              # == prefix_hashes[-1]
    prefix_hashes: list[str]      # chained hash of each raw message in the prefix
    tokens_before: int; tokens_after: int; evicted: list[Message]
    compacted: list[Message]      # full replacement incl. system prompt
    summary_text: str | None = None; pins_injected: list[str] = []
    validator: dict[str, Any] | None = None; llm_tokens: int = 0; active: bool = True
```
Contract (`src/keel/session.py`):
```python
def canonical_message(msg: Message) -> str   # json.dumps of {role, content, name, tool_calls,
                                             # tool_call_id} (absent keys omitted),
                                             # sort_keys=True, separators=(",",":"), ensure_ascii=False
def message_hashes(messages: list[Message]) -> list[str]  # h_i = sha256(h_{i-1} + canonical_i), h_-1 = ""
def first_changed_index(hashes: list[str], prefix_hashes: list[str]) -> int
def find_span(messages: list[Message], keep_last_n: int, min_end: int = 0) -> tuple[int, int] | None
@dataclass
class CacheResult:
    working: list[Message]; record: CompactionRecord | None
    status: Literal["none", "hit", "mismatch"]
    stale: list[CompactionRecord]; first_changed: int | None
def apply_cache(raw: list[Message], hashes: list[str], records: list[CompactionRecord]) -> CacheResult
def raw_prefix_len(cache: CacheResult, working_end: int) -> int
```
Rules:
- `message_hashes`: `sha256((prev + canonical).encode("utf-8")).hexdigest()`, starting from `prev = ""`.
- `first_changed_index`: the first `i < min(len(hashes), len(prefix_hashes))` where they differ. If none differ, return `min(len(hashes), len(prefix_hashes))`.
- `find_span`: `start = 1` if `messages` is non-empty and `messages[0]["role"] == "system"`, else 0. `end = len(messages) - keep_last_n`. While `end > start` and `messages[end]["role"] == "tool"`: `end -= 1`. Return `None` if `end <= start` or `end < min_end`; otherwise `(start, end)`.
- `apply_cache`: walk `records` from the longest `prefix_len` to the shortest. A record matches when `len(raw) >= prefix_len` and `hashes[prefix_len-1] == prefix_hash`.
  - The first match gives `working = list(record.compacted) + raw[prefix_len:]`.
  - Status is `"hit"` if the very first (longest) record matched; `"mismatch"` if any longer record failed (those failed records go into `stale`, and `first_changed = first_changed_index(hashes, longest.prefix_hashes)`); `"none"` if there are no records.
  - With records but no match at all: status `"mismatch"`, `working = list(raw)`, `record = None`, every record is stale.
- `raw_prefix_len(cache, working_end)`: `working_end` if `cache.record` is None; else `record.prefix_len + (working_end - len(record.compacted))`. Raise `ValueError` if the result would be < `record.prefix_len`.

## Files
Modify: `src/keel/session.py`.
Create: `tests/test_session_cache.py`.
Read: `src/keel/session.py`, `src/keel/models.py`.

## Implement
Implement each function exactly per the rules. Never mutate the input lists or dicts.

## Tests
`tests/test_session_cache.py`. Helpers: `u(t)`, `a(t)`, `sys(t)` build plain messages. `call(id, name)` builds an assistant message with one tool_call; `tool(id, t)` builds a tool message. Use `rec(raw, prefix_len, compacted)` to build a `CompactionRecord` from `message_hashes(raw)`.
- `test_hash_stable_and_chained()`: equal lists give equal hashes. Changing message 2 changes hashes[2:] but not hashes[:2]. Key order inside a message dict doesn't matter. An extra unknown key (e.g. `"reasoning_content"`) doesn't change the hash.
- `test_first_changed_index()`.
- `test_find_span_basic()`: `[sys, u, a, u, a, u, a]` with keep 4 → `(1, 3)`.
- `test_find_span_no_system()`: `[u, a, u, a, u, a]` with keep 2 → `(0, 4)`.
- `test_find_span_keeps_tool_group()`: `[sys, u, call(c1), tool(c1), tool2(c1), a, u]` with keep 3: `end = 4`; messages[4] is a tool and messages[3] is a tool, so end moves to 2 (the call message) → `(1, 2)`.
- `test_find_span_none_when_too_short()`: `[sys, u, a]` with keep 4 → None. With `min_end=5` on a long list where the end would be 4 → None.
- `test_apply_cache_none()`: no records → status `none`, `working == raw`.
- `test_apply_cache_hit()`: raw has 10 messages; a record with `prefix_len 6` and `compacted [sys, summary]`; the next request is raw plus 2 more messages → working = `[sys, summary] + raw[6:12]`, status `hit`.
- `test_apply_cache_mismatch_falls_back()`: two records (prefix_len 4 and 8). Edit message 6 → match on the 4-record, status `mismatch`, the stale list holds the 8-record, `first_changed == 6`.
- `test_apply_cache_mismatch_no_match()`: edit message 1 → `record is None`, `working == raw`, both records stale.
- `test_apply_cache_shorter_raw_is_mismatch()`: raw shorter than prefix_len → mismatch.
- `test_raw_prefix_len_chained()`: a cache hit with a record of prefix_len 6 and compacted length 2. A working end of 5 maps to raw prefix 9. With no record, it maps to working_end.

## Acceptance
```bash
uv run pytest tests/test_session_cache.py -q
uv run ruff check .
```

## Out of scope
Storing or deactivating records (pipeline, T-16) and strategies.

## Depends on
T-04

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
