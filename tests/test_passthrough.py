import json

import httpx
import respx

from keel.pipeline import parse_keel_headers
from tests.conftest import UP, chat_json

URL = f"{UP}/chat/completions"
BODY = {
    "model": "m1",
    "tools": [{"type": "function", "function": {"name": "f", "parameters": {}}}],
    "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "res"},
    ],
    "foo": 1,
}


@respx.mock
async def test_passthrough_body_unchanged(config, make_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=chat_json()))
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json=BODY)
    assert json.loads(route.calls.last.request.content) == BODY
    assert r.status_code == 200 and r.json() == chat_json()
    assert r.headers["x-keel-cache"] == "passthrough"


@respx.mock
async def test_passthrough_logged_without_session(config, make_client, store):
    respx.post(URL).mock(return_value=httpx.Response(200, json=chat_json()))
    async with make_client(config) as c:
        await c.post("/v1/chat/completions", json=BODY)
    (row,) = store.query("SELECT * FROM requests")
    assert row["session_id"] is None
    assert row["cache_status"] == "passthrough"
    assert row["tokens_out"] == 2 and row["tokenizer"] == "fallback"


@respx.mock
async def test_session_request_logged(config, make_client, store):
    respx.post(URL).mock(return_value=httpx.Response(200, json=chat_json()))
    async with make_client(config) as c:
        for _ in range(2):
            r = await c.post("/v1/chat/completions", json=BODY, headers={"X-Keel-Session": "s1"})
    assert [x["turn_idx"] for x in store.list_requests("s1")] == [0, 1]
    assert store.get_session("s1") is not None
    assert r.headers["x-keel-compacted"] == "false"


@respx.mock
async def test_upstream_error_passed_through(config, make_client, store):
    err = {"error": {"message": "boom"}}
    respx.post(URL).mock(return_value=httpx.Response(500, json=err))
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json=BODY)
    assert r.status_code == 500 and r.json() == err
    assert store.query("SELECT status FROM requests") == [{"status": 500}]


async def test_unknown_model_404(config, make_client):
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json={**BODY, "model": "nope"})
    assert r.status_code == 404 and r.json()["error"]["type"] == "model_not_found"


async def test_stream_501(config, make_client):
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json={**BODY, "stream": True})
    assert r.status_code == 501


async def test_invalid_body_400(config, make_client):
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json={"model": "m1"})
    assert r.status_code == 400


async def test_models_and_healthz(config, make_client):
    async with make_client(config) as c:
        ids = [m["id"] for m in (await c.get("/v1/models")).json()["data"]]
        h = (await c.get("/healthz")).json()
    assert ids == ["m1", "judge"] and h == {"status": "ok"}


def test_parse_keel_headers_case_insensitive():
    h = parse_keel_headers({"x-keel-session": "a", "X-KEEL-FORCE-COMPACT": "True"})
    assert h.session_id == "a" and h.force_compact is True and h.pin is None
