import json

import httpx
import respx

from bench.toy_loop import run_toy_loop
from tests.conftest import UP, chat_json

URL = f"{UP}/chat/completions"
CALL = {"id": "call_1", "type": "function", "function": {"name": "get_time", "arguments": "{}"}}


@respx.mock
async def test_toy_loop_two_steps(config, make_client, store):
    route = respx.post(URL).mock(side_effect=[
        httpx.Response(200, json=chat_json(content=None, tool_calls=[CALL])),
        httpx.Response(200, json=chat_json("It is midnight UTC.")),
    ])
    async with make_client(config) as c:
        msgs = await run_toy_loop(c, "m1", "toy-1")
    assert msgs[-1]["content"] == "It is midnight UTC."
    assert any(m["role"] == "tool" and m["tool_call_id"] == "call_1" for m in msgs)
    assert store.next_turn_idx("toy-1") == 2
    second = json.loads(route.calls[1].request.content)
    assert any(m["role"] == "tool" for m in second["messages"])


@respx.mock
async def test_toy_loop_stops_at_max_steps(config, make_client):
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=chat_json(content=None, tool_calls=[CALL]))
    )
    async with make_client(config) as c:
        await run_toy_loop(c, "m1", "toy-2", max_steps=2)
    assert route.call_count == 2
