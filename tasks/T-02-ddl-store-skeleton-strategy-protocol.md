# T-02: SQLite DDL, Store skeleton, Strategy protocol

## Goal
Fix the SQLite schema and the Strategy protocol in code: the full DDL, a `Store` class whose methods are stubs, the strategy base types, and the example config file.

## Context
Keel stores traces in SQLite (stdlib `sqlite3`). The strategy layer composes compaction strategies with `+` (e.g. `summarize+pin`). This task writes contracts only. Method bodies stay `raise NotImplementedError` except `Store.__init__` and `Store.close`.

`Message = dict[str, Any]`; `Pin`, `CompactionRecord`, `RequestRecord`, `RunInfo`, `Episode` live in `keel.models`; `KeelConfig` lives in `keel.config` (both from T-01).

DDL (store it as the module constant `DDL: str`, executed with `executescript`):
```sql
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, config_json TEXT NOT NULL,
  extracted_upto INTEGER NOT NULL DEFAULT 0, extracted_hash TEXT);
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT REFERENCES sessions(id),
  turn_idx INTEGER NOT NULL, upstream_model TEXT NOT NULL, status INTEGER NOT NULL,
  cache_status TEXT NOT NULL, compacted INTEGER NOT NULL DEFAULT 0, tokenizer TEXT NOT NULL,
  tokens_in_raw INTEGER NOT NULL, tokens_in_sent INTEGER NOT NULL, tokens_out INTEGER,
  pin_tokens INTEGER NOT NULL DEFAULT 0, proxy_ms REAL NOT NULL, upstream_ms REAL NOT NULL,
  llm_ms REAL NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_requests_session ON requests(session_id, turn_idx);
CREATE TABLE IF NOT EXISTS compactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
  turn_idx INTEGER NOT NULL, strategy TEXT NOT NULL, prefix_len INTEGER NOT NULL,
  prefix_hash TEXT NOT NULL, prefix_hashes_json TEXT NOT NULL,
  tokens_before INTEGER NOT NULL, tokens_after INTEGER NOT NULL,
  evicted_json TEXT NOT NULL, compacted_json TEXT NOT NULL, summary_text TEXT,
  pins_injected_json TEXT NOT NULL DEFAULT '[]', validator_json TEXT,
  llm_tokens INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_compactions_session ON compactions(session_id, active);
CREATE TABLE IF NOT EXISTS pins (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
  text TEXT NOT NULL, source TEXT NOT NULL CHECK (source IN ('explicit','auto')),
  source_turn INTEGER, confidence REAL NOT NULL DEFAULT 1.0,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, started_at TEXT NOT NULL, git_sha TEXT NOT NULL, config_json TEXT NOT NULL,
  model_hashes_json TEXT NOT NULL, seeds_json TEXT NOT NULL, args_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
  scenario_id TEXT NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL, condition TEXT NOT NULL,
  seed INTEGER NOT NULL, violated INTEGER NOT NULL, constraint_survived INTEGER,
  summary_survived INTEGER, task_done INTEGER NOT NULL, validator_missing INTEGER,
  auto_pins_total INTEGER, auto_pins_tp INTEGER, session_id TEXT NOT NULL,
  probe_json TEXT NOT NULL DEFAULT '[]', error TEXT, created_at TEXT NOT NULL,
  UNIQUE (run_id, scenario_id, model, condition, seed));
```

Store contract (signatures only in this task):
```python
class Store:   # one sqlite3 connection, check_same_thread=False, guarded by threading.Lock
    def __init__(self, path: str) -> None          # ":memory:" allowed; runs DDL
    def close(self) -> None
    def ensure_session(self, session_id: str, config: dict[str, Any]) -> None
    def get_session(self, session_id: str) -> dict[str, Any] | None
    def set_extracted(self, session_id: str, upto: int, last_hash: str | None) -> None
    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]
    def next_turn_idx(self, session_id: str) -> int
    def insert_request(self, rec: RequestRecord) -> int
    def list_requests(self, session_id: str) -> list[dict[str, Any]]
    def insert_compaction(self, rec: CompactionRecord) -> int
    def active_compactions(self, session_id: str) -> list[CompactionRecord]   # prefix_len asc
    def list_compactions(self, session_id: str) -> list[CompactionRecord]     # all, id asc
    def deactivate_compactions(self, ids: list[int]) -> None
    def add_pin(self, pin: Pin) -> Pin
    def list_pins(self, session_id: str, active_only: bool = False) -> list[Pin]
    def deactivate_pin(self, session_id: str, pin_id: int) -> bool
    def insert_run(self, run: RunInfo) -> None
    def get_run(self, run_id: str) -> RunInfo | None
    def episode_exists(self, run_id: str, scenario_id: str, model: str, condition: str, seed: int) -> bool
    def insert_episode(self, ep: Episode) -> int
    def list_episodes(self, run_id: str) -> list[Episode]
    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]
```

