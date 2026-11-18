"""Week-1 toy tool-calling loop (python -m bench.toy_loop)."""

from __future__ import annotations

import argparse
import asyncio

import httpx

from keel.models import Message

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Current UTC time",
        "parameters": {"type": "object", "properties": {"tz": {"type": "string"}},
                       "required": []},
    },
}]
SYSTEM = "You are a helpful assistant. Use tools when useful."
USER = "What time is it in UTC? Use the get_time tool."
TOOL_RESULT = "2026-01-01T00:00:00Z"


async def run_toy_loop(
    client: httpx.AsyncClient, model: str, session: str, max_steps: int = 3
) -> list[Message]:
    messages: list[Message] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    for _ in range(max_steps):
        r = await client.post(
            "/v1/chat/completions",
            json={"model": model, "messages": messages, "tools": TOOLS, "temperature": 0},
            headers={"X-Keel-Session": session},
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]
        msg: Message = {"role": raw.get("role") or "assistant", "content": raw.get("content") or ""}
        if raw.get("tool_calls"):
            msg["tool_calls"] = raw["tool_calls"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            break
        for call in calls:
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": TOOL_RESULT})
    return messages


def _print(messages: list[Message]) -> None:
    for m in messages:
        print(f"{m['role']}: {m.get('content') or ''}")
        for call in m.get("tool_calls") or []:
            fn = call.get("function", {})
            print(f"  -> {fn.get('name')}({fn.get('arguments')})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m bench.toy_loop")
    p.add_argument("--base-url", default="http://127.0.0.1:8400")
    p.add_argument("--model", default="qwen3-1.7b")
    p.add_argument("--session", default="toy-1")
    p.add_argument("--max-steps", type=int, default=3)
    args = p.parse_args(argv)

    async def go() -> list[Message]:
        async with httpx.AsyncClient(base_url=args.base_url, timeout=300) as client:
            return await run_toy_loop(client, args.model, args.session, args.max_steps)

    try:
        _print(asyncio.run(go()))
    except httpx.HTTPError as e:
        print(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
