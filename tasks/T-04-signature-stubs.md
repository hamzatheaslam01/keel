# T-04: Signature stubs for all remaining modules

## Goal
Create every remaining module with its exact public signatures, bodies raising `NotImplementedError`, so that later tasks only fill bodies and every import resolves now.

## Context
**File-count waiver:** this task touches more than 4 files. That's allowed because each file holds only signatures, docstrings and constants.

Existing modules: `keel.config` (KeelConfig and friends), `keel.models` (Message, Pin, CompactionRecord, RequestRecord, SessionState, RunInfo, Episode, PIN_HEADER, SUMMARY_PREFIX, text_of), `keel.store` (Store), `keel.strategies.base` (LLMResult, LLMClient, CompactionState, StrategyContext, Strategy, StrategyError, parse_strategy, canonical_name, run_strategies), `bench.schema` (Scenario etc.), `bench.graders`.

Signatures to create, copied exactly:
```python
# src/keel/tokens.py
@dataclass
class TokenCount: n: int; method: Literal["hf", "fallback"]
class TokenRegistry:
    def __init__(self, paths: dict[str, str]) -> None
    def method(self, model: str) -> Literal["hf", "fallback"]
    def count_text(self, model: str, text: str) -> int
    def count_messages(self, model: str, messages: list[Message], tools: list[dict] | None = None) -> TokenCount
    def head_tail(self, model: str, text: str, head: int, tail: int) -> tuple[str, str, int]

# src/keel/upstream.py
class UnknownModelError(KeyError): ...
class UpstreamError(RuntimeError): ...
class UpstreamClient:
    def __init__(self, upstreams: list[UpstreamConfig], transport: httpx.AsyncBaseTransport | None = None)
    def route(self, model: str) -> UpstreamConfig
    def models(self) -> list[str]
    async def forward(self, body: dict[str, Any]) -> tuple[httpx.Response, float]
    async def forward_stream(self, body: dict[str, Any]) -> AsyncIterator[bytes]
    async def complete(self, model: str, messages: list[Message], *, temperature: float,
                       top_p: float | None = None, seed: int | None = None,
                       max_tokens: int = 1024) -> LLMResult
    async def aclose(self) -> None

# src/keel/session.py
def canonical_message(msg: Message) -> str
def message_hashes(messages: list[Message]) -> list[str]
def first_changed_index(hashes: list[str], prefix_hashes: list[str]) -> int
def find_span(messages: list[Message], keep_last_n: int, min_end: int = 0) -> tuple[int, int] | None
@dataclass
class CacheResult:
    working: list[Message]; record: CompactionRecord | None
    status: Literal["none", "hit", "mismatch"]
    stale: list[CompactionRecord]; first_changed: int | None
def apply_cache(raw: list[Message], hashes: list[str], records: list[CompactionRecord]) -> CacheResult
def raw_prefix_len(cache: CacheResult, working_end: int) -> int

# src/keel/pipeline.py
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
                              hdr: KeelHeaders, deps: Deps) -> tuple[list[Pin], float]
def should_compact(tokens_in: int, cfg: CompactionConfig, strategy: str, force: bool) -> bool
async def compact(cache: CacheResult, raw: list[Message], hashes: list[str], state: SessionState,
                  body: dict[str, Any], turn_idx: int, deps: Deps
                  ) -> tuple[CompactionRecord | None, float]
def inject_pins(working: list[Message], pins: list[Pin]) -> tuple[list[Message], str | None]
def error_body(message: str, type_: str, code: int) -> dict[str, Any]

# src/keel/app.py
def create_app(config: KeelConfig, store: Store | None = None, upstream: UpstreamClient | None = None,
               tokens: TokenRegistry | None = None) -> FastAPI

# src/keel/extract.py
class Candidate(BaseModel): text: str; confidence: float
def parse_candidates(text: str) -> list[Candidate]
async def extract_constraints(messages: list[Message], llm: LLMClient, model: str,
                              max_input_chars: int) -> tuple[list[Candidate], float, int]

# src/keel/strategies/{truncate,summarize,validate,pin}.py: one class each
class TruncateStrategy:  name = "truncate";  order = 10;  async def apply(self, state, ctx) -> CompactionState
class SummarizeStrategy: name = "summarize"; order = 20;  async def apply(self, state, ctx) -> CompactionState
class ValidateStrategy:  name = "validate";  order = 30;  async def apply(self, state, ctx) -> CompactionState
class PinStrategy:       name = "pin";       order = 40;  async def apply(self, state, ctx) -> CompactionState

# src/keel/cli.py
def build_parser() -> argparse.ArgumentParser
def main(argv: list[str] | None = None) -> int

# bench/mock_tools.py
class ToolSpec(BaseModel):
    name: str; description: str; parameters: dict[str, Any]; default_output: str = "ok"
def load_tools(path: Path) -> dict[str, ToolSpec]
def tool_definitions(names: list[str], tools: dict[str, ToolSpec]) -> list[dict[str, Any]]
def mock_output(name: str, s: Scenario, tools: dict[str, ToolSpec]) -> str
def generate_filler(spec: FillerSpec) -> str
def stress_variant(s: Scenario, n: int, seed: int) -> Scenario

# bench/runner.py
@dataclass(frozen=True)
class Condition: id: str; strategy: str; pins: Literal["none", "oracle", "auto"]
CONDITIONS = {"C0": Condition("C0","none","none"), "C1": Condition("C1","summarize","none"),
  "C2": Condition("C2","truncate","none"), "C3": Condition("C3","summarize+pin","oracle"),
  "C4": Condition("C4","summarize+pin","auto"), "C5": Condition("C5","summarize+validate","oracle"),
  "C6": Condition("C6","truncate+pin","oracle")}
SAMPLING = {"temperature": 0.7, "top_p": 0.9}; MAX_PROBE_STEPS = 4; BENCH_TRIGGER = 1_000_000_000
def build_history(s: Scenario, root: Path) -> tuple[list[Message], dict[int, int]]
def condition_config(base: KeelConfig, cond: Condition, summarizer: str | None = None) -> KeelConfig
def session_id_for(run_id: str, scenario_id: str, model: str, cond: str, seed: int) -> str
async def run_episode(client: httpx.AsyncClient, store: Store, s: Scenario, root: Path, model: str,
                      cond: Condition, seed: int, run_id: str, tools: dict[str, ToolSpec]) -> Episode
async def run_batch(config: KeelConfig, scenarios_dir: Path, models: list[str], conditions: list[str],
                    seeds: list[int], out: Path, limit: int | None = None,
                    summarizer: str | None = None, upstream: UpstreamClient | None = None,
                    stress: int = 0) -> str

# bench/report.py
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]
def mcnemar_exact(b: int, c: int) -> float
def included_pairs(episodes: list[Episode], n_seeds: int) -> tuple[set[tuple[str, str]], int]
def aggregate(store: Store, run_id: str) -> list[dict[str, Any]]
def paired_c1_c3(store: Store, run_id: str) -> list[dict[str, Any]]
def extractor_metrics(store: Store, run_id: str) -> list[dict[str, Any]]
def validator_metrics(store: Store, run_id: str) -> list[dict[str, Any]]
def hypotheses(rows: list[dict], extractor: list[dict], validator: list[dict]) -> list[dict[str, str]]
def write_report(out_dir: Path) -> tuple[Path, Path]

# bench/validate.py
def validate_scenario(s: Scenario, root: Path, tools: dict[str, ToolSpec], keep_last_n: int = 4) -> list[str]
def main(argv: list[str] | None = None) -> int

# bench/toy_loop.py
async def run_toy_loop(client: httpx.AsyncClient, model: str, session: str, max_steps: int = 3) -> list[Message]
def main(argv: list[str] | None = None) -> int
```

