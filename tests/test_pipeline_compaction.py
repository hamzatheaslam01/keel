import respx

from keel.models import SUMMARY_PREFIX
from tests.conftest import UP
from tests.helpers import Upstream, hist

URL = f"{UP}/chat/completions"
FORCE = {"X-Keel-Session": "s1", "X-Keel-Force-Compact": "true"}
SESS = {"X-Keel-Session": "s1"}


def setup(config, strategy="summarize", keep=4, **up):
    config.compaction.strategy = strategy
    config.compaction.keep_last_n = keep
    u = Upstream(**up)
    respx.post(URL).mock(side_effect=u)
    return u


@respx.mock
async def test_forced_compaction_writes_record(config, make_client, store):
    u = setup(config)
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                         headers=FORCE)
    assert len(u.bodies) == 2
    sent = u.agent_bodies()[0]["messages"]
    assert sent[0]["content"] == "SYS" and sent[1]["content"].startswith(SUMMARY_PREFIX)
    assert sent[2:] == hist(10)[7:]
    (rec,) = store.list_compactions("s1")
    assert rec.prefix_len == 7 and rec.summary_text == "SUMMARY TEXT" and len(rec.evicted) == 6
    assert r.headers["x-keel-compacted"] == "true" and r.headers["x-keel-cache"] == "none"


@respx.mock
async def test_cache_hit_reuses_summary(config, make_client, store):
    u = setup(config)
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=FORCE)
        r = await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(12)},
                         headers=SESS)
    assert len(u.summarizer_calls()) == 1
    sent = u.agent_bodies()[-1]["messages"]
    assert sent[1]["content"].startswith(SUMMARY_PREFIX) and sent[2:] == hist(12)[7:]
    assert r.headers["x-keel-cache"] == "hit" and len(store.list_compactions("s1")) == 1


@respx.mock
async def test_mismatch_recompacts_from_change(config, make_client, store):
    u = setup(config)
    edited = hist(10)
    edited[3] = {**edited[3], "content": "EDITED"}
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=FORCE)
        r = await c.post("/v1/chat/completions", json={"model": "m1", "messages": edited},
                         headers=SESS)
    recs = store.list_compactions("s1")
    assert [x.active for x in recs] == [False, True]
    assert len(u.summarizer_calls()) == 2 and r.headers["x-keel-cache"] == "mismatch"


@respx.mock
async def test_tool_group_not_split(config, make_client):
    u = setup(config, keep=3)
    call = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"}, {"role": "user", "content": "u2"}, call,
            {"role": "tool", "tool_call_id": "c1", "content": "r"},
            {"role": "assistant", "content": "a2"}, {"role": "user", "content": "u3"}]
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": msgs},
                     headers=FORCE)
    sent = u.agent_bodies()[0]["messages"]
    assert sent[2] == call and sent[3]["role"] == "tool"


@respx.mock
async def test_strategy_none_ignores_force(config, make_client):
    u = setup(config, strategy="none")
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=FORCE)
    assert len(u.bodies) == 1 and u.bodies[0]["messages"] == hist(10)


@respx.mock
async def test_trigger_tokens_without_force(config, make_client, store):
    setup(config)
    config.compaction.trigger_tokens = 5
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=SESS)
    assert len(store.list_compactions("s1")) == 1


@respx.mock
async def test_policy_header_override(config, make_client, store):
    setup(config, strategy="none")
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers={**FORCE, "X-Keel-Policy": "summarize"})
        bad = await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                           headers={"X-Keel-Session": "s2", "X-Keel-Policy": "bogus"})
    assert len(store.list_compactions("s1")) == 1 and bad.status_code == 400


@respx.mock
async def test_compaction_failure_returns_502(config, make_client, store):
    setup(config, summarizer_status=500)
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                         headers=FORCE)
    assert r.status_code == 502 and r.json()["error"]["type"] == "keel_compaction_failed"
    assert store.list_requests("s1")[0]["status"] == 502


@respx.mock
async def test_header_pin_stored(config, make_client, store):
    setup(config)
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(2)},
                     headers={**SESS, "X-Keel-Pin": "never deploy prod"})
    (p,) = store.list_pins("s1")
    assert p.source == "explicit" and p.text == "never deploy prod"


@respx.mock
async def test_request_rows_have_cache_status(config, make_client, store):
    setup(config)
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=FORCE)
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(12)},
                     headers=SESS)
    rows = store.list_requests("s1")
    assert [r["cache_status"] for r in rows] == ["none", "hit"]
    assert [r["compacted"] for r in rows] == [1, 0]
