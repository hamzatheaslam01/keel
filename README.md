# Keel

Keel is an OpenAI-compatible proxy that sits between any agent loop and its model and stops context compaction from silently deleting the agent's standing instructions. When a long conversation gets summarized, rules like "never deploy to prod" can vanish from the summary and the agent breaks them without any error. Keel compacts history for you, remembers what it evicted, and guards your rules with composable strategies: truncation, pinning and summary validation. It ships with DecayBench-lite, a deterministic benchmark that measures how often agents break rules after compaction and how much each guard helps.

## Quickstart (pip)

```bash
pip install keel-proxy
```

```bash
cp keel.example.yaml keel.yaml
```

Edit `keel.yaml` so `upstreams[].base_url` points at your model server (llama.cpp, Ollama, or any OpenAI-compatible API), then:

```bash
keel serve --config keel.yaml
```

Keel listens on `http://127.0.0.1:8400`.

## Quickstart (Docker)

```bash
docker build -t keel-proxy .
```

```bash
docker run -p 8400:8400 -v $PWD/keel.yaml:/config/keel.yaml keel-proxy
```

Inside Docker, `localhost` is the container, so point upstream `base_url`s at the host, e.g. `http://host.docker.internal:8080/v1`.

## Point your agent at Keel

Use any OpenAI client and add a session header. Without `X-Keel-Session` Keel is a pure passthrough.

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8400/v1",
    api_key="unused",
    default_headers={"X-Keel-Session": "my-agent"},
)
reply = client.chat.completions.create(
    model="qwen3-1.7b",
    messages=[{"role": "user", "content": "Never deploy to prod. Now check the logs."}],
)
```

```bash
curl -s http://127.0.0.1:8400/v1/chat/completions -H "Content-Type: application/json" -H "X-Keel-Session: demo" -d '{"model":"qwen3-1.7b","messages":[{"role":"system","content":"You are an ops agent."},{"role":"user","content":"Never deploy to prod."}]}'
```

## Guards

Strategies compose with `+`, e.g. `summarize+pin`. They always run in the order truncate → summarize → validate → pin.

| Strategy | What it does | Extra LLM calls |
|---|---|---|
| `none` | No compaction | 0 |
| `truncate` | Shortens old tool outputs to head + tail with a `[truncated N tokens]` marker | 0 |
| `summarize` | Replaces older turns with one summary written by the agent's own model | 1 per compaction |
| `validate` | A fixed small judge checks the summary still states each pin, and appends any it dropped | 1 per compaction |
| `pin` | Re-injects your pinned instructions after any compaction, right after the system prompt | 0 |

Pins come from the pin API (`POST /v1/sessions/{id}/pins`), the `X-Keel-Pin` header, or the optional auto-extractor, which scans user and tool messages for standing instructions.

## Headers

| Request header | Effect |
|---|---|
| `X-Keel-Session` | Enables compaction and tracing for this session |
| `X-Keel-Policy` | Per-request strategy override, e.g. `truncate+pin` |
| `X-Keel-Force-Compact: true` | Compact now, regardless of `trigger_tokens` |
| `X-Keel-Pin` | Add a pin inline |

| Response header | Meaning |
|---|---|
| `X-Keel-Compacted` | A compacted form was used for this request |
| `X-Keel-Tokens-Saved` | Raw prompt tokens minus tokens sent |
| `X-Keel-Pins-Injected` | Number of pins injected |
| `X-Keel-Cache` | `none`, `hit` or `mismatch` for the prefix cache |

Other endpoints: `GET /v1/models`, `GET /v1/traces`, `GET /v1/traces/{id}`, `GET /healthz`.

## Benchmark: DecayBench-lite

40 scripted scenarios (20 hard safety norms, 20 soft org policies) across devops, customer support, calendar and email, and data pipelines. In each one, a constraint arrives in an early user turn or tool output, compaction is forced, and a probe tempts the agent to break the rule. Grading is deterministic: there is no LLM judge in the grading path. The judge and extractor model are fixed across conditions, and the summarizer defaults to the agent's own model.

```bash
keel bench run --scenarios scenarios --models qwen3-1.7b,qwen3-4b --conditions C0,C1,C2,C3,C4,C5,C6 --seeds 3 --out results/run-001
```

```bash
keel bench report results/run-001
```

| Condition | Strategy | Pins |
|---|---|---|
| C0 | none (constraint visible) | none |
| C1 | summarize | none |
| C2 | truncate | none |
| C3 | summarize+pin | oracle |
| C4 | summarize+pin | auto-extracted |
| C5 | summarize+validate | oracle, judge-checked |
| C6 | truncate+pin | oracle |

The report gives violation rates with Wilson 95% CIs, a C1 vs C3 McNemar test, survival, overhead and latency. A scenario-model pair only counts if the model obeys the rule in C0 in at least 2 of 3 seeds. Validate new scenarios with `python -m bench.validate scenarios`. Step-by-step local and Kaggle instructions are in [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Results

_Results table pasted here after the benchmark run._

## Trace viewer

```bash
cd viewer && npm install && KEEL_API_URL=http://127.0.0.1:8400 npm run dev
```

Open http://localhost:3000 for a session list, per-turn timeline, before/after diff of every compaction, and highlighted pins.

_Screenshots go here._

## How it works

- The chat API is stateless, so clients resend the full history. Keel hashes each message in a chain and caches every compaction against the prefix it replaced, so later requests reuse the same compacted form. If history is edited, it recompacts from the first changed message.
- The system prompt and the last `keep_last_n` messages are never compacted.
- An assistant `tool_calls` message is never separated from its tool results.
- Pins are injected as one system message after the system prompt, only once a compaction is in effect.
- Validation uses a fixed small judge and repairs the summary verbatim.
- Every request and compaction, including evicted messages and injected pins, is written to SQLite.
- No agent frameworks are used (no LangChain, no LlamaIndex): Keel is a thin, inspectable layer.

## License

MIT. See [LICENSE](LICENSE).
