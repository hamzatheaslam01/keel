# T-24: Report metrics: overhead, latency, McNemar, summary survival

## Goal
Extend the report with token overhead, added proxy latency (p50/p95), summary-only survival, and an exact McNemar paired comparison of C1 vs C3 per model.

## Context
PRD metrics:
- Token overhead: extra prompt tokens per request from pins and validation, absolute and as % of context.
- Added latency: proxy time excluding upstream LLM calls, p50 and p95.
- Statistics: for C1 vs C3, a paired comparison over scenarios (McNemar on per-scenario majority outcome).

Data available:
- `requests` table columns: `session_id, turn_idx, tokens_in_sent, pin_tokens, proxy_ms, status, error`.
- `compactions` table: `session_id, validator_json` (JSON with `prompt_tokens`, `completion_tokens` when the validator ran).
- Episodes: `session_id`, `summary_survived`.
- Each episode's requests are those with `requests.session_id = episode.session_id`. Use `store.query(sql, params)` → `list[dict]`.

Definitions (computed per model × condition, over included, non-errored episodes, kind `all` only; for kind `hard`/`soft` rows write empty strings in these new columns):
- `pin_tokens_mean` = the mean `pin_tokens` over those episodes' requests with `status == 200`.
- `overhead_pct` = `100 * sum(pin_tokens) / sum(tokens_in_sent)` over the same requests.
- `validator_tokens_mean` = the mean `prompt_tokens + completion_tokens` over those episodes' compactions with a non-null `validator_json` that contains `prompt_tokens`. Empty if none.
- `proxy_ms_p50`, `proxy_ms_p95`: nearest-rank percentile (`sorted[ceil(p/100*n)-1]`) of `proxy_ms` over those requests.
- `summary_survival` = the mean of non-null `summary_survived`; empty if none.

McNemar (C1 vs C3, per model, included pairs only):
- The per-scenario majority outcome for a condition = violated in more than half of its non-errored seeds.
- `b` = scenarios violated under C1 but not C3; `c` = violated under C3 but not C1.
- `mcnemar_exact(b, c)`: `n = b + c`; `n == 0` → 1.0; else `min(1, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n)`.
- Only scenarios with both C1 and C3 results count.

```python
def mcnemar_exact(b: int, c: int) -> float
def aggregate(store: Store, run_id: str) -> list[dict[str, Any]]   # extend rows with the new keys
def write_report(out_dir: Path) -> tuple[Path, Path]
```
New row keys, appended after `excluded_pairs` in this order: `summary_survival, pin_tokens_mean, overhead_pct, validator_tokens_mean, proxy_ms_p50, proxy_ms_p95`.

## Files
Modify: `bench/report.py`.
Create: `tests/test_report_metrics.py`.
Read: `bench/report.py`, `src/keel/store.py`.

## Implement
1. Add the private helpers `_requests_for(store, session_ids)` and `_compactions_for(store, session_ids)`, using `IN (?,?,…)` queries in chunks of 500.
2. Compute the new keys in `aggregate`.
3. Implement the stub `paired_c1_c3(store: Store, run_id: str) -> list[dict[str, Any]]`, returning rows `{model, scenarios, b, c, p_value}`.
4. In `results.md`, add a section `## Overhead and latency` (model, condition, pin tokens, overhead %, validator tokens, p50 ms, p95 ms, summary survival %) and a section `## C1 vs C3 (McNemar exact, per-scenario majority)` (model, scenarios, b, c, p).

## Tests
`tests/test_report_metrics.py` (synthetic store as in T-23: `run-x`, seeds [0, 1, 2], all pairs C0-compliant; insert matching `requests` and `compactions` rows with `store.insert_request` / `insert_compaction`):
- `test_mcnemar_values()`: `(0, 0)` → 1.0; `(0, 6)` → 0.03125; `(1, 5)` → 0.21875; `(5, 1)` → 0.21875.
- `test_percentiles_nearest_rank()`: proxy_ms [1..20] → p50 = 10, p95 = 19.
- `test_overhead_pct()`: 2 requests with pin_tokens 10 and 30, tokens_in_sent 1000 and 1000 → `pin_tokens_mean == 20`, `overhead_pct == 2.0`.
- `test_validator_tokens_mean()`: a compaction with `validator={"prompt_tokens": 300, "completion_tokens": 20, "missing": 0}` → 320.
- `test_paired_c1_c3()`: 3 scenarios where C1 majority-violated is [T, T, F] and C3 is [F, F, F] → `b=2, c=0`, `p=0.5`.
- `test_report_sections_present(tmp_path)`: `results.md` contains both new headings.

## Acceptance
```bash
uv run pytest tests/test_report_metrics.py tests/test_report_core.py -q
uv run ruff check .
```

## Out of scope
Extractor P/R, validator catch rate, H-flags (T-32); changing the inclusion rule.

## Depends on
T-23

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
