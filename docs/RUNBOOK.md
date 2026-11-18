# Keel runbook

How to run DecayBench-lite locally (llama.cpp on a 4GB GPU) and on Kaggle.

## 1. Prerequisites

- Python 3.11 and [uv](https://docs.astral.sh/uv/).
- A llama.cpp build with `llama-server` (CUDA build for GPU runs).
- This repo, then:

```bash
uv sync
```

## 2. Models and tokenizers

Download Qwen3-1.7B and Qwen3-4B as Q4_K_M GGUF files into `models/`, plus each model's `tokenizer.json`:

```
models/Qwen3-1.7B-Q4_K_M.gguf
models/Qwen3-4B-Q4_K_M.gguf
models/qwen3-1.7b/tokenizer.json
models/qwen3-4b/tokenizer.json
```

Keel loads tokenizers only from these local files and makes no network calls except to configured upstreams. A missing tokenizer falls back to chars/4, logged per request as `tokenizer=fallback`.

## 3. Start llama.cpp

One `llama-server` serves one model, so run one per model. Check the flags against `llama-server --help` for your build. `--jinja` is required for chat templates and tool calls.

```bash
llama-server -m models/Qwen3-1.7B-Q4_K_M.gguf --alias qwen3-1.7b --port 8080 -c 16384 -np 1 --jinja -ngl 99
```

```bash
llama-server -m models/Qwen3-4B-Q4_K_M.gguf --alias qwen3-4b --port 8081 -c 16384 -np 1 --jinja -ngl 99
```

The judge and extractor (`qwen3-1.7b`) must be routable whenever C4 or C5 run, even when M2 is the model under test. A 4GB GPU may not fit both servers. Locally, run one model at a time and skip C4/C5 for M2. On Kaggle (T4 16GB, or 2×T4), run both.

## 4. Configure Keel

Save this as `keel.yaml`. It is gitignored. Thinking is turned off through `extra_body`.

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

The benchmark runner sets the strategy and trigger per condition itself.

## 5. Smoke test

```bash
uv run keel serve --config keel.yaml
```

```bash
curl -s http://127.0.0.1:8400/v1/chat/completions -H "Content-Type: application/json" -H "X-Keel-Session: smoke" -d '{"model":"qwen3-1.7b","messages":[{"role":"user","content":"Say hi"}]}'
```

```bash
uv run python -m bench.toy_loop --model qwen3-1.7b --session toy-1
```

The requests should appear in `keel.db` (`/v1/traces` lists them).

## 6. Measure seconds per episode

Run two scenarios first and time them:

```bash
uv run keel bench run --scenarios scenarios --models qwen3-1.7b --conditions C0,C1 --seeds 1 --limit 2 --out results/timing --config keel.yaml
```

The runner prints seconds per episode. Projected hours = `episodes × seconds per episode / 3600`. The full plan is 40 scenarios × 7 conditions × 2 models × 3 seeds = 1,680 local episodes. If the projection exceeds about 48 GPU-hours, cut to 2 seeds or 30 scenarios before cutting conditions.

Per episode the model makes 2–5 agent calls, plus 1 summarizer call (C1/C3/C4/C5), 1 judge call (C5) and about 10 extractor calls (C4).

## 7. Full run and resume

```bash
uv run keel bench run --scenarios scenarios --models qwen3-1.7b,qwen3-4b --conditions C0,C1,C2,C3,C6 --seeds 3 --out results/run-001 --config keel.yaml
```

Rerunning the same command with the same `--out` skips finished episodes. Each run writes `results/<run>/keel.db`, which holds the git SHA, the config (API keys redacted), model file hashes from `model_files`, seeds and arguments.

## 8. Kaggle

Kaggle GPU quotas change, so check your current allowance in Kaggle settings before planning a batch.

1. Create a notebook with a GPU accelerator enabled.
2. Upload `models/` (GGUF files and tokenizers) as a private Dataset and attach it.
3. Install uv and clone this repo:

```bash
pip install uv && git clone https://github.com/hamzatheaslam01/keel && cd keel && uv sync
```

4. Build llama.cpp with CUDA (`cmake -B build -DGGML_CUDA=ON && cmake --build build -j`).
5. Start both servers in the background with `nohup ... &`, pointing `-m` at the attached Dataset paths.
6. Run the benchmark into the persisted working directory:

```bash
uv run keel bench run --scenarios scenarios --models qwen3-1.7b,qwen3-4b --conditions C0,C1,C2,C3,C6 --seeds 3 --out /kaggle/working/results/run-002 --config keel.yaml
```

7. Save a notebook version so `/kaggle/working` is kept. If the session times out, start a new one and rerun the same command; finished episodes are skipped.

## 9. Hosted model (M3)

Check the provider's terms allow benchmarking and that its free quota covers about 360 episodes plus summarizer calls. Then add an upstream:

```yaml
  - name: hosted
    base_url: ${HOSTED_BASE_URL}
    api_key: ${HOSTED_API_KEY}
    models: [hosted-small]
```

Run C0, C1 and C3 only:

```bash
uv run keel bench run --models hosted-small --conditions C0,C1,C3 --seeds 3 --out results/run-m3 --config keel.yaml
```

## 10. Report

```bash
uv run keel bench report results/run-001
```

This writes `results.md`, `results.csv` and `hypotheses.json` into the run directory.

## 11. Troubleshooting

- **`tokenizer fallback for <model>` warnings:** the `tokenizers:` path is missing or wrong. Counts use chars/4. That's fine for the benchmark, which uses forced compaction, but fix it for trigger-based use.
- **Tool calls not parsed (the model answers in text):** start `llama-server` with `--jinja`.
- **Context overflow errors:** raise `-c` on `llama-server`.
- **502 `keel_compaction_failed`:** an internal summarizer, judge or extractor call failed. Check that the judge/extractor model has a running server. The runner marks the episode errored; errored episodes are counted separately and excluded from rates.
