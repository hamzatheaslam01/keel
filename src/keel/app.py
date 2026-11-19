"""FastAPI app and routes."""

from __future__ import annotations

import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from keel.config import KeelConfig
from keel.models import Pin
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
    deps.tokens.warm()
    app = FastAPI(title="keel")
    app.state.deps = deps

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(
                error_body("invalid JSON body", "invalid_request_error", 400), status_code=400
            )
        outcome = await handle_chat(body, request.headers, deps)
        if outcome.stream is not None:
            return StreamingResponse(
                outcome.stream, media_type="text/event-stream", headers=outcome.headers
            )
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

    def _err(msg: str, type_: str, code: int) -> JSONResponse:
        return JSONResponse(error_body(msg, type_, code), status_code=code)

    @app.post("/v1/sessions/{session_id}/pins")
    async def add_pin(session_id: str, request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or not text.strip():
            return _err("'text' must be a non-empty string", "invalid_request_error", 400)
        source_turn = data.get("source_turn")
        if source_turn is not None and not isinstance(source_turn, int):
            return _err("'source_turn' must be an integer", "invalid_request_error", 400)
        deps.store.ensure_session(session_id, {"strategy": config.compaction.strategy})
        pin = deps.store.add_pin(
            Pin(session_id=session_id, text=text.strip(), source="explicit",
                source_turn=source_turn)
        )
        return JSONResponse(pin.model_dump(), status_code=201)

    @app.get("/v1/sessions/{session_id}/pins")
    async def list_pins(session_id: str) -> dict:
        return {"data": [p.model_dump() for p in deps.store.list_pins(session_id)]}

    @app.delete("/v1/sessions/{session_id}/pins/{pin_id}")
    async def delete_pin(session_id: str, pin_id: int) -> JSONResponse:
        if not deps.store.deactivate_pin(session_id, pin_id):
            return _err(f"pin {pin_id} not found", "not_found", 404)
        return JSONResponse({"id": pin_id, "active": False})

    @app.get("/v1/traces")
    async def list_traces(limit: int = 100) -> dict:
        return {"data": deps.store.list_sessions(limit)}

    @app.get("/v1/traces/{session_id}")
    async def get_trace(session_id: str) -> JSONResponse:
        session = deps.store.get_session(session_id)
        if session is None:
            return _err(f"session {session_id} not found", "not_found", 404)
        return JSONResponse({
            "session": session,
            "requests": deps.store.list_requests(session_id),
            "compactions": [c.model_dump() for c in deps.store.list_compactions(session_id)],
            "pins": [p.model_dump() for p in deps.store.list_pins(session_id)],
        })

    return app
