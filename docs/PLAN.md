# Keel delivery plan

Six milestones, one per PRD week. Implementer tasks are `T-XX` and each has its own file in `tasks/`. `HUMAN` tasks (`H-XX`) are for Hamza and have no task file. Size: S ≈ <150 changed lines, M ≈ 150–300.

## Implementer protocol

1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.

## M1: Week 1. Skeleton, passthrough, traces
**Exit criterion:** A toy tool-calling loop runs through Keel against llama.cpp and its requests show up in SQLite. A one-page prior-work note exists.

| ID | Title | Depends on | Size |
|---|---|---|---|
| H-01 | HUMAN: Prior-work check (Governance Decay repo + scenario/grader code, CliffCompaction internals + license, any tool combining them). Write `docs/prior-work.md` (≤1 page) | — | M |
| H-02 | HUMAN: Read the four PDFs; record which PRD figures are verified, with page numbers, in `docs/prior-work.md` | — | M |
| H-03 | HUMAN: `git init` + GitHub repo; install uv + Python 3.11; build llama.cpp server; download Qwen3-1.7B and Qwen3-4B Q4_K_M GGUF and each model's `tokenizer.json` into `models/` (gitignored); write a local `keel.yaml` | — | M |
| H-04 | HUMAN: Choose the M3 free-tier hosted model; check its ToS allows benchmarking and its quota covers ~360 episodes plus summarizer calls; check current Kaggle GPU quota. Note both in `docs/prior-work.md` | — | S |
| T-01 | Project scaffold, config and shared models | — | M |
| T-02 | SQLite DDL, Store skeleton, Strategy protocol | T-01 | M |
| T-03 | Scenario schema and grader contracts | T-01 | M |
| T-04 | Signature stubs for all remaining modules | T-02, T-03 | M |
| T-05 | CI workflow and repo hygiene | T-01 | S |
| T-06 | Token registry | T-04 | S |
| T-07 | Upstream client and routing | T-04 | M |
| T-08 | Store implementation | T-04 | M |
| T-09 | Passthrough pipeline and app routes | T-06, T-07, T-08 | M |
| T-10 | Trace API, pin API and `keel serve` | T-09 | M |
| T-11 | Toy tool-calling loop | T-10 | S |
| H-05 | HUMAN: Start llama.cpp, `keel serve`, run `python -m bench.toy_loop`; confirm rows in `keel.db` (**exit check**) | T-11, H-03 | S |

## M2: Week 2. Graders, runner, summarize, first numbers
**Exit criterion:** Grader tests pass. First C0 vs C1 numbers on 10 scenarios. Seconds per episode measured, and the run budget confirmed or cut.

| ID | Title | Depends on | Size |
|---|---|---|---|
| T-12 | Deterministic graders | T-04 | M |
| T-13 | Scenario loader and mock tools | T-04 | M |
| T-14 | Message hashing, prefix cache, compactable span | T-04 | M |
| T-15 | Summarize strategy and `+` composition | T-04, T-06 | M |
| T-16 | Pipeline compaction path (steps 2–7, 9) | T-09, T-14, T-15 | M |
| T-17 | History builder and conditions | T-13 | S |
| T-18 | Three example scenarios, `tools.yaml`, validation script | T-13, T-14, T-17 | M |
| T-19 | Episode runner and `keel bench run` | T-12, T-16, T-17, T-18 | M |
| T-20 | Scenarios batch 1: devops ×10 | T-18 | M |
| H-06 | HUMAN: Run `keel bench run` C0,C1 on M1 over the 10 devops scenarios, 3 seeds. Record seconds/episode, project GPU-hours for the full plan, and apply the PRD cut rule (seeds, then scenarios) if >48 h. Write `docs/budget.md` | T-19, T-20 | S |

## M3: Week 3. Truncate, pin, report, headline table
**Exit criterion:** Headline table with CIs for 5 conditions × 2 models.

| ID | Title | Depends on | Size |
|---|---|---|---|
| T-21 | Truncate strategy | T-15 | M |
| T-22 | Pin strategy and pin injection | T-16 | S |
| T-23 | Report core and `keel bench report` | T-19 | M |
| T-24 | Report metrics: survival, overhead, latency, McNemar, hard/soft | T-23 | M |
| T-25 | Scenarios batch 2: support ×10 | T-18 | M |
| T-26 | Scenarios batch 3: calendar_email ×10 | T-18 | M |
| T-27 | Scenarios batch 4: data_pipelines ×10 | T-18 | M |
| T-28 | Runbook (local + Kaggle) | T-19 | S |
| H-07 | HUMAN: Set up Kaggle notebook following `docs/RUNBOOK.md`; smoke-test 1 scenario × C0,C1 | T-28 | S |
| H-08 | HUMAN: Run C0,C1,C2,C3,C6 × M1,M2 × all scenarios × seeds; `keel bench report` | T-21..T-27, H-07 | M |