## Files
Create (all stubs):
`src/keel/tokens.py`, `src/keel/upstream.py`, `src/keel/session.py`, `src/keel/pipeline.py`, `src/keel/app.py`, `src/keel/extract.py`, `src/keel/cli.py`, `src/keel/strategies/truncate.py`, `src/keel/strategies/summarize.py`, `src/keel/strategies/validate.py`, `src/keel/strategies/pin.py`, `bench/mock_tools.py`, `bench/runner.py`, `bench/report.py`, `bench/validate.py`, `bench/toy_loop.py`, `tests/test_imports.py`.

Read: `src/keel/models.py`, `src/keel/strategies/base.py`, `src/keel/store.py`, `bench/schema.py`.

## Implement
1. In every file, use `from __future__ import annotations`, real imports of the referenced types, and `ClassVar` for `name` and `order`.
2. Every function or method body is `raise NotImplementedError("T-XX")`, using the ID of the task that implements it: tokens T-06; upstream T-07 (`forward_stream` T-33); session T-14; pipeline: `parse_keel_headers`/`passthrough`/`error_body`/`handle_chat` T-09, `load_session`/`capture_constraints`/`should_compact`/`compact` T-16, `inject_pins` T-22; app T-09; extract T-30; truncate T-21; summarize T-15; validate T-29; pin T-22; cli `main` T-10; mock_tools T-13 (`stress_variant` T-40); runner `build_history`/`condition_config`/`session_id_for` T-17, `run_episode`/`run_batch` T-19; report T-23 (`paired_c1_c3` T-24; `extractor_metrics`/`validator_metrics`/`hypotheses` T-32); validate T-18; toy_loop T-11.
3. Two exceptions, which you implement now:
   - The dataclasses, `CONDITIONS`, `SAMPLING`, `MAX_PROBE_STEPS` and `BENCH_TRIGGER`.
   - `cli.build_parser()` builds an argparse parser `prog="keel"` with subcommands: `serve` (`--config`, default `keel.yaml`); `bench` with subcommands `run` (`--scenarios` default `scenarios`, `--models` required, `--conditions` default `C0,C1,C2,C3,C4,C5,C6`, `--seeds` int default 3, `--out` required, `--config` default `keel.yaml`, `--limit` int optional) and `report` (positional `out_dir`). `main` parses its args, then raises `NotImplementedError("T-10")`. `--help` must still work, since argparse exits before reaching that line.
4. `tests/test_imports.py`: `test_all_modules_import()` imports each new module with `importlib.import_module`. `test_conditions_table()` asserts `CONDITIONS["C5"].strategy == "summarize+validate"` and `CONDITIONS["C4"].pins == "auto"`. `test_strategy_class_attrs()` checks name and order for all 4 strategies.

## Tests
`tests/test_imports.py` as above.

## Acceptance
```bash
uv run pytest tests/test_imports.py -q
uv run keel --help
uv run keel bench run --help
uv run ruff check .
```

## Out of scope
Any real logic beyond the constants, dataclasses and argparse tree.

## Depends on
T-02, T-03

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
