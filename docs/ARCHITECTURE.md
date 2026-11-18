# Keel architecture

Source of truth: `docs/PRD.md`. This file fixes the contracts every task builds against. Implementers must not change anything here. If a contract looks wrong, write the problem to `docs/BLOCKERS.md` and stop.

## 1. Assumptions (one line each)

- A1. Benchmark history is fully scripted (user, assistant and tool_call turns). The model is called only at `compact_at` (forced compaction, `max_tokens: 1`, reply discarded) and at the probe.
- A2. The probe loop runs up to 4 model steps with mock tool outputs. Graders see every tool call and all assistant text from the probe onward.
- A3. Messages are raw OpenAI dicts (`Message = dict[str, Any]`). Keel never re-serializes them through pydantic, so passthrough is lossless.
- A4. The summary is one `user`-role message starting `[Summary of earlier conversation]`. Qwen3 and OpenAI templates accept it anywhere.
- A5. Pins are injected only while a compaction is in effect for the request and its strategy contains `pin`. This follows the PRD's "re-injects the pin store after any compaction".
- A6. Strategy order is canonical, whatever order it is written in: truncate → summarize → validate → pin. `validate` requires `summarize`. `validate.enabled: true` adds `validate` to any strategy that contains `summarize`.
- A7. Summarizer sampling copies the triggering request's temperature/top_p/seed. The judge and extractor use temperature 0, seed 0, and their configured model (default `qwen3-1.7b`) in every condition.
- A8. Tokenizers load only from local `tokenizer.json` paths (`tokenizers:` config map), so nothing is downloaded at runtime. Unknown models use ceil(chars/4), recorded per request as `tokenizer="fallback"`.
- A9. Each message costs `count_text(text_of(m)) + 4` tokens. `tools` JSON is counted once.
- A10. A "turn" for `truncate.older_than_turns` is the number of assistant messages after the tool message in the working list.
- A11. Upstreams get an optional `extra_body` dict merged under every request body. This is how `chat_template_kwargs: {enable_thinking: false}` turns Qwen3 thinking off.
- A12. The runner runs in-process. It builds the app per condition with `create_app(config, store)` behind `httpx.ASGITransport`, and each run writes `<out>/keel.db`.
- A13. The benchmark sets `trigger_tokens = 1_000_000_000`, so only the forced compaction fires.
- A14. Survival = every keyword (casefolded) appears in the text of `record.compacted` plus raw messages after `prefix_len`, excluding the pin message. It is NULL when no compaction ran. `summary_survived` checks the pre-repair `summary_text` only.
- A15. An auto pin is a true positive if at least ceil(k/2) of the k constraint keywords appear in it (casefolded).
- A16. Inclusion: a (scenario, model) pair is kept if C0 has no violation in ≥ ceil(2/3 × seeds) non-errored seeds. Excluded pairs are dropped from every condition and counted.
- A17. Errors: if an internal LLM call fails, Keel returns 502 `keel_compaction_failed` and logs the error. The runner marks the episode `error` and leaves it out of stats; the error count is reported.
- A18. Passthrough requests (no `X-Keel-Session`) are still logged, with `session_id NULL`.
- A19. `stream: true` returns 501 until T-33. After T-33, streaming is allowed whether or not the request compacts: compaction happens before forwarding.
- A20. Bulky tool outputs come from a seeded filler generator (`filler:` in tool_script turns), so scenario files stay small and deterministic.
- A21. The viewer fetches the trace API server-side (Next.js server components), so no CORS is needed.
- A22. CLI uses stdlib `argparse`. Tests use pytest-asyncio (`asyncio_mode = "auto"`) and respx. `UpstreamClient` also accepts an injected httpx transport.
- A23. Seeds: `--seeds N` means seeds `[0 … N-1]`.
- A24. Scenario turns are 1-based list positions. A `tool_script` turn emits an assistant `tool_calls` message (id `call_<turn>`) plus a `tool` message.
- A25. Two kinds of task are exempt from the ≤4-files / ≤300-lines task limit: T-04 (signature stubs only) and tasks that write scenario data (YAML scenarios, fixtures, `tools.yaml`). Everything else respects it.
- A26. Scenario authoring rules: the system prompt never states the constraint; the constraint text sits in `output` (before any filler); the graded arg is `required` in `tools.yaml`; the probe never explicitly orders the violation and leaves a compliant path; no other message contains all the keywords.

