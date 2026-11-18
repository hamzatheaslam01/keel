# T-19: Episode runner and `keel bench run`

## Goal
Implement `run_episode` and `run_batch`, which drive scripted episodes through an in-process Keel app, grade them deterministically and write `episodes` and `runs` rows. Wire up the `keel bench run` CLI command.

## Context
Episode flow (ARCHITECTURE §5):
1. `sid = session_id_for(run_id, s.id, model, cond.id, seed)`. For oracle conditions (`cond.pins == "oracle"`): `POST /v1/sessions/{sid}/pins` with `{"text": s.constraint.text, "source_turn": s.constraint.introduced_at.turn}`.
2. `history, ends = build_history(s, root)`. The **compact request**:
   - body `{"model": model, "messages": history[:ends[s.compact_at]], "tools": tool_definitions(s.tools, tools), **SAMPLING, "seed": seed, "max_tokens": 1}`
   - headers `X-Keel-Session: sid` and `X-Keel-Force-Compact: true`
   - The reply is discarded; any non-200 is an episode error.
3. **Probe loop**: `msgs = history + [{"role": "user", "content": s.probe.content}]`. Then up to `MAX_PROBE_STEPS` (4) times:
   - POST (same base body, no `max_tokens`, no force header).
   - Take `choices[0].message` and keep only `role`/`content`/`tool_calls` (role defaults to "assistant", None content → ""). Append it to `msgs` and to `probe_msgs`.
   - If there are no tool calls, stop. Otherwise, for each call, append `{"role": "tool", "tool_call_id": call.get("id", ""), "content": mock_output(name, s, tools)}` to both lists.
4. Grading:
   - `violated, task_done = grade(s, probe_trace(probe_msgs))`.
   - `rec` = the last record in `store.list_compactions(sid)` with `active` True (or None). If `rec` exists: `constraint_survived = constraint_survived(kw, rec.compacted + raw[rec.prefix_len:])` where `raw = history + [probe msg]`; `summary_survived = keywords_present(kw, rec.summary_text)` if `summary_text` is not None; `validator_missing = rec.validator.get("missing")` if `rec.validator`.
   - If `cond.pins == "auto"`: `auto = [p for p in store.list_pins(sid) if p.source == "auto" and p.active]`; `auto_pins_total = len(auto)`; `auto_pins_tp = sum(keyword_hits(kw, p.text) >= ceil(len(kw)/2) for p in auto)`.
5. Return an `Episode`. Any `httpx.HTTPError`, `KeyError`, `ValueError` or `IndexError` → an `Episode` with `error=str(e)[:500]` and default flags.

Batch flow:
- `out.mkdir(parents=True, exist_ok=True)`; `store = Store(str(out / "keel.db"))`; `run_id = out.name`.
- Load scenarios (`load_scenarios(scenarios_dir)[:limit]`) and tools (`load_tools(scenarios_dir / "tools.yaml")`).
- `store.insert_run(RunInfo(...))` (INSERT OR IGNORE makes resume safe), where:
  - `config` = `config.model_dump(by_alias=True)` with every upstream `api_key` replaced by `"***"` when set
  - `model_hashes = {m: file_sha256(config.model_files[m]) if m in model_files and the file exists else "unknown"}`
  - `args = {scenarios_dir, models, conditions, seeds, limit, summarizer, "summarizer_prompt_hash": SUMMARIZER_PROMPT_HASH, "judge_model": config.validate_.judge_model, "extractor_model": config.pins.extractor_model, "sampling": SAMPLING, "max_probe_steps": MAX_PROBE_STEPS}`
- `upstream = upstream or UpstreamClient(config.upstreams)`, shared across conditions.
- For each condition: `app = create_app(condition_config(config, CONDITIONS[c], summarizer), store=store, upstream=upstream)` and `client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://keel", timeout=None)`. Then for each model, scenario and seed: skip if `store.episode_exists(...)`; else `ep = await run_episode(...)`, `store.insert_episode(ep)`, and print `f"{c} {model} {s.id} s{seed} violated={ep.violated} err={bool(ep.error)} {secs:.1f}s"`. Episodes run sequentially.
- Return `run_id`.

Helpers (private): `git_sha() -> str` (`git rev-parse HEAD`, plus `-dirty` if `git status --porcelain` prints anything, `"nogit"` on failure) and `file_sha256(path) -> str` (chunked, 1 MiB).

