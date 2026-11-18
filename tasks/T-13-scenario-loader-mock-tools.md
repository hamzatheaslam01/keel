# T-13: Scenario loader and mock tools

## Goal
Implement scenario loading (YAML → `Scenario`, tool output resolution), the tool registry (`scenarios/tools.yaml`), mock tool outputs, and the seeded filler generator that produces bulky deterministic tool outputs.

## Context
Scenario files live in `scenarios/*.yaml` (one scenario per file). `tools.yaml` in the same directory is the tool registry, not a scenario. A `tool_script` turn's output text is built from up to three parts, joined with `"\n"` in this order: the `output_file` text (path relative to the scenarios root), then `output`, then the generated `filler`. The constraint text in a tool output is always in `output`, so it comes before any filler.

Determinism matters: the same scenario, seed and config must produce identical model inputs. The filler uses only `random.Random(spec.seed)`.

From `bench/schema.py` (already written):
```python
class FillerSpec(BaseModel): kind: Literal["log", "csv", "json", "text"]; n: int; seed: int = 0
class ToolScriptTurn(BaseModel):
    role: Literal["tool_script"]; tool: str; args: dict[str, Any] = {}
    output: str | None = None; output_file: str | None = None; filler: FillerSpec | None = None
class Scenario(BaseModel): ... ; tools: list[str]; probe_tool_outputs: dict[str, str] = {}
def load_scenario(path: Path) -> Scenario
def load_scenarios(directory: Path) -> list[Scenario]   # *.yaml except tools.yaml, sorted by id
def resolve_output(turn: ToolScriptTurn, root: Path) -> str
```
Contract (`bench/mock_tools.py`):
```python
class ToolSpec(BaseModel):
    name: str; description: str; parameters: dict[str, Any]; default_output: str = "ok"
def load_tools(path: Path) -> dict[str, ToolSpec]
    # file shape: {tools: {<name>: {description, parameters, default_output?}}}; name filled from key
def tool_definitions(names: list[str], tools: dict[str, ToolSpec]) -> list[dict[str, Any]]
    # [{"type":"function","function":{"name","description","parameters"}}] in `names` order; KeyError if unknown
def mock_output(name: str, s: Scenario, tools: dict[str, ToolSpec]) -> str
    # s.probe_tool_outputs[name] > tools[name].default_output > "error: unknown tool"
def generate_filler(spec: FillerSpec) -> str        # random.Random(spec.seed); exactly spec.n lines
```
`resolve_output` imports `generate_filler` from `bench.mock_tools`. To avoid a cycle, do the import inside the function body.

Filler formats (lines joined with `"\n"`, no trailing newline; aim for the stated length so token budgets are predictable):
- `log` (~100 chars/line): `f"2026-03-{d:02d}T{h:02d}:{m:02d}:{s:02d}Z {LEVEL} {svc}[{pid}]: {msg} latency_ms={lat} trace={hex8}"`
- `csv` (~50 chars/line): the first line is the header `id,created_at,user_id,amount,status,region`, then `n-1` rows like `10423,2026-03-04T11:02:51Z,u_58213,49.90,settled,r3`
- `json` (~120 chars/line, JSONL): `{"order_id": "A-1xxx", "sku": "SKU-xxxx", "qty": n, "price": x.xx, "status": "...", "carrier": "...", "updated_at": "..."}` via `json.dumps(..., sort_keys=True)`
- `text` (~80 chars/line): sentences assembled from word lists.

Vocabulary restriction: filler must never contain these words, because scenario keywords rely on their absence: `prod`, `production`, `staging`, `limit`, `analytics`, `legal`, `billing`, `retry`, `retries`, `freeze`, `secret`, `email`, `password`, `customers`, `pii`, `eu-west`, `us-east`, `batch-1`, `batch-2`, `tier2`, `canary`.

Use these exact lists:
```python
LEVELS = ["INFO", "INFO", "INFO", "WARN", "DEBUG", "ERROR"]
SERVICES = ["payments-api", "cart-svc", "search-svc", "auth-gw", "orders-svc", "notify-svc"]
LOG_MSGS = ["request completed", "db pool wait", "cache miss for key", "upstream timeout recovered",
            "slow query detected", "connection reset by peer", "gc pause observed", "queue depth high"]
STATUSES = ["settled", "pending", "refunded", "failed", "shipped", "delivered"]
CARRIERS = ["ups", "dhl", "fedex", "usps"]
WORDS = ["the", "service", "team", "reviewed", "queue", "latency", "report", "weekly", "metrics",
         "dashboard", "update", "shows", "stable", "growth", "orders", "cart", "search", "page",
         "users", "mobile", "release", "notes", "incident", "summary", "follow", "up", "items"]
```

## Files
Modify: `bench/schema.py`, `bench/mock_tools.py`.
Create: `tests/test_loader_mock_tools.py`.
Read: `bench/schema.py`, `bench/mock_tools.py`.

## Implement
1. `load_scenario(path)`: `yaml.safe_load(path.read_text("utf-8"))` → `Scenario.model_validate`. Wrap errors as `ValueError(f"{path.name}: {err}")`.
2. `load_scenarios(directory)`: load every `*.yaml` except `tools.yaml`, sort by `id`, and raise `ValueError` on duplicate ids.
3. `resolve_output(turn, root)`: parts = [`(root / output_file).read_text("utf-8").rstrip("\n")` if set, `output` if set, `generate_filler(filler)` if set]; return `"\n".join(parts)`.
4. `load_tools`, `tool_definitions` and `mock_output` per the contract.
5. `generate_filler`: one `rng = random.Random(spec.seed)` and the formats above. Every random choice goes through `rng`; never use `datetime.now()`.

## Tests
`tests/test_loader_mock_tools.py`:
- `test_load_scenarios_skips_tools_and_sorts(tmp_path)`: write `b.yaml` (id `b-1`), `a.yaml` (id `a-1`) and `tools.yaml` → ids `["a-1", "b-1"]`. Build the scenario YAML from a minimal valid dict: devops, 3 user turns, introduced at turn 1, `compact_at: 2`, a probe, and graders `{type: tool_call_forbidden, tool: deploy}` for both.
- `test_duplicate_ids_raise(tmp_path)`.
- `test_resolve_output_order(tmp_path)`: an `output_file` containing `"FILE\n"`, `output: "OUT"`, and `filler: {kind: text, n: 2, seed: 1}` → lines `[FILE, OUT, <2 filler lines>]`.
- `test_filler_deterministic_and_line_count()`: for each kind, `n=25`: same seed → identical text; exactly 25 lines; seeds 1 and 2 differ.
- `test_filler_vocabulary_clean()`: for every kind, with seeds 0–9 and `n=200`, none of the forbidden words appears (casefolded substring check).
- `test_filler_lengths_roughly()`: average line length for log is 80–130, csv 35–70, json 90–160, text 50–110.
- `test_tools_registry(tmp_path)`: a `tools.yaml` with `deploy` (parameters with `env` required) and `read_logs` → `tool_definitions(["read_logs", "deploy"], ...)` is in that order; an unknown name raises `KeyError`.
- `test_mock_output_precedence()`: `probe_tool_outputs` wins, then `default_output`, then `"error: unknown tool"`.

## Acceptance
```bash
uv run pytest tests/test_loader_mock_tools.py tests/test_schema.py -q
uv run ruff check .
```

## Out of scope
`stress_variant` (T-40), `scenarios/tools.yaml` content (T-18), the runner.

## Depends on
T-04

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
