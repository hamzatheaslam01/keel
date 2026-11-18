# T-39: Summarizer-swap flag (FR-20)

## Goal
Add `--summarizer MODEL` to `keel bench run`, so a subset can be rerun with a larger summarizer model. That separates summary quality from model obedience.

## Context
PRD FR-20 (Could): summarizer-swap ablation, where the summarizer is a larger free-tier model on a subset. By default the summarizer is the agent's own model (`compaction.summarizer: same_as_agent`). `run_batch(..., summarizer=...)` and `condition_config(base, cond, summarizer)` already accept the override, and the summarize strategy already uses `config.compaction.summarizer` when it isn't `same_as_agent`. The run's `args` already record `summarizer`. Only the CLI flag and an end-to-end test are missing.

```python
async def run_batch(config, scenarios_dir, models, conditions, seeds, out, limit=None, summarizer=None, upstream=None) -> str
```
The summarizer model must be routable: it must appear in some upstream's `models`. Validate this in the CLI before starting, and fail with exit 2 and a clear message if it isn't.

## Files
Modify: `src/keel/cli.py`.
Create: `tests/test_summarizer_swap.py`.
Read: `src/keel/cli.py`, `bench/runner.py`, `tests/test_runner.py`.

## Implement
1. `bench run` gets `--summarizer` (default None). If it's set and not in `UpstreamClient(cfg.upstreams).models()` → print `"unknown summarizer model: X"` and return 2. Pass it to `run_batch`.
2. Print `summarizer=<value or same_as_agent>` in the start banner.

## Tests
`tests/test_summarizer_swap.py` (reuse the respx side-effect pattern from `tests/test_runner.py`; the config's upstream serves `["m1", "big"]`):
- `test_summarizer_model_used(tmp_path)`: `run_batch(..., ["C1"], summarizer="big")` → the recorded summarizer request has `model == "big"`, the agent requests have `model == "m1"`, and `store.get_run(...).args["summarizer"] == "big"`.
- `test_cli_rejects_unknown_summarizer(tmp_path)`: a config file with upstream models `["m1"]`; `main(["bench", "run", "--models", "m1", "--out", str(tmp_path / "r"), "--config", cfgpath, "--summarizer", "zzz"]) == 2`.

## Acceptance
```bash
uv run pytest tests/test_summarizer_swap.py -q
uv run pytest -q -m "not perf"
uv run ruff check .
```

## Out of scope
Choosing the larger model or running the ablation (HUMAN), report changes.

## Depends on
T-19

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
