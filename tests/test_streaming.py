import json

import httpx
import respx

from tests.conftest import UP, chat_json
from tests.helpers import SUMMARIZER_MARK, hist

URL = f"{UP}/chat/completions"
SSE = (b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
       b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
       b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
       b'data: [DONE]\n\n')


def sse_response(request):
    body = json.loads(request.content)
    if body["messages"][0]["content"].startswith(SUMMARIZER_MARK):
        return httpx.Response(200, json=chat_json("SUMMARY"))
    if body.get("stream") is True:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=SSE)
    return httpx.Response(200, json=chat_json())


@respx.mock
async def test_stream_passthrough_bytes(config, make_client, store):
    respx.post(URL).mock(side_effect=sse_response)
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions",
                         json={"model": "m1", "stream": True, "messages": hist(2)})
    assert r.content == SSE and r.headers["content-type"].startswith("text/event-stream")
    (row,) = store.query("SELECT * FROM requests")
    assert row["tokens_out"] == 2 and row["cache_status"] == "passthrough"


@respx.mock
async def test_stream_with_session_and_compaction(config, make_client, store):
    config.compaction.strategy = "summarize"
    respx.post(URL).mock(side_effect=sse_response)
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions",
                         json={"model": "m1", "stream": True, "messages": hist(10)},
                         headers={"X-Keel-Session": "s1", "X-Keel-Force-Compact": "true"})
    assert r.content == SSE and r.headers["x-keel-compacted"] == "true"
    assert len(store.list_compactions("s1")) == 1


@respx.mock
async def test_stream_upstream_error(config, make_client, store):
    respx.post(URL).mock(return_value=httpx.Response(500, text="boom"))
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions",
                         json={"model": "m1", "stream": True, "messages": hist(2)})
    assert r.status_code in (500, 502) and "error" in r.json()
    assert store.query("SELECT error FROM requests")[0]["error"]


@respx.mock
async def test_non_stream_unchanged(config, make_client):
    respx.post(URL).mock(side_effect=sse_response)
    async with make_client(config) as c:
        r = await c.post("/v1/chat/completions", json={"model": "m1", "messages": hist(2)})
    assert r.json() == chat_json()
