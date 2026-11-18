"""Week-1 toy tool-calling loop."""

from __future__ import annotations

import httpx

from keel.models import Message


async def run_toy_loop(
    client: httpx.AsyncClient, model: str, session: str, max_steps: int = 3
) -> list[Message]:
    raise NotImplementedError("T-11")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("T-11")


if __name__ == "__main__":
    raise SystemExit(main())
