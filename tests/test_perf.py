import math

import httpx
import pytest

from keel.app import create_app
from keel.config import KeelConfig, ServerConfig, TruncateConfig, UpstreamConfig
from keel.store import Store
from keel.upstream import UpstreamClient
from tests.conftest import UP, chat_json


def p95(xs):
    xs = sorted(xs)
    return xs[math.ceil(0.95 * len(xs)) - 1]


@pytest.mark.perf
async def test_truncate_pin_overhead_p95_under_20ms():
    cfg = KeelConfig(server=ServerConfig(db=":memory:"),
                     upstreams=[UpstreamConfig(name="u", base_url=UP, models=["m1"])])
    cfg.compaction.strategy = "truncate+pin"
    cfg.compaction.keep_last_n = 4
    cfg.compaction.trigger_tokens = 10**9
    cfg.compaction.truncate = TruncateConfig(head_tokens=50, tail_tokens=20, older_than_turns=2)
    store = Store(":memory:")
    up = UpstreamClient(cfg.upstreams, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=chat_json("ok"))))
    app = create_app(cfg, store=store, upstream=up)

    hist = [{"role": "system", "content": "SYS"}]
    for i in range(10):
        hist += [{"role": "user", "content": f"step {i}"},
                 {"role": "assistant", "content": "", "tool_calls": [
                     {"id": f"c{i}", "type": "function",
                      "function": {"name": "f", "arguments": "{}"}}]},
                 {"role": "tool", "tool_call_id": f"c{i}", "content": "x" * 3000},
                 {"role": "assistant", "content": f"done {i}"}]
    sid = {"X-Keel-Session": "perf"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://keel") as c:
        await c.post("/v1/sessions/perf/pins", json={"text": "never deploy to prod"})
        await c.post("/v1/sessions/perf/pins", json={"text": "tag tickets billing-team"})
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist},
                     headers={**sid, "X-Keel-Force-Compact": "true"})
        for i in range(50):
            hist = hist + [{"role": "user", "content": f"more {i}"},
                           {"role": "assistant", "content": f"ok {i}"}]
            await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist},
                         headers=sid)

    rows = store.list_requests("perf")
    ms = [r["proxy_ms"] for r in rows]
    print(f"\nproxy_ms p95 all={p95(ms):.2f} non-forced={p95(ms[1:]):.2f}")
    assert p95(ms) < 20.0
    assert any(r["cache_status"] == "hit" for r in rows)
    (rec,) = store.list_compactions("perf")
    assert any("[truncated" in str(m.get("content")) for m in rec.compacted)
