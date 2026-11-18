"""Model -> upstream routing and forwarding."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from keel.config import UpstreamConfig
from keel.models import Message
from keel.strategies.base import LLMResult


class UnknownModelError(KeyError):
    """No configured upstream serves this model."""


class UpstreamError(RuntimeError):
    """An internal upstream call failed."""


class UpstreamClient:
    def __init__(
        self, upstreams: list[UpstreamConfig], transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        raise NotImplementedError("T-07")

    def route(self, model: str) -> UpstreamConfig:
        raise NotImplementedError("T-07")

    def models(self) -> list[str]:
        raise NotImplementedError("T-07")

    async def forward(self, body: dict[str, Any]) -> tuple[httpx.Response, float]:
        raise NotImplementedError("T-07")

    async def forward_stream(self, body: dict[str, Any]) -> AsyncIterator[bytes]:
        raise NotImplementedError("T-33")

    async def complete(
        self,
        model: str,
        messages: list[Message],
        *,
        temperature: float,
        top_p: float | None = None,
        seed: int | None = None,
        max_tokens: int = 1024,
    ) -> LLMResult:
        raise NotImplementedError("T-07")

    async def aclose(self) -> None:
        raise NotImplementedError("T-07")
