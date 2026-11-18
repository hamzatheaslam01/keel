# T-38: README quickstart

## Goal
Write `README.md`: what Keel is, a quickstart that works on a clean machine in under 10 minutes (pip and Docker), how to point an agent at it, the headers, the benchmark commands, the viewer, and placeholders for results and screenshots.

## Context
Facts to use (don't invent numbers; results are pasted in later by HUMAN H-11):
- Keel is an OpenAI-compatible proxy between an agent loop and its model. It stops context compaction from silently deleting the agent's standing instructions. Guards compose with `+`: `truncate`, `summarize`, `pin`, `validate` (e.g. `summarize+pin`).
- Endpoints: `POST /v1/chat/completions`, `GET /v1/models`, pins at `/v1/sessions/{id}/pins` (POST/GET/DELETE), `GET /v1/traces`, `GET /v1/traces/{id}`, `GET /healthz`.
- Request headers: `X-Keel-Session` (enables compaction; absent = pure passthrough), `X-Keel-Policy` (per-request strategy), `X-Keel-Force-Compact: true`, `X-Keel-Pin`. Response headers: `X-Keel-Compacted`, `X-Keel-Tokens-Saved`, `X-Keel-Pins-Injected`, `X-Keel-Cache`.
- Install: `pip install keel-proxy`; config from `keel.example.yaml`; run `keel serve --config keel.yaml`.
- Docker: `docker build -t keel-proxy .` then `docker run -p 8400:8400 -v $PWD/keel.yaml:/config/keel.yaml keel-proxy`. Inside Docker, the upstream `base_url` must point at the host (e.g. `http://host.docker.internal:8080/v1`).
- Benchmark: `keel bench run --scenarios scenarios --models qwen3-1.7b,qwen3-4b --conditions C0,C1,C2,C3,C4,C5,C6 --seeds 3 --out results/run-001`, then `keel bench report results/run-001`. Conditions: C0 none, C1 summarize, C2 truncate, C3 summarize+pin (oracle), C4 summarize+pin (auto), C5 summarize+validate (oracle), C6 truncate+pin (oracle).
- Grading is deterministic (no LLM judge in the grading path). The judge and extractor model are fixed across conditions; the summarizer defaults to the agent's own model.
- Viewer: `cd viewer && npm install && KEEL_API_URL=http://127.0.0.1:8400 npm run dev`, then open http://localhost:3000.
- Detailed local/Kaggle steps: `docs/RUNBOOK.md`. Design: `docs/ARCHITECTURE.md`. License: MIT.

## Files
Create: `README.md`, `tests/test_readme.py`.
Read: `keel.example.yaml`.

## Implement
1. Sections, in order:
   - `# Keel`: a one-paragraph pitch.
   - `## Quickstart (pip)`
   - `## Quickstart (Docker)`
   - `## Point your agent at Keel`: Python `openai` client example with `base_url="http://127.0.0.1:8400/v1"` and `default_headers={"X-Keel-Session": "my-agent"}`, plus a curl example.
   - `## Guards`: a strategy table.
   - `## Headers`
   - `## Benchmark: DecayBench-lite`
   - `## Results`: the placeholder line `_Results table pasted here after the benchmark run._`
   - `## Trace viewer`: the placeholder `_Screenshots go here._`
   - `## How it works`: 6 short bullets on the stateless-API prefix cache, the system prompt and last N messages never being compacted, tool groups never split, pins, validation, and traces.
   - `## License`
2. The curl example sends a 2-message chat with `-H "X-Keel-Session: demo"`.
3. Keep it under 1,000 words, and don't mention LangChain or LlamaIndex except to say they're not used.

## Tests
`tests/test_readme.py::test_readme_sections`: all 11 headings exist; `X-Keel-Session` and `keel bench run` appear; the text has no `%` sign with a digit right before it inside the Results section (no fabricated numbers).

## Acceptance
```bash
uv run pytest tests/test_readme.py -q
```

## Out of scope
Real results, screenshots (HUMAN H-11), code changes.

## Depends on
T-37

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
