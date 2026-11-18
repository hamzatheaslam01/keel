# T-08: Store implementation

## Goal
Implement every `Store` method: the SQLite reads and writes for sessions, requests, compactions, pins, runs and episodes.

## Context
The DDL already exists in `src/keel/store.py` (T-02), along with `utcnow()`, the connection (`self._conn`, `row_factory=sqlite3.Row`) and `self._lock`. Every method stub currently raises `NotImplementedError`.

Storage rules:
- Timestamps are `utcnow()` ISO strings.
- JSON columns use `json.dumps(x, ensure_ascii=False)` and are read back with `json.loads`.
- Booleans are stored as 0/1 and returned as `bool` in models.
- Wrap each write in `with self._lock:` and commit.
- Foreign keys are **not** enforced: don't enable `PRAGMA foreign_keys`.

Models (from `keel.models`):
```python
class Pin(BaseModel):
    id: int | None = None; session_id: str; text: str
    source: Literal["explicit", "auto"] = "explicit"; source_turn: int | None = None
    confidence: float = 1.0; active: bool = True
class CompactionRecord(BaseModel):
    id: int | None = None; session_id: str; turn_idx: int; strategy: str
    prefix_len: int; prefix_hash: str; prefix_hashes: list[str]
    tokens_before: int; tokens_after: int; evicted: list[Message]; compacted: list[Message]
    summary_text: str | None = None; pins_injected: list[str] = []
    validator: dict[str, Any] | None = None; llm_tokens: int = 0; active: bool = True
class RequestRecord(BaseModel):
    session_id: str | None; turn_idx: int; upstream_model: str; status: int
    cache_status: Literal["passthrough", "none", "hit", "mismatch"]
    compacted: bool = False; tokenizer: Literal["hf", "fallback"]
    tokens_in_raw: int; tokens_in_sent: int; tokens_out: int | None = None
    pin_tokens: int = 0; proxy_ms: float; upstream_ms: float; llm_ms: float = 0.0
    error: str | None = None
class RunInfo(BaseModel):
    id: str; started_at: str; git_sha: str; config: dict[str, Any]
    model_hashes: dict[str, str]; seeds: list[int]; args: dict[str, Any]
class Episode(BaseModel):
    run_id: str; scenario_id: str; kind: Literal["hard", "soft"]; model: str
    condition: str; seed: int; session_id: str
    violated: bool = False; task_done: bool = False
    constraint_survived: bool | None = None; summary_survived: bool | None = None
    validator_missing: int | None = None
    auto_pins_total: int | None = None; auto_pins_tp: int | None = None
    probe: list[Message] = []; error: str | None = None
```
Column mapping: `CompactionRecord.prefix_hashes` → `prefix_hashes_json`, `evicted` → `evicted_json`, `compacted` → `compacted_json`, `pins_injected` → `pins_injected_json`, `validator` → `validator_json` (NULL when None). `RunInfo.config` → `config_json`, `model_hashes` → `model_hashes_json`, `seeds` → `seeds_json`, `args` → `args_json`. `Episode.probe` → `probe_json`.

## Files
Modify: `src/keel/store.py`.
Create: `tests/test_store.py`.
Read: `src/keel/store.py`, `src/keel/models.py`.

## Implement
1. `ensure_session`: `INSERT OR IGNORE` with `config_json=json.dumps(config)`. An existing session keeps its config.
2. `get_session`: a dict with keys `id, created_at, config` (parsed), `extracted_upto, extracted_hash`, or None.
3. `set_extracted`: update both extraction columns.
4. `list_sessions(limit)`: dicts `{id, created_at, n_requests, n_compactions}` ordered `created_at DESC, rowid DESC`, built with correlated `COUNT(*)` subqueries.
5. `next_turn_idx`: `SELECT COUNT(*) FROM requests WHERE session_id=?`.
6. `insert_request`: insert all fields plus `created_at`; return `lastrowid`. `list_requests`: `ORDER BY id`, rows as plain dicts.
7. `insert_compaction`: return the id. `active_compactions`: `active=1 ORDER BY prefix_len ASC, id ASC`. `list_compactions`: all rows `ORDER BY id`. Both return `CompactionRecord` with `id` set. `deactivate_compactions(ids)`: `UPDATE ... SET active=0 WHERE id IN (...)`; an empty list does nothing.
8. `add_pin`: if an active pin with the same `session_id` and `text` exists, return it (with id). Otherwise insert and return the pin with its new id. `list_pins`: `ORDER BY id`, filtered by `active_only`. `deactivate_pin`: returns True only if a row in that session changed.
9. `insert_run`: `INSERT OR IGNORE` (resume-safe). `get_run`: rebuild `RunInfo` or None.
10. `episode_exists`: an `EXISTS` query on the unique key. `insert_episode`: plain insert (an `IntegrityError` propagates); return the id. `list_episodes(run_id)`: `ORDER BY id`, rebuilt as `Episode` (nullable booleans: NULL→None, 0/1→bool).
11. `query(sql, params)`: run it, return `[dict(r) for r in rows]`.

## Tests
`tests/test_store.py` with fixture `store = Store(":memory:")`:
- `test_session_roundtrip_and_ignore()`: calling `ensure_session("s1", {"a": 1})` twice, the second time with `{"a": 2}`, leaves the config `{"a": 1}`.
- `test_set_extracted()`.
- `test_requests_and_turn_idx()`: insert 2 requests → `next_turn_idx == 2`, `list_requests` has 2 rows, and the first row's `cache_status` matches what was inserted.
- `test_list_sessions_counts_newest_first()`: two sessions; the second is created later, so it comes first; it has 1 request and 1 compaction.
- `test_compaction_roundtrip()`: insert a record with `evicted=[{"role":"user","content":"x"}]` and `validator=None`. Read it back with `active_compactions`: equal fields, `id` set, `validator is None`.
- `test_active_order_and_deactivate()`: records with `prefix_len` 9 and 5 → the active order is [5, 9]. Deactivating the first leaves only 9 active; `list_compactions` still returns both.
- `test_add_pin_dedupes_active()`: the same text twice → the same id. After `deactivate_pin`, adding it again → a new id. `deactivate_pin("other", id)` → False.
- `test_run_roundtrip_and_ignore()`.
- `test_episode_roundtrip_nullable()`: `constraint_survived=None` and `summary_survived=False` survive the round trip; `probe` is a list of dicts; `episode_exists` is True; inserting a duplicate raises `sqlite3.IntegrityError`.
- `test_query_helper()`.

## Acceptance
```bash
uv run pytest tests/test_store.py tests/test_store_schema.py -q
uv run ruff check .
```

## Out of scope
Changing the DDL. Pipeline and API code.

## Depends on
T-04

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
