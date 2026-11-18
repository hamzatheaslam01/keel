import httpx
import respx

from keel.cli import main
from tests.conftest import UP, chat_json


async def test_add_list_deactivate_pin(config, make_client):
    async with make_client(config) as c:
        r = await c.post("/v1/sessions/s1/pins", json={"text": " never deploy prod "})
        assert r.status_code == 201
        pin = r.json()
        assert pin["text"] == "never deploy prod" and pin["source"] == "explicit"
        assert len((await c.get("/v1/sessions/s1/pins")).json()["data"]) == 1
        d = await c.delete(f"/v1/sessions/s1/pins/{pin['id']}")
        assert d.json()["active"] is False
        (p,) = (await c.get("/v1/sessions/s1/pins")).json()["data"]
        assert p["active"] is False
        assert (await c.delete("/v1/sessions/s1/pins/999")).status_code == 404


async def test_add_pin_blank_400(config, make_client):
    async with make_client(config) as c:
        r = await c.post("/v1/sessions/s1/pins", json={"text": "  "})
    assert r.status_code == 400


async def test_add_pin_dedupes(config, make_client):
    async with make_client(config) as c:
        a = (await c.post("/v1/sessions/s1/pins", json={"text": "x"})).json()
        b = (await c.post("/v1/sessions/s1/pins", json={"text": "x"})).json()
    assert a["id"] == b["id"]


@respx.mock
async def test_traces_list_and_detail(config, make_client):
    respx.post(f"{UP}/chat/completions").mock(return_value=httpx.Response(200, json=chat_json()))
    body = {"model": "m1", "messages": [{"role": "user", "content": "hi"}]}
    async with make_client(config) as c:
        for _ in range(2):
            await c.post("/v1/chat/completions", json=body, headers={"X-Keel-Session": "s1"})
        await c.post("/v1/sessions/s1/pins", json={"text": "p"})
        rows = (await c.get("/v1/traces")).json()["data"]
        detail = (await c.get("/v1/traces/s1")).json()
    (s1,) = [r for r in rows if r["id"] == "s1"]
    assert s1["n_requests"] == 2
    assert len(detail["requests"]) == 2 and detail["compactions"] == []
    assert len(detail["pins"]) == 1 and isinstance(detail["session"]["config"], dict)


async def test_trace_unknown_404(config, make_client):
    async with make_client(config) as c:
        assert (await c.get("/v1/traces/nope")).status_code == 404


def test_cli_serve_bad_config(tmp_path, capsys):
    assert main(["serve", "--config", str(tmp_path / "missing.yaml")]) == 2