Strategy contract (`src/keel/strategies/base.py`):
```python
class LLMResult(BaseModel):
    text: str; prompt_tokens: int; completion_tokens: int; ms: float
class LLMClient(Protocol):
    async def complete(self, model: str, messages: list[Message], *, temperature: float,
                       top_p: float | None = None, seed: int | None = None,
                       max_tokens: int = 1024) -> LLMResult: ...
@dataclass
class CompactionState:
    messages: list[Message]        # working list being rewritten (whole request)
    span: tuple[int, int]          # [start, end) the strategy may rewrite
    evicted: list[Message]         # copy of original messages[start:end]
    summary_text: str | None = None; validator: dict[str, Any] | None = None
    pins_to_inject: bool = False; llm_tokens: int = 0; llm_ms: float = 0.0
@dataclass
class StrategyContext:
    session_id: str; agent_model: str
    sampling: dict[str, Any]       # temperature/top_p/seed from the request (may be empty)
    config: KeelConfig; pins: list[Pin]; tokens: TokenRegistry; llm: LLMClient
class Strategy(Protocol):
    name: ClassVar[str]; order: ClassVar[int]   # truncate 10, summarize 20, validate 30, pin 40
    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState: ...
class StrategyError(ValueError): ...
def parse_strategy(spec: str, validate_enabled: bool = False) -> list[Strategy]
def canonical_name(strategies: list[Strategy]) -> str     # "none" when empty
async def run_strategies(strategies: list[Strategy], state: CompactionState,
                         ctx: StrategyContext) -> CompactionState
```
`TokenRegistry` (in `keel.tokens`) doesn't exist yet. Import it under `if TYPE_CHECKING:` and use `from __future__ import annotations`.

Example config (`keel.example.yaml`), the PRD config plus the Keel-specific fields:
```yaml
server: {host: 127.0.0.1, port: 8400, db: keel.db}
upstreams:
  - name: local
    base_url: http://127.0.0.1:8080/v1     # llama.cpp server
    models: [qwen3-1.7b, qwen3-4b]
    extra_body: {chat_template_kwargs: {enable_thinking: false}}
  - name: hosted
    base_url: ${HOSTED_BASE_URL}
    api_key: ${HOSTED_API_KEY}
    models: [hosted-small]
compaction:
  strategy: summarize+pin
  trigger_tokens: 6000
  keep_last_n: 4
  truncate: {older_than_turns: 3, head_tokens: 200, tail_tokens: 100}
  summarizer: same_as_agent
pins:
  auto_extract: false
  extractor_model: qwen3-1.7b
  min_confidence: 0.6
validate:
  enabled: false
  judge_model: qwen3-1.7b
tokenizers:            # local tokenizer.json files; missing -> chars/4 fallback
  qwen3-1.7b: models/qwen3-1.7b/tokenizer.json
  qwen3-4b: models/qwen3-4b/tokenizer.json
model_files:           # hashed into every benchmark run
  qwen3-1.7b: models/Qwen3-1.7B-Q4_K_M.gguf
  qwen3-4b: models/Qwen3-4B-Q4_K_M.gguf
```

## Files
Create:
- `src/keel/store.py`
- `src/keel/strategies/__init__.py` (empty)
- `src/keel/strategies/base.py`
- `keel.example.yaml`
- `tests/test_store_schema.py`

Read: `src/keel/models.py`, `src/keel/config.py`.

## Implement
1. `store.py`: the `DDL` constant exactly as above, plus a `utcnow() -> str` helper returning `datetime.now(timezone.utc).isoformat()`.
2. `Store.__init__`: `sqlite3.connect(path, check_same_thread=False)`, `row_factory = sqlite3.Row`, `executescript(DDL)`, and for file DBs `PRAGMA journal_mode=WAL` (skip for `":memory:"`). Keep `self._lock = threading.Lock()`. `close()` closes the connection.
3. Every other `Store` method: the exact signature with docstring, and a body of `raise NotImplementedError("T-08")`.
4. `base.py`: all classes and functions from the contract. `parse_strategy`, `canonical_name` and `run_strategies` have the body `raise NotImplementedError("T-15")`.
5. `keel.example.yaml` exactly as above.

## Tests
`tests/test_store_schema.py`:
- `test_ddl_creates_tables()`: `Store(":memory:")`, query `sqlite_master` and assert the table set ⊇ {sessions, requests, compactions, pins, runs, episodes}.
- `test_init_idempotent(tmp_path)`: open `Store(str(tmp_path/"k.db"))` twice (close the first). No error.
- `test_episode_unique(tmp_path)`: insert a run row and then the same episode row twice with raw SQL via `store._conn`. The second insert raises `sqlite3.IntegrityError`.
- `test_pin_source_check()`: a raw insert with `source='oracle'` raises `sqlite3.IntegrityError`.
- `test_compaction_state_defaults()`: `CompactionState(messages=[], span=(0, 0), evicted=[])` has `pins_to_inject is False`, `llm_tokens == 0`.
- `test_example_config_loads()`: `load_config("keel.example.yaml")` succeeds. `HOSTED_BASE_URL` is unset, so 1 upstream remains, and `cfg.tokenizers["qwen3-1.7b"]` ends with `tokenizer.json`.

## Acceptance
```bash
uv run pytest tests/test_store_schema.py -q
uv run ruff check .
```

## Out of scope
Implementing Store queries (T-08) or composition (T-15). Don't edit `config.py` or `models.py`.

## Depends on
T-01

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
