"""Model -> upstream routing and forwarding."""

from __future__ import annotations

import time
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
    """Implements LLMClient."""

    def __init__(
        self, upstreams: list[UpstreamConfig], transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._upstreams = list(upstreams)
        self._client = httpx.AsyncClient(transport=transport)

    def route(self, model: str) -> UpstreamConfig:
        for up in self._upstreams:
            if model in up.models:
                return up
        raise UnknownModelError(model)

    def models(self) -> list[str]:
        seen: list[str] = []
        for up in self._upstreams:
            for m in up.models:
                if m not in seen:
                    seen.append(m)
        return seen

    def _prepare(self, body: dict[str, Any]) -> tuple[UpstreamConfig, str, dict, dict]:
        up = self.route(body["model"])
        url = up.base_url.rstrip("/") + "/chat/completions"
        payload = {**up.extra_body, **body}
        headers = {"Authorization": f"Bearer {up.api_key}"} if up.api_key else {}
        return up, url, payload, headers

    async def forward(self, body: dict[str, Any]) -> tuple[httpx.Response, float]:
        up, url, payload, headers = self._prepare(body)
        t0 = time.perf_counter()
        resp = await self._client.post(url, json=payload, headers=headers, timeout=up.timeout_s)
        return resp, (time.perf_counter() - t0) * 1000

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
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if top_p is not None:
            body["top_p"] = top_p
        if seed is not None:
            body["seed"] = seed
        try:
            resp, ms = await self.forward(body)
        except httpx.HTTPError as e:
            raise UpstreamError(f"{type(e).__name__}: {e}") from e
        if resp.status_code >= 400:
            raise UpstreamError(f"{resp.status_code}: {resp.text[:500]}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise UpstreamError(f"bad upstream response: {e}") from e
        usage = data.get("usage") or {}
        return LLMResult(
            text=content,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            ms=ms,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