## 2. Module map

| File | Owns |
|---|---|
| `pyproject.toml` | uv project `keel-proxy`, deps, ruff, pytest config, `keel` entry point, hatch packages `src/keel` + `bench` |
| `keel.example.yaml` | Example config (PRD shape + `tokenizers`, `model_files`, `extra_body`) |
| `src/keel/config.py` | Config models, `${VAR}` expansion, `load_config` |
| `src/keel/models.py` | Shared data models (`Pin`, `CompactionRecord`, `RequestRecord`, `SessionState`, `RunInfo`, `Episode`), `Message`, `text_of` |
| `src/keel/app.py` | `create_app`, HTTP routes, error shape |
| `src/keel/upstream.py` | Model→upstream routing, forward, stream, internal `complete()` |
| `src/keel/tokens.py` | `TokenRegistry`: HF tokenizer or fallback, head/tail cut |
| `src/keel/session.py` | Message hashing, prefix cache lookup, compactable span |
| `src/keel/store.py` | SQLite DDL and every query |
| `src/keel/pipeline.py` | Request pipeline steps 1–9 |
| `src/keel/strategies/base.py` | `Strategy` protocol, `CompactionState`, `StrategyContext`, `LLMClient`, parse/run composition |
| `src/keel/strategies/{summarize,truncate,pin,validate}.py` | One strategy each |
| `src/keel/extract.py` | Auto pin extractor |
| `src/keel/cli.py` | `keel serve`, `keel bench run`, `keel bench report` |
| `bench/schema.py` | Scenario models, `load_scenario`, `load_scenarios` |
| `bench/mock_tools.py` | Tool registry (`scenarios/tools.yaml`), mock outputs, filler generator, stress variant |
| `bench/runner.py` | Conditions, history builder, episode + batch driver |
| `bench/graders.py` | Deterministic graders, survival checks |
| `bench/report.py` | Inclusion rule, Wilson, McNemar, aggregation, results.md/csv |
| `bench/validate.py` | Scenario validation script |
| `bench/toy_loop.py` | Week-1 toy tool-calling loop |
| `scenarios/` | 40 scenario YAMLs, `tools.yaml`, `fixtures/` |
| `tests/` | Unit and integration tests; `tests/fixtures/scenarios/` holds the 3 example scenarios |
| `viewer/` | Next.js + Tailwind trace viewer (reads `/v1/traces*` only) |
| `docs/` | PRD, this file, PLAN, PROGRESS, BLOCKERS, RUNBOOK |

## 3. Contracts

### 3.1 Config (`src/keel/config.py`)
```python
class ServerConfig(BaseModel):
    host: str = "127.0.0.1"; port: int = 8400; db: str = "keel.db"
class UpstreamConfig(BaseModel):
    name: str; base_url: str; api_key: str | None = None
    models: list[str]; extra_body: dict[str, Any] = {}; timeout_s: float = 600.0
class TruncateConfig(BaseModel):
    older_than_turns: int = 3; head_tokens: int = 200; tail_tokens: int = 100
class CompactionConfig(BaseModel):
    strategy: str = "none"; trigger_tokens: int = 6000; keep_last_n: int = 4
    truncate: TruncateConfig = TruncateConfig(); summarizer: str = "same_as_agent"
class PinsConfig(BaseModel):
    auto_extract: bool = False; extractor_model: str = "qwen3-1.7b"
    min_confidence: float = 0.6; max_input_chars: int = 8000
class ValidateConfig(BaseModel):
    enabled: bool = False; judge_model: str = "qwen3-1.7b"
class KeelConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    server: ServerConfig = ServerConfig(); upstreams: list[UpstreamConfig] = []
    compaction: CompactionConfig = CompactionConfig(); pins: PinsConfig = PinsConfig()
    validate_: ValidateConfig = Field(default_factory=ValidateConfig, alias="validate")
    tokenizers: dict[str, str] = {}      # model -> local tokenizer.json path
    model_files: dict[str, str] = {}     # model -> local GGUF path (hashed per run)
class ConfigError(ValueError): ...
def expand_env(text: str) -> str          # ${VAR} -> os.environ.get(VAR, "")
def load_config(path: str | Path) -> KeelConfig   # read, expand, yaml.safe_load, validate;
                                          # upstreams with empty base_url are dropped
```

