# T-01: Project scaffold, config and shared models

## Goal
Create the uv project (pyproject with deps, ruff, pytest) plus the config models and shared data models that every later task imports.

## Context
Keel is an OpenAI-compatible proxy (FastAPI) that rewrites the `messages` array before forwarding it upstream. Python 3.11, uv, pydantic v2. The repo is empty except `docs/` and `tasks/`.

Packaging: the distribution is named `keel-proxy`. Two importable packages live in it: `keel` (from `src/keel`) and `bench` (top-level `bench/`, created in T-03). Wheel packages are built with hatchling.

Contract: `src/keel/config.py`
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

Contract: `src/keel/models.py`
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

## Files
Create:
- `pyproject.toml`
- `src/keel/__init__.py` (only `__version__ = "0.1.0"`)
- `src/keel/config.py`
- `src/keel/models.py`
- `tests/test_config_models.py`

Read: none.

## Implement
1. `pyproject.toml`:
   - `[project]` name `keel-proxy`, version `0.1.0`, `requires-python = ">=3.11"`, `license = {text = "MIT"}`, description "Context-guard proxy for agent compaction".
   - dependencies: `fastapi>=0.110`, `uvicorn>=0.29`, `httpx>=0.27`, `pydantic>=2.6`, `pyyaml>=6.0`, `tokenizers>=0.15`.
   - `[project.scripts] keel = "keel.cli:main"` (the module comes in T-04).
   - `[dependency-groups] dev = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21", "ruff>=0.5"]`.
   - `[build-system] requires = ["hatchling"]`, `build-backend = "hatchling.build"`.
   - `[tool.hatch.build.targets.wheel] packages = ["src/keel", "bench"]`.
   - `[tool.pytest.ini_options] asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["."]`.
   - `[tool.ruff] line-length = 100`, `target-version = "py311"`; `[tool.ruff.lint] select = ["E", "F", "I", "B", "UP"]`.
2. Create an empty `bench/__init__.py` so hatch can find the package (T-03 adds modules).
3. `config.py`: the models exactly as in the contract (use `ConfigDict`, `Field`).
   - `expand_env` replaces each `${NAME}` (regex `\$\{([A-Za-z_][A-Za-z0-9_]*)\}`) with `os.environ.get(NAME, "")`.
   - `load_config`: read the text (utf-8), run `expand_env`, then `yaml.safe_load` (`None` → `{}`). Drop upstream dicts whose `base_url` is empty or whitespace, logging a warning with `logging.getLogger("keel")`. Then `KeelConfig.model_validate(data)`. Wrap `OSError`, `yaml.YAMLError` and `pydantic.ValidationError` in `ConfigError` with the path in the message.
4. `models.py`: the models exactly as in the contract. Use `Field(default_factory=list)` for list defaults. `text_of`:
   - `content` str → itself. `content` list → join of `part["text"]` for parts with `type == "text"`, separated by `"\n"`. `None` or missing → `""`.
   - For each `tool_calls[i]["function"]`, append `"\n" + name + " " + arguments`.
   - `name` is not included.
5. `models.py` imports `CompactionConfig` from `keel.config`. `config.py` must not import `models.py`.

## Tests
`tests/test_config_models.py`:
- `test_load_config_full(tmp_path, monkeypatch)`: write the YAML below and set `HOSTED_BASE_URL=https://h.example/v1` and `HOSTED_API_KEY=k1`. Assert 2 upstreams; `cfg.upstreams[1].api_key == "k1"`; `cfg.compaction.truncate.head_tokens == 200`; `cfg.validate_.judge_model == "qwen3-1.7b"`; `cfg.server.port == 8400`.
- `test_unset_env_drops_upstream(tmp_path, monkeypatch)`: delete `HOSTED_BASE_URL` from the environment and load the same YAML. Assert only the `local` upstream remains.
- `test_defaults()`: `KeelConfig()` has `compaction.strategy == "none"`, `keep_last_n == 4`, `pins.min_confidence == 0.6`, and an empty `tokenizers`.
- `test_bad_yaml_raises_config_error(tmp_path)`: the file content `"server: [unclosed"` raises `ConfigError`.
- `test_extra_body_parsed(tmp_path)`: an upstream with `extra_body: {chat_template_kwargs: {enable_thinking: false}}` round-trips.
- `test_text_of_string_list_and_tool_calls()`: asserts `text_of({"role":"user","content":"hi"}) == "hi"`; list content `[{"type":"text","text":"a"},{"type":"image_url"},{"type":"text","text":"b"}]` → `"a\nb"`; an assistant with `content=None` and one tool call `{"function":{"name":"deploy","arguments":"{\"env\":\"prod\"}"}}` → `"\ndeploy {\"env\":\"prod\"}"`.
- `test_episode_and_record_defaults()`: `Episode(run_id="r", scenario_id="s", kind="hard", model="m", condition="C0", seed=0, session_id="x")` has `probe == []` and `error is None`; `Pin(session_id="s", text="t").source == "explicit"`.

Fixture YAML (inline in the test as a string):
```yaml
server: {host: 127.0.0.1, port: 8400, db: keel.db}
upstreams:
  - name: local
    base_url: http://127.0.0.1:8080/v1
    models: [qwen3-1.7b, qwen3-4b]
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
pins: {auto_extract: false, extractor_model: qwen3-1.7b, min_confidence: 0.6}
validate: {enabled: false, judge_model: qwen3-1.7b}
```

## Acceptance
```bash
uv sync
uv run pytest tests/test_config_models.py -q
uv run ruff check .
```

## Out of scope
Store, strategies, app, CLI and bench modules. Don't create `keel.example.yaml` (T-02) or CI (T-05).

## Depends on
none

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