Contracts:
```python
async def run_episode(client: httpx.AsyncClient, store: Store, s: Scenario, root: Path, model: str,
                      cond: Condition, seed: int, run_id: str, tools: dict[str, ToolSpec]) -> Episode
async def run_batch(config: KeelConfig, scenarios_dir: Path, models: list[str], conditions: list[str],
                    seeds: list[int], out: Path, limit: int | None = None,
                    summarizer: str | None = None, upstream: UpstreamClient | None = None,
                    stress: int = 0) -> str   # stress is T-40: here, raise NotImplementedError if stress > 0
class Episode(BaseModel):
    run_id: str; scenario_id: str; kind: Literal["hard", "soft"]; model: str
    condition: str; seed: int; session_id: str
    violated: bool = False; task_done: bool = False
    constraint_survived: bool | None = None; summary_survived: bool | None = None
    validator_missing: int | None = None
    auto_pins_total: int | None = None; auto_pins_tp: int | None = None
    probe: list[Message] = []; error: str | None = None
```
Available: `build_history`, `condition_config`, `session_id_for`, `CONDITIONS`, `SAMPLING`, `MAX_PROBE_STEPS` (runner); `load_scenarios` (schema); `load_tools`, `tool_definitions`, `mock_output` (mock_tools); `grade`, `probe_trace`, `constraint_survived`, `keywords_present`, `keyword_hits` (graders); `create_app` (keel.app); `Store`, `RunInfo`; `SUMMARIZER_PROMPT_HASH` (keel.strategies.summarize); `UpstreamClient(upstreams, transport=None)`.

CLI: `keel bench run --scenarios DIR --models a,b --conditions C0,C1 --seeds 3 --out results/run-001 [--config keel.yaml] [--limit N]`. Seeds `N` → `[0 … N-1]`.

## Files
Modify: `bench/runner.py`, `src/keel/cli.py`.
Create: `tests/test_runner.py`.
Read: `bench/runner.py`, `src/keel/cli.py`, `tests/conftest.py`, `tests/fixtures/scenarios/ex-hard-ops.yaml`.

## Implement
1. `run_episode` and `run_batch` exactly as described.
2. `cli.main` for `bench run`: `load_config(args.config)`, split the comma lists, check each condition is in `CONDITIONS` (otherwise print an error and return 2), then `asyncio.run(run_batch(...))`, print `run_id`, return 0.

## Tests
`tests/test_runner.py` (async). Use the config from conftest with upstream `UP` serving `["m1", "judge"]`, and respx on `POST {UP}/chat/completions` with this side effect:
- the summarizer call (system starts with `"You compress conversation history"`) → `chat_json("The team fixed the payments pool size.")`, which contains no keywords;
- `max_tokens == 1` → `chat_json("ok")`;
- otherwise, if the last message is the probe user message → `chat_json(None, tool_calls=[{"id": "p1", "type": "function", "function": {"name": "deploy", "arguments": "{\"service\":\"payments-api\",\"env\":\"prod\",\"reason\":\"fix\"}"}}])`;
- otherwise (after the tool result) → `chat_json("Deployed.")`.

Scenario: `tests/fixtures/scenarios/ex-hard-ops.yaml`, copied with `scenarios/tools.yaml` into `tmp_path/sc/`.
- `test_run_episode_c1(tmp_path)`: `run_batch(config, tmp_path/"sc", ["m1"], ["C1"], [0], tmp_path/"run-t", upstream=UpstreamClient(config.upstreams))`. One episode: `violated True`, `task_done False`, `constraint_survived False`, `summary_survived False`, `error None`, `probe` has 3 messages (assistant call, tool, assistant text). `run_id == "run-t"`.
- `test_run_episode_c0_no_compaction(tmp_path)`: C0 → `constraint_survived is None`, no compactions in the DB, `violated True`.
- `test_compact_request_uses_force_and_max_tokens(tmp_path)`: inspect the recorded upstream calls: the first agent call has `max_tokens == 1` and `seed == 0`, and `tools` contains `deploy`.
- `test_resume_skips_existing(tmp_path)`: run the same batch twice → still 1 episode and no new upstream calls on the second run.
- `test_run_info_logged(tmp_path)`: `store.get_run("run-t")` has `seeds == [0]`, `args["summarizer_prompt_hash"]` set, `model_hashes == {"m1": "unknown"}`, and no plain `api_key` values.
- `test_upstream_error_marks_episode(tmp_path)`: the agent route returns 500 on the probe → `ep.error` is set and nothing raises.
- `test_cli_bench_run_rejects_unknown_condition()`: `main(["bench", "run", "--models", "m1", "--conditions", "C9", "--out", "x"]) == 2`.

## Acceptance
```bash
uv run pytest tests/test_runner.py -q
uv run pytest -q
uv run ruff check .
uv run keel bench run --help
```

## Out of scope
The report (T-23), pin injection (T-22; C3/C6 run but pins are not injected until then), the summarizer flag (T-39), stress (T-40).

## Depends on
T-12, T-16, T-17, T-18

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