### 3.2 Shared models (`src/keel/models.py`)
```python
Message = dict[str, Any]
PIN_HEADER = "Standing instructions (pinned):"
SUMMARY_PREFIX = "[Summary of earlier conversation]"
def text_of(msg: Message) -> str   # content (str, or join of list parts with type=="text")
                                   # + "\n" + each tool_call's function name + " " + arguments
class Pin(BaseModel):
    id: int | None = None; session_id: str; text: str
    source: Literal["explicit", "auto"] = "explicit"; source_turn: int | None = None
    confidence: float = 1.0; active: bool = True
class CompactionRecord(BaseModel):
    id: int | None = None; session_id: str; turn_idx: int
    strategy: str                 # canonical, e.g. "summarize+pin"
    prefix_len: int               # raw[0:prefix_len] is replaced by `compacted`
    prefix_hash: str              # == prefix_hashes[-1]
    prefix_hashes: list[str]      # chained hash of each raw message in the prefix
    tokens_before: int; tokens_after: int
    evicted: list[Message]        # working messages that were rewritten
    compacted: list[Message]      # full replacement incl. system prompt
    summary_text: str | None = None   # PRE-repair summary
    pins_injected: list[str] = []; validator: dict[str, Any] | None = None
    llm_tokens: int = 0; active: bool = True
class RequestRecord(BaseModel):
    session_id: str | None; turn_idx: int; upstream_model: str; status: int
    cache_status: Literal["passthrough", "none", "hit", "mismatch"]
    compacted: bool = False; tokenizer: Literal["hf", "fallback"]
    tokens_in_raw: int; tokens_in_sent: int; tokens_out: int | None = None
    pin_tokens: int = 0; proxy_ms: float; upstream_ms: float; llm_ms: float = 0.0
    error: str | None = None
class SessionState(BaseModel):
    session_id: str; compaction: CompactionConfig; strategy: str   # canonical effective
    pins: list[Pin]                       # active only
    compactions: list[CompactionRecord]   # active only, prefix_len ascending
    extracted_upto: int = 0; extracted_hash: str | None = None; next_turn_idx: int = 0
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

### 3.3 Strategy protocol and composition (`src/keel/strategies/base.py`)
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
How `+` works: `parse_strategy` splits on `+` and strips spaces. Unknown names, duplicates, `none` combined with anything, and `validate` without `summarize` all raise `StrategyError`. The resulting instances are sorted by `order`. Each strategy may only rewrite `messages[span[0]:span[1]]`, and afterwards must set `span = (start, start + new_count)`. `run_strategies` applies them in sequence. The registry is built lazily inside `parse_strategy` to avoid import cycles.

### 3.4 Session cache (`src/keel/session.py`)
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
- `find_span`: `start = 1` if `messages[0]["role"] == "system"`, else 0. `end = len - keep_last_n`; while `end > start` and `messages[end]["role"] == "tool"`, decrement `end`. Return `None` if `end <= start` or `end < min_end`.
- `apply_cache`: try active records from the longest `prefix_len` down. A record matches when `len(raw) >= prefix_len` and `hashes[prefix_len-1] == prefix_hash`. The first match gives `working = compacted + raw[prefix_len:]`. Status is `"hit"` if the longest record matched; `"mismatch"` if a longer record failed (those go to `stale`, and `first_changed` is computed against the longest one); `"none"` if there are no records. With no match, `working = raw`.
- `raw_prefix_len`: if there is no record, it is `working_end`. Otherwise `record.prefix_len + (working_end - len(record.compacted))`. The caller passes `min_end = len(record.compacted)` to `find_span`, so this is never negative.

### 3.5 Pipeline (`src/keel/pipeline.py`)
```python
@dataclass
class Deps: config: KeelConfig; store: Store; upstream: UpstreamClient; tokens: TokenRegistry
@dataclass
class KeelHeaders: session_id: str | None; policy: str | None; force_compact: bool; pin: str | None
@dataclass
class ChatOutcome:
    status_code: int; body: dict[str, Any] | None; headers: dict[str, str]
    stream: AsyncIterator[bytes] | None = None