## M4: Week 4. Validate, extractor, full table
**Exit criterion:** Full table for all 7 conditions. Extractor precision and recall. H1–H5 each marked yes, no or unclear.

| ID | Title | Depends on | Size |
|---|---|---|---|
| T-29 | Validate strategy (judge + verbatim repair) | T-15 | M |
| T-30 | Auto pin extractor | T-04, T-07 | M |
| T-31 | Extractor in pipeline step 4; runner auto-pin scoring | T-16, T-19, T-30 | M |
| T-32 | Report extras: extractor P/R, validator catch rate, H1–H5 flags | T-24, T-31 | M |
| H-09 | HUMAN: Add the hosted upstream; run C4,C5 on M1,M2 and C0,C1,C3 on M3; regenerate report | T-29, T-31, T-32 | M |
| H-10 | HUMAN: Mark H1–H5 yes/no/unclear in `docs/results-notes.md` from the report | H-09 | S |

## M5: Week 5. Viewer, streaming, packaging
**Exit criterion:** Quickstart works on a clean machine in under 10 minutes. The viewer shows evicted spans and injected pins for any session.

| ID | Title | Depends on | Size |
|---|---|---|---|
| T-33 | Streaming passthrough | T-16 | M |
| T-34 | Proxy overhead test (p95 < 20 ms, truncate+pin) | T-21, T-22 | S |
| T-35 | Viewer scaffold and session list | T-10 | M |
| T-36 | Viewer session detail: timeline, compaction diff, pins | T-35 | M |
| T-37 | Packaging and Dockerfile | T-19 | S |
| T-38 | README quickstart | T-37 | S |
| H-11 | HUMAN: Clean-machine quickstart (<10 min, timed); viewer screenshots into README; paste results table into README | T-36, T-38, H-09 | M |

## M6: Week 6. Analysis, stretch, release
**Exit criterion:** The write-up, results CSV and a tagged release are public.

| ID | Title | Depends on | Size |
|---|---|---|---|
| T-39 | Summarizer-swap flag (FR-20) | T-19 | S |
| T-40 | Eviction stress variant (FR-19) | T-19 | M |
| H-12 | HUMAN: Hard vs soft analysis, FR-19/FR-20 runs if time, replication write-up answering H1–H5 | H-10 | M |
| H-13 | HUMAN: Tag release with results CSV + run configs; make repo public | H-12, H-11 | S |

## Critical path
T-01 → T-02 → T-04 → T-08 → T-09 → T-16 → T-19 → H-06 → T-22 → T-23 → H-08 → T-29/T-31 → H-09 → H-12 → H-13

(T-14 and T-15 feed T-16; T-12/T-13/T-17/T-18 feed T-19 and can run in parallel with T-14–T-16.)

## Review checkpoints (bring these back to the planner)

- **End of M1:** `git diff --stat` since start; `uv run pytest -q` output; `uv run ruff check .`; one passthrough trace (`sqlite3 keel.db "select * from requests limit 3"`); a screenshot or log of the toy loop against llama.cpp; `docs/prior-work.md`; your M3 choice; any `docs/BLOCKERS.md` entries.
- **End of M2:** full diffs of `session.py`, `pipeline.py` and `strategies/summarize.py`; pytest output; one compaction row from a C1 episode (`evicted_json` length, `summary_text`, `prefix_len`) plus the next request's `cache_status` (should be `hit`); 2 episodes' `probe_json` (one violated, one not); `docs/budget.md` with seconds/episode; C0 vs C1 raw counts.
- **End of M3:** `results/<run>/results.md` and `results.csv`; excluded-pair count; one C2 and one C6 trace (truncated marker + pin message visible); report unit-test output; the `truncate.py` diff.
- **End of M4:** full 7-condition table; extractor P/R; validator catch rate; 3 sample `validator_json` rows (one repaired); your H1–H5 draft marks; the M3 subset numbers and any quota issues.
- **End of M5:** quickstart timing log from the clean machine; viewer screenshots (list, timeline, diff); `T-34` p95 number; `docker run` output.
- **End of M6:** write-up draft; release tag URL; any FR-19/FR-20 numbers.

## Task count
M1: 11 T + 5 H · M2: 9 T + 1 H · M3: 8 T + 2 H · M4: 4 T + 2 H · M5: 6 T + 1 H · M6: 2 T + 2 H. **Total: 40 T, 13 H.**
