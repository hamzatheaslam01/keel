"""FastAPI app and routes."""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from keel.config import KeelConfig
from keel.pipeline import Deps, error_body, handle_chat
from keel.store import Store
from keel.tokens import TokenRegistry
from keel.upstream import UpstreamClient


def create_app(
    config: KeelConfig,
    store: Store | None = None,
    upstream: UpstreamClient | None = None,
    tokens: TokenRegistry | None = None,
) -> FastAPI:
    deps = Deps(
        config=config,
        store=store or Store(config.server.db),
        upstream=upstream or UpstreamClient(config.upstreams),
        tokens=tokens or TokenRegistry(config.tokenizers),
    )
    app = FastAPI(title="keel")
    app.state.deps = deps

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(
                error_body("invalid JSON body", "invalid_request_error", 400), status_code=400
            )
        outcome = await handle_chat(body, request.headers, deps)
        return JSONResponse(
            outcome.body, status_code=outcome.status_code, headers=outcome.headers
        )

    @app.get("/v1/models")
    async def list_models() -> dict:
        return {
            "object": "list",
            "data": [
                {"id": m, "object": "model", "owned_by": deps.upstream.route(m).name}
                for m in deps.upstream.models()
            ],
        }

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