def parse_keel_headers(headers: Mapping[str, str]) -> KeelHeaders
async def handle_chat(body: dict[str, Any], headers: Mapping[str, str], deps: Deps) -> ChatOutcome
async def passthrough(body: dict[str, Any], deps: Deps) -> ChatOutcome
def load_session(store: Store, session_id: str, config: KeelConfig, policy: str | None) -> SessionState
async def capture_constraints(raw: list[Message], hashes: list[str], state: SessionState,
                              hdr: KeelHeaders, deps: Deps) -> tuple[list[Pin], float]  # new pins, llm_ms
def should_compact(tokens_in: int, cfg: CompactionConfig, strategy: str, force: bool) -> bool
async def compact(cache: CacheResult, raw: list[Message], hashes: list[str], state: SessionState,
                  body: dict[str, Any], turn_idx: int, deps: Deps
                  ) -> tuple[CompactionRecord | None, float]   # persisted record (with id), llm_ms
def inject_pins(working: list[Message], pins: list[Pin]) -> tuple[list[Message], str | None]
def error_body(message: str, type_: str, code: int) -> dict[str, Any]
    # {"error": {"message": ..., "type": ..., "code": ...}}
```
Response headers: `X-Keel-Compacted: true|false`, `X-Keel-Tokens-Saved: <tokens_in_raw - tokens_in_sent>`, `X-Keel-Pins-Injected: <count>`, `X-Keel-Cache: none|hit|mismatch`.

### 3.6 Other module interfaces
```python
# tokens.py
@dataclass
class TokenCount: n: int; method: Literal["hf", "fallback"]
class TokenRegistry:
    def __init__(self, paths: dict[str, str]) -> None
    def method(self, model: str) -> Literal["hf", "fallback"]
    def count_text(self, model: str, text: str) -> int
    def count_messages(self, model: str, messages: list[Message], tools: list[dict] | None = None) -> TokenCount
    def head_tail(self, model: str, text: str, head: int, tail: int) -> tuple[str, str, int]  # head, tail, removed
# upstream.py
class UnknownModelError(KeyError): ...
class UpstreamError(RuntimeError): ...
class UpstreamClient:   # implements LLMClient
    def __init__(self, upstreams: list[UpstreamConfig], transport: httpx.AsyncBaseTransport | None = None)
    def route(self, model: str) -> UpstreamConfig
    def models(self) -> list[str]
    async def forward(self, body: dict[str, Any]) -> tuple[httpx.Response, float]   # response, upstream_ms
    async def forward_stream(self, body: dict[str, Any]) -> AsyncIterator[bytes]
    async def complete(self, model, messages, *, temperature, top_p=None, seed=None, max_tokens=1024) -> LLMResult
    async def aclose(self) -> None
# app.py
def create_app(config: KeelConfig, store: Store | None = None, upstream: UpstreamClient | None = None,
               tokens: TokenRegistry | None = None) -> FastAPI
# extract.py
class Candidate(BaseModel): text: str; confidence: float
def parse_candidates(text: str) -> list[Candidate]
async def extract_constraints(messages: list[Message], llm: LLMClient, model: str,
                              max_input_chars: int) -> tuple[list[Candidate], float, int]  # cands, ms, tokens
