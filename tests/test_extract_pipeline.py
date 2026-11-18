import json

import respx

from keel.models import PIN_HEADER
from tests.conftest import UP
from tests.helpers import Upstream

URL = f"{UP}/chat/completions"
SESS = {"X-Keel-Session": "s1"}
FORCE = {**SESS, "X-Keel-Force-Compact": "true"}


def judge(conf=0.9):
    def f(body):
        msg = body["messages"][1]["content"]
        block = msg.split("<message>")[1]
        if "prod" in block:
            return json.dumps({"instructions": [{"text": "Never deploy to prod.",
                                                 "confidence": conf}]})
        return '{"instructions": []}'
    return f


def setup(config, conf=0.9, enabled=True, **kw):
    config.pins.auto_extract = enabled
    config.pins.extractor_model = "judge"
    config.compaction.strategy = "summarize+pin"
    config.compaction.keep_last_n = 2
    u = Upstream(summary="SUMMARY", judge_text=judge(conf), **kw)
    respx.post(URL).mock(side_effect=u)
    return u


def judge_calls(u):
    return [b for b in u.bodies if b["model"] == "judge"]


BASE = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "check logs"},
        {"role": "user", "content": "Never deploy to prod."}, {"role": "assistant", "content": "ok"}]


@respx.mock
async def test_extracts_from_user_turn(config, make_client, store):
    u = setup(config)
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": BASE}, headers=SESS)
    (p,) = store.list_pins("s1")
    assert p.source == "auto" and p.active and p.source_turn == 2
    assert len(judge_calls(u)) == 2


@respx.mock
async def test_extracts_from_tool_output(config, make_client, store):
    setup(config)
    msgs = BASE[:2] + [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": "Runbook: never touch prod."}]
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": msgs}, headers=SESS)
    assert store.list_pins("s1")[0].source_turn == 3


@respx.mock
async def test_only_new_messages_scanned(config, make_client):
    u = setup(config)
    more = BASE + [{"role": "user", "content": "next"}, {"role": "assistant", "content": "a"},
                   {"role": "user", "content": "again"}]
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": BASE}, headers=SESS)
        n = len(judge_calls(u))
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": more}, headers=SESS)
    assert len(judge_calls(u)) - n == 2


@respx.mock
async def test_edit_rescans_from_zero(config, make_client, store):
    u = setup(config)
    edited = [dict(m) for m in BASE]
    edited[1]["content"] = "check the logs please"
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": BASE}, headers=SESS)
        n = len(judge_calls(u))
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": edited},
                     headers=SESS)
    assert len(judge_calls(u)) - n == 2
    assert len(store.list_pins("s1", active_only=True)) == 1


@respx.mock
async def test_low_confidence_inactive(config, make_client, store):
    u = setup(config, conf=0.3)
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": BASE},
                     headers=FORCE)
    (p,) = store.list_pins("s1")
    assert p.active is False
    assert not any(str(m.get("content")).startswith(PIN_HEADER)
                   for m in u.agent_bodies()[-1]["messages"])


@respx.mock
async def test_auto_pin_injected_after_compaction(config, make_client):
    u = setup(config)
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": BASE},
                     headers=FORCE)
    pin_msg = u.agent_bodies()[-1]["messages"][1]["content"]
    assert pin_msg.startswith(PIN_HEADER) and "Never deploy to prod." in pin_msg


@respx.mock
async def test_extractor_failure_502(config, make_client):
    setup(config, judge_status=500)
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json={"model": "m1", "messages": BASE},
                         headers=SESS)
    assert r.status_code == 502 and r.json()["error"]["type"] == "keel_compaction_failed"


@respx.mock
async def test_disabled_makes_no_calls(config, make_client):
    u = setup(config, enabled=False)
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": BASE}, headers=SESS)
    assert judge_calls(u) == []
