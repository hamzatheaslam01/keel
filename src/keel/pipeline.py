"""Request pipeline (steps 1-9)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from keel.config import CompactionConfig, KeelConfig
from keel.models import CompactionRecord, Message, Pin, RequestRecord, SessionState
from keel.session import CacheResult
from keel.store import Store
from keel.tokens import TokenRegistry
from keel.upstream import UnknownModelError, UpstreamClient


@dataclass
class Deps:
    config: KeelConfig
    store: Store
    upstream: UpstreamClient
    tokens: TokenRegistry


@dataclass
class KeelHeaders:
    session_id: str | None
    policy: str | None
    force_compact: bool
    pin: str | None


@dataclass
class ChatOutcome:
    status_code: int
    body: dict[str, Any] | None
    headers: dict[str, str]
    stream: AsyncIterator[bytes] | None = None


def error_body(message: str, type_: str, code: int) -> dict[str, Any]:
    return {"error": {"message": message, "type": type_, "code": code}}


def parse_keel_headers(headers: Mapping[str, str]) -> KeelHeaders:
    h = {str(k).lower(): v for k, v in headers.items()}

    def get(name: str) -> str | None:
        v = h.get(name)
        return v if v else None

    force = (h.get("x-keel-force-compact") or "").strip().lower() == "true"
    return KeelHeaders(
        session_id=get("x-keel-session"),
        policy=get("x-keel-policy"),
        force_compact=force,
        pin=get("x-keel-pin"),
    )


def _ms_since(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def _log_error(
    deps: Deps, body: dict[str, Any], *, session_id: str | None, turn_idx: int,
    cache_status: str, t0: float, tokens_raw: int, status: int, error: str, llm_ms: float = 0.0,
) -> None:
    deps.store.insert_request(
        RequestRecord(
            session_id=session_id, turn_idx=turn_idx, upstream_model=str(body.get("model", "")),
            status=status, cache_status=cache_status,
            tokenizer=deps.tokens.method(str(body.get("model", ""))),
            tokens_in_raw=tokens_raw, tokens_in_sent=tokens_raw,
            proxy_ms=max(0.0, _ms_since(t0) - llm_ms), upstream_ms=0.0, llm_ms=llm_ms,
            error=error,
        )
    )


async def _forward_and_log(
    body: dict[str, Any],
    messages_sent: list[Message],
    deps: Deps,
    *,
    session_id: str | None,
    turn_idx: int,
    cache_status: str,
    t0: float,
    tokens_raw: int,
    compacted: bool = False,
    pin_tokens: int = 0,
    llm_ms: float = 0.0,
    extra_headers: dict[str, str] | None = None,
) -> ChatOutcome:
    """Forward `body` with `messages_sent`, log a request row, return the outcome."""
    model = str(body["model"])
    sent = {**body, "messages": messages_sent}
    tc_sent = deps.tokens.count_messages(model, messages_sent, body.get("tools"))
    try:
        resp, up_ms = await deps.upstream.forward(sent)
    except UnknownModelError:
        msg = f"model not found: {model}"
        _log_error(deps, body, session_id=session_id, turn_idx=turn_idx,
                   cache_status=cache_status, t0=t0, tokens_raw=tokens_raw, status=404,
                   error=msg, llm_ms=llm_ms)
        return ChatOutcome(404, error_body(msg, "model_not_found", 404), {})
    except httpx.HTTPError as e:
        msg = f"upstream unreachable: {type(e).__name__}: {e}"
        _log_error(deps, body, session_id=session_id, turn_idx=turn_idx,
                   cache_status=cache_status, t0=t0, tokens_raw=tokens_raw, status=502,
                   error=msg, llm_ms=llm_ms)
        return ChatOutcome(502, error_body(msg, "upstream_unreachable", 502), {})

    status = resp.status_code
    error: str | None = None
    try:
        body_json = resp.json()
    except ValueError:
        status = 502
        error = "upstream returned non-JSON"
        body_json = error_body(error, "upstream_bad_response", 502)
    if error is None and status >= 400:
        err = body_json.get("error") if isinstance(body_json, dict) else None
        error = str(err.get("message") if isinstance(err, dict) else err or resp.text[:500])
    usage = body_json.get("usage") if isinstance(body_json, dict) else None
    tokens_out = usage.get("completion_tokens") if isinstance(usage, dict) else None

    deps.store.insert_request(
        RequestRecord(
            session_id=session_id, turn_idx=turn_idx, upstream_model=model, status=status,
            cache_status=cache_status, compacted=compacted, tokenizer=tc_sent.method,
            tokens_in_raw=tokens_raw, tokens_in_sent=tc_sent.n, tokens_out=tokens_out,
            pin_tokens=pin_tokens, proxy_ms=max(0.0, _ms_since(t0) - up_ms - llm_ms),
            upstream_ms=up_ms, llm_ms=llm_ms, error=error,
        )
    )
    headers = {"X-Keel-Cache": cache_status, **(extra_headers or {})}
    return ChatOutcome(status, body_json, headers)


async def passthrough(body: dict[str, Any], deps: Deps) -> ChatOutcome:
    t0 = time.perf_counter()
    raw = body["messages"]
    tokens_raw = deps.tokens.count_messages(str(body["model"]), raw, body.get("tools")).n
    return await _forward_and_log(
        body, raw, deps, session_id=None, turn_idx=0, cache_status="passthrough", t0=t0,
        tokens_raw=tokens_raw,
    )


async def handle_chat(
    body: dict[str, Any], headers: Mapping[str, str], deps: Deps
) -> ChatOutcome:
    t0 = time.perf_counter()
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("model"), str)
        or not isinstance(body.get("messages"), list)
    ):
        msg = "body must be an object with a string 'model' and a list 'messages'"
        return ChatOutcome(400, error_body(msg, "invalid_request_error", 400), {})
    if body.get("stream"):
        return ChatOutcome(
            501, error_body("streaming not supported yet", "keel_stream_unsupported", 501), {}
        )
    hdr = parse_keel_headers(headers)
    if hdr.session_id is None:
        return await passthrough(body, deps)

    # Session path (temporary until T-16): forward unchanged and log under the session.
    sid = hdr.session_id
    deps.store.ensure_session(sid, {"strategy": deps.config.compaction.strategy})
    turn_idx = deps.store.next_turn_idx(sid)
    raw = body["messages"]
    tokens_raw = deps.tokens.count_messages(str(body["model"]), raw, body.get("tools")).n
    return await _forward_and_log(
        body, raw, deps, session_id=sid, turn_idx=turn_idx, cache_status="none", t0=t0,
        tokens_raw=tokens_raw,
        extra_headers={
            "X-Keel-Compacted": "false",
            "X-Keel-Tokens-Saved": "0",
            "X-Keel-Pins-Injected": "0",
        },
    )


def load_session(
    store: Store, session_id: str, config: KeelConfig, policy: str | None
) -> SessionState:
    raise NotImplementedError("T-16")


async def capture_constraints(
    raw: list[Message], hashes: list[str], state: SessionState, hdr: KeelHeaders, deps: Deps
) -> tuple[list[Pin], float]:
    raise NotImplementedError("T-16")


def should_compact(tokens_in: int, cfg: CompactionConfig, strategy: str, force: bool) -> bool:
    raise NotImplementedError("T-16")


async def compact(
    cache: CacheResult,
    raw: list[Message],
    hashes: list[str],
    state: SessionState,
    body: dict[str, Any],
    turn_idx: int,
    deps: Deps,
) -> tuple[CompactionRecord | None, float]:
    raise NotImplementedError("T-16")


def inject_pins(working: list[Message], pins: list[Pin]) -> tuple[list[Message], str | None]:
    raise NotImplementedError("T-22")