```

### 3.7 Store and SQLite DDL (`src/keel/store.py`)
```python
class Store:   # one sqlite3 connection, check_same_thread=False, guarded by threading.Lock
    def __init__(self, path: str) -> None          # ":memory:" allowed; runs DDL
    def close(self) -> None
    def ensure_session(self, session_id: str, config: dict[str, Any]) -> None
    def get_session(self, session_id: str) -> dict[str, Any] | None
    def set_extracted(self, session_id: str, upto: int, last_hash: str | None) -> None
    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]   # newest first + n_requests, n_compactions
    def next_turn_idx(self, session_id: str) -> int
    def insert_request(self, rec: RequestRecord) -> int
    def list_requests(self, session_id: str) -> list[dict[str, Any]]
    def insert_compaction(self, rec: CompactionRecord) -> int
    def active_compactions(self, session_id: str) -> list[CompactionRecord]   # prefix_len asc
    def list_compactions(self, session_id: str) -> list[CompactionRecord]     # all, id asc
    def deactivate_compactions(self, ids: list[int]) -> None
    def add_pin(self, pin: Pin) -> Pin            # same session + same text + active -> existing pin
    def list_pins(self, session_id: str, active_only: bool = False) -> list[Pin]
    def deactivate_pin(self, session_id: str, pin_id: int) -> bool
    def insert_run(self, run: RunInfo) -> None
    def get_run(self, run_id: str) -> RunInfo | None
    def episode_exists(self, run_id: str, scenario_id: str, model: str, condition: str, seed: int) -> bool
    def insert_episode(self, ep: Episode) -> int
    def list_episodes(self, run_id: str) -> list[Episode]
    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]   # read-only helper for report
```
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
Timestamps are UTC ISO-8601 strings. JSON columns are written with `json.dumps(..., ensure_ascii=False)`. Booleans are stored as 0/1.

### 3.8 Scenario schema (`bench/schema.py`)
```python
class ConstraintIntro(BaseModel): turn: int; role: Literal["user", "tool"]
class Constraint(BaseModel): text: str; introduced_at: ConstraintIntro; keywords: list[str]  # min 1
class FillerSpec(BaseModel): kind: Literal["log", "csv", "json", "text"]; n: int; seed: int = 0
class UserTurn(BaseModel): role: Literal["user"]; content: str
class AssistantTurn(BaseModel): role: Literal["assistant"]; content: str
class ToolScriptTurn(BaseModel):
    role: Literal["tool_script"]; tool: str; args: dict[str, Any] = {}
    output: str | None = None; output_file: str | None = None; filler: FillerSpec | None = None
    # at least one of output/output_file/filler; final text = file text, then output, then filler, "\n"-joined
Turn = Annotated[UserTurn | AssistantTurn | ToolScriptTurn, Field(discriminator="role")]
class GraderSpec(BaseModel):
    type: Literal["tool_call_forbidden", "tool_call_arg", "regex_present", "regex_absent"]
    tool: str | None = None; arg: str | None = None
    equals: Any = None; matches: str | None = None; not_in: list[Any] | None = None
    pattern: str | None = None
    # validator: tool_call_forbidden needs tool; tool_call_arg needs tool+arg+exactly one of
    # equals/matches/not_in; regex_* need pattern
class Graders(BaseModel): violation: GraderSpec; task_success: GraderSpec
class Scenario(BaseModel):
    id: str; kind: Literal["hard", "soft"]
    domain: Literal["devops", "support", "calendar_email", "data_pipelines"]
    system_prompt: str; constraint: Constraint; tools: list[str]; turns: list[Turn]
    compact_at: int; probe: UserTurn; probe_tool_outputs: dict[str, str] = {}; grader: Graders
    # validator: 1 <= introduced_at.turn < compact_at <= len(turns)
def load_scenario(path: Path) -> Scenario
def load_scenarios(directory: Path) -> list[Scenario]   # *.yaml except tools.yaml, sorted by id
def resolve_output(turn: ToolScriptTurn, root: Path) -> str  # output_file is relative to `root` (scenarios dir)
```

### 3.9 Grader interface (`bench/graders.py`). No LLM, ever
```python
@dataclass(frozen=True)
class ToolCall: name: str; args: dict[str, Any]   # args = json.loads(arguments) or {"_raw": str}
@dataclass(frozen=True)
class ProbeTrace: tool_calls: tuple[ToolCall, ...]; text: str
def strip_think(text: str) -> str                  # removes <think>...</think> blocks
def probe_trace(messages: list[Message]) -> ProbeTrace   # from role=="assistant" messages only
def fires(spec: GraderSpec, trace: ProbeTrace) -> bool
def grade(scenario: Scenario, trace: ProbeTrace) -> tuple[bool, bool]   # (violated, task_done)
def keywords_present(keywords: list[str], text: str) -> bool            # all, casefolded
def constraint_survived(keywords: list[str], messages: list[Message]) -> bool  # skips PIN_HEADER messages
def keyword_hits(keywords: list[str], text: str) -> int
```
`fires` semantics:
- `tool_call_forbidden`: any call named `tool`.
- `tool_call_arg`: any call to `tool` whose `arg` is present and either `str(v).casefold() == str(equals).casefold()`, or `re.search(matches, str(v), re.I)` matches, or `str(v).casefold()` is not in the casefolded `not_in` list.
- `regex_present` / `regex_absent`: `re.search(pattern, trace.text, re.I | re.S)` finds / does not find a match.

### 3.10 Mock tools, validation, runner and report
```python
# bench/mock_tools.py   (scenarios/tools.yaml shape: {tools: {<name>: {description, parameters, default_output}}})
class ToolSpec(BaseModel):
    name: str; description: str; parameters: dict[str, Any]; default_output: str = "ok"
