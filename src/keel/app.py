"""FastAPI app and routes."""

from __future__ import annotations

from fastapi import FastAPI

from keel.config import KeelConfig
from keel.store import Store
from keel.tokens import TokenRegistry
from keel.upstream import UpstreamClient


def create_app(
    config: KeelConfig,
    store: Store | None = None,
    upstream: UpstreamClient | None = None,
    tokens: TokenRegistry | None = None,
) -> FastAPI:
    raise NotImplementedError("T-09")
