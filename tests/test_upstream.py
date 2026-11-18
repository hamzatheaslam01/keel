import json

import httpx
import pytest
import respx

from keel.config import UpstreamConfig
from keel.upstream import UnknownModelError, UpstreamClient, UpstreamError

A = "http://up-a.test/v1/chat/completions"
B = "http://up-b.test/v1/chat/completions"
OK = {
    "id": "x", "object": "chat.completion",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
}


@pytest.fixture
def client():
    return UpstreamClient([
        UpstreamConfig(name="a", base_url="http://up-a.test/v1", models=["m1", "m2"],
                       extra_body={"chat_template_kwargs": {"enable_thinking": False},
                                   "temperature": 0.1}),
        UpstreamConfig(name="b", base_url="http://up-b.test/v1/", models=["m3"], api_key="k"),
    ])


def test_route_and_models(client):
    assert client.route("m3").name == "b"
    assert client.models() == ["m1", "m2", "m3"]
    with pytest.raises(UnknownModelError):
        client.route("zz")


@respx.mock
async def test_forward_merges_extra_body(client):
    route = respx.post(A).mock(return_value=httpx.Response(200, json=OK))
    msgs = [{"role": "user", "content": "x"}]
    resp, ms = await client.forward({"model": "m1", "messages": msgs, "temperature": 0.9})
    sent = json.loads(route.calls.last.request.content)
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["messages"] == msgs
    assert sent["temperature"] == 0.9
    assert resp.status_code == 200 and ms >= 0


@respx.mock
async def test_forward_auth_and_trailing_slash(client):
    route = respx.post(B).mock(return_value=httpx.Response(200, json=OK))
    await client.forward({"model": "m3", "messages": []})
    assert route.calls.last.request.headers["authorization"] == "Bearer k"


@respx.mock
async def test_forward_passes_error_status(client):
    respx.post(A).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    resp, _ = await client.forward({"model": "m1", "messages": []})
    assert resp.status_code == 500


@respx.mock
async def test_complete_parses_usage(client):
    route = respx.post(A).mock(return_value=httpx.Response(200, json=OK))
    r = await client.complete("m1", [], temperature=0.0, seed=4)
    assert (r.text, r.prompt_tokens, r.completion_tokens) == ("hi", 7, 2)
    sent = json.loads(route.calls.last.request.content)
    assert sent["seed"] == 4 and "top_p" not in sent


@respx.mock
async def test_complete_raises_on_error(client):
    respx.post(A).mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(UpstreamError):
        await client.complete("m1", [], temperature=0.0)


@respx.mock
async def test_complete_wraps_connect_error(client):
    respx.post(A).mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(UpstreamError):
        await client.complete("m1", [], temperature=0.0)