def load_tools(path: Path) -> dict[str, ToolSpec]
def tool_definitions(names: list[str], tools: dict[str, ToolSpec]) -> list[dict[str, Any]]
    # [{"type":"function","function":{"name","description","parameters"}}] in `names` order
def mock_output(name: str, s: Scenario, tools: dict[str, ToolSpec]) -> str
    # s.probe_tool_outputs[name] > tools[name].default_output > "error: unknown tool"
def generate_filler(spec: FillerSpec) -> str        # random.Random(spec.seed); exactly spec.n lines
def stress_variant(s: Scenario, n: int, seed: int) -> Scenario   # FR-19 (T-40)
# bench/validate.py   (python -m bench.validate scenarios/)
def validate_scenario(s: Scenario, root: Path, tools: dict[str, ToolSpec], keep_last_n: int = 4) -> list[str]
def main(argv: list[str] | None = None) -> int     # prints errors per file; exit 1 if any
```
```python
@dataclass(frozen=True)
class Condition: id: str; strategy: str; pins: Literal["none", "oracle", "auto"]
CONDITIONS = {"C0": Condition("C0","none","none"), "C1": Condition("C1","summarize","none"),
  "C2": Condition("C2","truncate","none"), "C3": Condition("C3","summarize+pin","oracle"),
  "C4": Condition("C4","summarize+pin","auto"), "C5": Condition("C5","summarize+validate","oracle"),
  "C6": Condition("C6","truncate+pin","oracle")}
SAMPLING = {"temperature": 0.7, "top_p": 0.9}; MAX_PROBE_STEPS = 4; BENCH_TRIGGER = 1_000_000_000
def build_history(s: Scenario, root: Path) -> tuple[list[Message], dict[int, int]]  # msgs, turn -> len after turn
def condition_config(base: KeelConfig, cond: Condition, summarizer: str | None = None) -> KeelConfig
def session_id_for(run_id: str, scenario_id: str, model: str, cond: str, seed: int) -> str
    # f"{run_id}:{scenario_id}:{model}:{cond}:s{seed}"
async def run_episode(client: httpx.AsyncClient, store: Store, s: Scenario, root: Path, model: str,
                      cond: Condition, seed: int, run_id: str, tools: dict[str, ToolSpec]) -> Episode
async def run_batch(config: KeelConfig, scenarios_dir: Path, models: list[str], conditions: list[str],
                    seeds: list[int], out: Path, limit: int | None = None,
                    summarizer: str | None = None, upstream: UpstreamClient | None = None,
                    stress: int = 0) -> str  # run_id; stress > 0 -> stress_variant (T-40)
