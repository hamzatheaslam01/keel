# T-23: Report core and `keel bench report`

## Goal
Implement the report: the inclusion rule, Wilson 95% CIs, per model × condition (× kind) aggregation of violation rate, task success and survival, written as `results.md` and `results.csv`. Wire up `keel bench report`.

## Context
PRD FR-12: per model × condition violation rate with Wilson 95% CI, survival, task success, overhead (overhead comes in T-24); Markdown table + CSV. FR-13: a scenario-model pair counts only if C0 compliance is at least 2 of 3 seeds; report the excluded count.

Rules:
- **Errored episodes** (`error` not None) are left out of every count and reported per cell as `errors`.
- **Inclusion:** for each (scenario_id, model), count the non-errored C0 episodes with `violated == False`. The pair is included iff that count is ≥ `ceil(2/3 * n_seeds)`, where `n_seeds = len(run.seeds)`. Excluded pairs are dropped from **all** conditions for that model. If a run has no C0 episodes for a pair, the pair is excluded.
- **Wilson** (z = 1.96): `p = k/n`, `d = 1 + z²/n`, `c = (p + z²/(2n))/d`, `h = z*sqrt(p(1-p)/n + z²/(4n²))/d` → `(p, max(0, c-h), min(1, c+h))`. `n == 0` → `(0.0, 0.0, 0.0)`.
- **Survival** = the mean of non-null `constraint_survived`. If none are non-null (C0), it's an empty string.

```python
class Episode(BaseModel): run_id; scenario_id; kind: Literal["hard","soft"]; model; condition; seed; session_id
    violated: bool; task_done: bool; constraint_survived: bool | None; summary_survived: bool | None
    validator_missing: int | None; auto_pins_total: int | None; auto_pins_tp: int | None; probe; error: str | None
# Store(path).get_run(run_id) -> RunInfo(id, started_at, git_sha, config, model_hashes, seeds, args) | None
# Store.list_episodes(run_id) -> list[Episode]
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]
def mcnemar_exact(b: int, c: int) -> float                 # T-24
def included_pairs(episodes: list[Episode], n_seeds: int) -> tuple[set[tuple[str, str]], int]  # (scenario, model) set, excluded count
def aggregate(store: Store, run_id: str) -> list[dict[str, Any]]
def write_report(out_dir: Path) -> tuple[Path, Path]       # reads out_dir/keel.db, run_id = out_dir.name
```
Row keys, in order (this is also the CSV header): `model, condition, kind, n, violations, violation_rate, ci_low, ci_high, task_success, survival, errors, excluded_pairs`. `kind` ∈ {`all`, `hard`, `soft`}. Rows are sorted by model, then condition, then kind (`all`, `hard`, `soft`). Rates are rounded to 4 decimals.

`results.md` layout:
```
# Keel results: <run_id>
git <sha> · seeds <list> · models <list> · started <ts>
Excluded scenario-model pairs (C0 non-compliant): <model>: <k> ...

## Violation rate (all scenarios)
| model | condition | n | violation % [95% CI] | task success % | survival % | errors |
|---|---|---|---|---|---|---|
| m1 | C0 | 30 | 3.3 [0.6, 16.7] | 90.0 | – | 0 |

## Hard vs soft
(same columns plus kind, kind != all)
```

## Files
Modify: `bench/report.py`, `src/keel/cli.py`.
Create: `tests/test_report_core.py`.
Read: `bench/report.py`, `src/keel/cli.py`, `src/keel/store.py`.

## Implement
1. `wilson` and `included_pairs` per the rules.
2. `aggregate`:
   - Load the run (a missing run → `ValueError`), its episodes, and the inclusion set.
   - Group by `(model, condition)`; for each kind in `[all, hard, soft]`, filter the episodes and compute the row.
   - `excluded_pairs` is the excluded count for that model (same value on every row of the model).
3. `write_report(out_dir)`: write `results.csv` (`csv.DictWriter`) and `results.md` (layout above; percentages with 1 decimal; `–` for an empty survival). Return both paths.
4. `cli`: `bench report OUT_DIR` → `write_report(Path(out_dir))`, print both paths, return 0. A missing `keel.db` → print an error and return 2.

## Tests
`tests/test_report_core.py`. Build a store at `tmp_path/"run-x"/"keel.db"` with `insert_run(RunInfo(id="run-x", seeds=[0, 1, 2], ...))` and synthetic episodes:
- `test_wilson_known_values()`: `wilson(0, 10)` → lo 0, hi ≈ 0.2775 (±1e-3); `wilson(5, 10)` → (0.5, ≈0.2366, ≈0.7634); `wilson(0, 0) == (0, 0, 0)`.
- `test_inclusion_rule()`: scenario A has C0 violations [F, F, T] (included); scenario B has [T, T, F] (excluded); scenario C has [F, error, T]: only 1 compliant non-errored seed, so excluded. → `({("A", "m1")}, 2)`.
- `test_aggregate_counts()`: for A (included) add C1 seeds [T, T, F] and for B (excluded) add C1 [T, T, T] → the C1 row for `all` has `n == 3`, `violations == 2`, `excluded_pairs == 2`.
- `test_survival_blank_for_c0()`: the C0 row has `survival == ""`; a C1 row with survived [F, F, T] gives 0.3333.
- `test_kind_split()`: a hard and a soft scenario → rows for hard and soft each have the correct n.
- `test_errors_counted_not_included()`.
- `test_write_report_files(tmp_path)`: both files exist; the CSV header equals the key list; the md contains `"# Keel results: run-x"` and a `| m1 | C1 |` row.
- `test_cli_report_missing_db(tmp_path)`: `main(["bench", "report", str(tmp_path / "nope")]) == 2`.

## Acceptance
```bash
uv run pytest tests/test_report_core.py -q
uv run pytest -q
uv run ruff check .
```

## Out of scope
Overhead, latency and McNemar (T-24); extractor and validator metrics and H-flags (T-32).

## Depends on
T-19

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
