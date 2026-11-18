import respx

from keel.models import PIN_HEADER, Pin
from keel.pipeline import inject_pins
from keel.strategies.base import CompactionState
from keel.strategies.pin import PinStrategy
from tests.conftest import UP
from tests.fakes import make_ctx
from tests.helpers import Upstream, hist

URL = f"{UP}/chat/completions"
FORCE = {"X-Keel-Session": "s1", "X-Keel-Force-Compact": "true"}
SESS = {"X-Keel-Session": "s1"}
SYS = {"role": "system", "content": "S"}
U = {"role": "user", "content": "u"}


def pins(*texts):
    return [Pin(session_id="s", text=t) for t in texts]


def test_inject_after_system():
    out, text = inject_pins([SYS, U], pins("a", "b"))
    assert out[0] == SYS and out[2] == U
    assert out[1]["content"] == "Standing instructions (pinned):\n- a\n- b" == text


def test_inject_without_system():
    out, _ = inject_pins([U], pins("a"))
    assert out[0]["role"] == "system" and out[1] == U


def test_no_pins_noop():
    w = [SYS, U]
    assert inject_pins(w, []) == (w, None)


async def test_pin_strategy_flag():
    st = CompactionState([SYS, U], (1, 1), [])
    out = await PinStrategy().apply(st, make_ctx())
    assert out.pins_to_inject and out.messages == st.messages


def setup(config, strategy="summarize+pin"):
    config.compaction.strategy = strategy
    config.compaction.keep_last_n = 4
    u = Upstream(summary="SUMMARY")
    respx.post(URL).mock(side_effect=u)
    return u


def has_pin(body):
    return any(str(m.get("content", "")).startswith(PIN_HEADER) for m in body["messages"])


@respx.mock
async def test_no_injection_before_compaction(config, make_client):
    u = setup(config)
    async with make_client(config) as c:
        await c.post("/v1/sessions/s1/pins", json={"text": "never prod"})
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=SESS)
    assert not has_pin(u.bodies[0])


@respx.mock
async def test_injected_on_compaction_and_cache_hit(config, make_client, store):
    u = setup(config)
    async with make_client(config) as c:
        await c.post("/v1/sessions/s1/pins", json={"text": "never prod"})
        r = await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                         headers=FORCE)
        assert u.agent_bodies()[-1]["messages"][1]["content"].startswith(PIN_HEADER)
        assert r.headers["x-keel-pins-injected"] == "1"
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(12)},
                     headers=SESS)
    assert u.agent_bodies()[-1]["messages"][1]["content"].startswith(PIN_HEADER)
    assert store.list_requests("s1")[0]["pin_tokens"] > 0
    assert store.list_compactions("s1")[0].pins_injected == ["never prod"]


@respx.mock
async def test_pin_added_later_appears_and_deactivated_disappears(config, make_client):
    u = setup(config)
    async with make_client(config) as c:
        p = (await c.post("/v1/sessions/s1/pins", json={"text": "first"})).json()
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=FORCE)
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(12)},
                     headers={**SESS, "X-Keel-Pin": "second"})
        assert u.agent_bodies()[-1]["messages"][1]["content"].count("\n- ") == 2
        await c.delete(f"/v1/sessions/s1/pins/{p['id']}")
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(14)},
                     headers=SESS)
    assert u.agent_bodies()[-1]["messages"][1]["content"].count("\n- ") == 1


@respx.mock
async def test_truncate_pin_injects(config, make_client):
    u = setup(config, "truncate+pin")
    async with make_client(config) as c:
        await c.post("/v1/sessions/s1/pins", json={"text": "never prod"})
        await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(10)},
                     headers=FORCE)
    assert has_pin(u.agent_bodies()[0]) and not u.summarizer_calls()