# report.py
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]  # rate, lo, hi; n==0 -> (0,0,0)
def mcnemar_exact(b: int, c: int) -> float
def included_pairs(episodes: list[Episode], n_seeds: int) -> tuple[set[tuple[str, str]], int]
def aggregate(store: Store, run_id: str) -> list[dict[str, Any]]   # one row per model x condition (+ kind)
def paired_c1_c3(store: Store, run_id: str) -> list[dict[str, Any]]        # {model, scenarios, b, c, p_value}
def extractor_metrics(store: Store, run_id: str) -> list[dict[str, Any]]   # {model, episodes, precision, recall}
def validator_metrics(store: Store, run_id: str) -> list[dict[str, Any]]   # {model, dropped_n, catch_rate}
def hypotheses(rows: list[dict], extractor: list[dict], validator: list[dict]) -> list[dict[str, str]]
def write_report(out_dir: Path) -> tuple[Path, Path]                 # results.md, results.csv
```

## 4. Request pipeline (steps → functions)

1. `app.chat_completions` → `handle_chat`. `parse_keel_headers`. No session → `passthrough` (forward unchanged, log a request with `cache_status="passthrough"`). `stream: true` → 501 until T-33.
2. `load_session`: `store.ensure_session`, effective strategy = `canonical_name(parse_strategy(policy or cfg.compaction.strategy, cfg.validate_.enabled))`, active pins and compactions, `next_turn_idx`.
3. `message_hashes(raw)` → `apply_cache`. Stale records → `store.deactivate_compactions`, and force = True.
4. `capture_constraints`: `X-Keel-Pin` → `store.add_pin`. If `pins.auto_extract`: run the extractor on user/tool messages in `raw[extracted_upto:]` (from 0 if `hashes[extracted_upto-1] != extracted_hash`), store `auto` pins (active iff confidence ≥ min_confidence), then `set_extracted`.
5. `tokens.count_messages(model, working, tools)` → `should_compact`: strategy ≠ "none" and (force or tokens > trigger_tokens).
6. `compact`: `find_span(working, keep_last_n, min_end=len(record.compacted) if record else 0)` → `CompactionState` → strategies (truncate/summarize).
7. … validate (inside `run_strategies`) → persist `CompactionRecord` with `prefix_len = raw_prefix_len(...)`, `compacted = new working[:new_end]`, `prefix_hashes = hashes[:prefix_len]`. `working = compacted + raw[prefix_len:]`.
8. `inject_pins` if a record is in effect (hit or new) and `"pin"` is in its strategy, with the active pins. Insert at index 1 if `working[0]` is system, else at 0.
9. `upstream.forward({**body, "messages": final})`, return the body unchanged with X-Keel headers, then `store.insert_request` (`proxy_ms = total − upstream_ms − llm_ms`).

## 5. Benchmark episode (runner)

1. `session_id_for(...)`. Oracle conditions: `POST /v1/sessions/{sid}/pins {text: constraint.text, source_turn: introduced_at.turn}`.
2. `history, ends = build_history(s, root)`. Compact request: `messages = history[:ends[compact_at]]`, `tools`, SAMPLING, `seed`, `max_tokens: 1`, headers `X-Keel-Session`, `X-Keel-Force-Compact: true`. The reply is discarded.
3. Probe: `messages = history + [probe]`. Loop ≤ 4: POST, append the assistant message. For each tool call, append `{"role":"tool","tool_call_id":id,"content":mock_output}`. Stop when there are no tool_calls.
4. `grade(s, probe_trace(probe_msgs))`. The latest compaction record gives survival flags, `validator_missing` and auto-pin TP counts. Write the `Episode`.

## 6. Decisions log

| Decision | Reason |
|---|---|
| Raw dict messages | Lossless passthrough of unknown OpenAI fields |
| Chained per-message hash | First changed message is found in O(n); supports recompaction from it |
| `compacted` stores full replacement incl. system | Cache swap is one slice; chained compactions compose |
| Pin message not cached | Pin store can change between requests |
| Scripted filler, model only at compact + probe | Identical inputs across conditions; ~5x cheaper runs |
| Force-compact request with `max_tokens: 1` | Reuses the normal proxy path; no extra endpoint |
| In-process runner via ASGITransport | One command, no port juggling on Kaggle, store shared |
| Graders pure functions on `ProbeTrace` | Deterministic, unit-testable, no LLM (PRD G3) |
| Judge/extractor temp 0, seed 0, fixed model | Not a confound across conditions |
| Summarizer prompt never mentions constraints | Measures realistic naive compaction; prompt hash logged per run |
| Survival excludes pin message | Separates summary quality from pin rescue |
| Seeded filler generator | Small, reviewable scenario files; deterministic bulk |
| argparse, no click/typer | No extra dependency |
| Episode-level Wilson + scenario-level McNemar | PRD statistics; McNemar needs no scipy |
| One DB per run directory | Self-contained, resumable, easy to publish |
