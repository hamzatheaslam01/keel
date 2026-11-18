# T-28: Runbook (local + Kaggle)

## Goal
Write `docs/RUNBOOK.md`, a step-by-step guide to running the benchmark locally (llama.cpp on a 4GB GPU) and on Kaggle (free GPU), including resume and budget checks.

## Context
Facts the runbook must state:
- Models: Qwen3-1.7B and Qwen3-4B, Q4_K_M GGUF, served by `llama-server` (llama.cpp) with an OpenAI-compatible API at `http://127.0.0.1:<port>/v1`. Thinking is off via `extra_body: {chat_template_kwargs: {enable_thinking: false}}` on the upstream. llama.cpp needs `--jinja` for chat templates and tool calls.
- One `llama-server` serves one model, so run two servers (port 8080 for 1.7B, port 8081 for 4B) and configure two upstreams. The judge and extractor (`qwen3-1.7b`) must be routable whenever C4/C5 run, even for M2. A 4GB GPU may not fit both; locally, run one model at a time and skip C4/C5 for M2. On Kaggle (T4 16GB, or 2×T4) run both.
- Benchmark command: `keel bench run --scenarios scenarios --models qwen3-1.7b,qwen3-4b --conditions C0,C1,C2,C3,C6 --seeds 3 --out results/run-001 --config keel.yaml`, then `keel bench report results/run-001`.
- Resume: rerunning the same command with the same `--out` skips finished episodes (UNIQUE key per run/scenario/model/condition/seed).
- Each run writes `results/<run>/keel.db`, which holds git SHA, config (API keys redacted), model file hashes from `model_files`, seeds and args.
- The model makes 2–5 agent calls per episode plus 1 summarizer call (C1/C3/C4/C5), 1 judge call (C5) and ~10 extractor calls (C4).
- Budget rule from the PRD: measure seconds per episode first (`--limit 2`). If the projected total exceeds ~48 GPU-hours, cut to 2 seeds or 30 scenarios before cutting conditions.
- Kaggle and free-tier API quotas were not verified in the PRD. The runbook must tell the reader to check current values and must not quote numbers.
- Keel makes no network calls except to configured upstreams; tokenizers load from local `tokenizer.json` files (`tokenizers:` map).

Bench config template (put it in the runbook):
```yaml
server: {host: 127.0.0.1, port: 8400, db: keel.db}
upstreams:
  - name: local-1p7b
    base_url: http://127.0.0.1:8080/v1
    models: [qwen3-1.7b]
    extra_body: {chat_template_kwargs: {enable_thinking: false}}
  - name: local-4b
    base_url: http://127.0.0.1:8081/v1
    models: [qwen3-4b]
    extra_body: {chat_template_kwargs: {enable_thinking: false}}
compaction: {keep_last_n: 4, truncate: {older_than_turns: 3, head_tokens: 200, tail_tokens: 100}, summarizer: same_as_agent}
pins: {extractor_model: qwen3-1.7b, min_confidence: 0.6}
validate: {judge_model: qwen3-1.7b}
tokenizers: {qwen3-1.7b: models/qwen3-1.7b/tokenizer.json, qwen3-4b: models/qwen3-4b/tokenizer.json}
model_files: {qwen3-1.7b: models/Qwen3-1.7B-Q4_K_M.gguf, qwen3-4b: models/Qwen3-4B-Q4_K_M.gguf}
```
Example server command (tell readers to check flags against `llama-server --help` for their build): `llama-server -m models/Qwen3-1.7B-Q4_K_M.gguf --alias qwen3-1.7b --port 8080 -c 16384 -np 1 --jinja -ngl 99`.

## Files
Create: `docs/RUNBOOK.md`, `tests/test_runbook.py`.
Read: none beyond this file.

## Implement
1. `docs/RUNBOOK.md` with these sections, in order:
   - `## 1. Prerequisites`
   - `## 2. Models and tokenizers`
   - `## 3. Start llama.cpp`
   - `## 4. Configure Keel`
   - `## 5. Smoke test`: `keel serve`, a curl to `/v1/chat/completions`, and `python -m bench.toy_loop`
   - `## 6. Measure seconds per episode`: `--limit 2`, then the projection formula `episodes × s/episode / 3600`
   - `## 7. Full run and resume`
   - `## 8. Kaggle`: enable the GPU, upload models + tokenizers as a private Dataset, install uv, build llama.cpp with CUDA, start servers with `nohup`, run `keel bench run` with `--out /kaggle/working/results/run-00X`, save the output, and use session time limits plus resume
   - `## 9. Hosted model (M3)`: add the upstream with `${HOSTED_BASE_URL}` and `${HOSTED_API_KEY}`; run C0,C1,C3 only; check the ToS and quota first
   - `## 10. Report`
   - `## 11. Troubleshooting`: tokenizer fallback warnings, tool calls not parsed (check `--jinja`), context overflow (raise `-c`), and 502 `keel_compaction_failed`
2. Use fenced `bash` blocks for commands. Keep it under 900 words.
3. `tests/test_runbook.py::test_runbook_sections` asserts that all 11 headings exist, that `--jinja` and `enable_thinking` appear, and that the file contains no digits followed by `GPU-hours/week` (i.e. no quota numbers).

## Tests
`tests/test_runbook.py` as above.

## Acceptance
```bash
uv run pytest tests/test_runbook.py -q
```

## Out of scope
Code changes, Kaggle notebook files, actually running anything (HUMAN H-07).

## Depends on
T-19

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
