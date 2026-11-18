"""Request pipeline (steps 1-9)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from keel.config import CompactionConfig, KeelConfig
from keel.extract import extract_constraints
from keel.models import PIN_HEADER, CompactionRecord, Message, Pin, RequestRecord, SessionState
from keel.session import CacheResult, apply_cache, find_span, message_hashes, raw_prefix_len
from keel.store import Store
from keel.strategies.base import (
    CompactionState,
    StrategyContext,
    StrategyError,
    canonical_name,
    parse_strategy,
    run_strategies,
)
from keel.tokens import TokenRegistry
from keel.upstream import UnknownModelError, UpstreamClient, UpstreamError

logger = logging.getLogger("keel")

_STREAM_CAP = 2 * 1024 * 1024


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
    model = str(body.get("model", ""))
    deps.store.insert_request(
        RequestRecord(
            session_id=session_id, turn_idx=turn_idx, upstream_model=model, status=status,
            cache_status=cache_status, tokenizer=deps.tokens.method(model),
            tokens_in_raw=tokens_raw, tokens_in_sent=tokens_raw,
            proxy_ms=max(0.0, _ms_since(t0) - llm_ms), upstream_ms=0.0, llm_ms=llm_ms,
            error=error[:2000],
        )
    )


def _tokens_out_from_sse(data: bytes) -> int | None:
    out: int | None = None
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        usage = obj.get("usage") if isinstance(obj, dict) else None
        if isinstance(usage, dict) and usage.get("completion_tokens") is not None:
            out = int(usage["completion_tokens"])
    return out


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
    headers = {"X-Keel-Cache": cache_status, **(extra_headers or {})}
    if "X-Keel-Tokens-Saved" in headers:
        headers["X-Keel-Tokens-Saved"] = str(tokens_raw - tc_sent.n)
    common = dict(session_id=session_id, turn_idx=turn_idx, cache_status=cache_status, t0=t0,
                  tokens_raw=tokens_raw, llm_ms=llm_ms)

    if body.get("stream") is True:
        return await _stream_and_log(sent, deps, tc_sent.n, tc_sent.method, compacted,
                                     pin_tokens, headers, **common)
    try:
        resp, up_ms = await deps.upstream.forward(sent)
    except UnknownModelError:
        msg = f"model not found: {model}"
        _log_error(deps, body, status=404, error=msg, **common)
        return ChatOutcome(404, error_body(msg, "model_not_found", 404), {})
    except httpx.HTTPError as e:
        msg = f"upstream unreachable: {type(e).__name__}: {e}"
        _log_error(deps, body, status=502, error=msg, **common)
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
    return ChatOutcome(status, body_json, headers)


async def _stream_and_log(
    sent: dict[str, Any], deps: Deps, tokens_sent: int, tokenizer: str, compacted: bool,
    pin_tokens: int, headers: dict[str, str], *, session_id: str | None, turn_idx: int,
    cache_status: str, t0: float, tokens_raw: int, llm_ms: float,
) -> ChatOutcome:
    model = str(sent["model"])
    proxy_ms = max(0.0, _ms_since(t0) - llm_ms)
    common = dict(session_id=session_id, turn_idx=turn_idx, cache_status=cache_status, t0=t0,
                  tokens_raw=tokens_raw, llm_ms=llm_ms)
    t_up = time.perf_counter()
    agen = deps.upstream.forward_stream(sent)
    try:
        first = await agen.__anext__()
    except StopAsyncIteration:
        first = b""
    except UnknownModelError:
        msg = f"model not found: {model}"
        _log_error(deps, sent, status=404, error=msg, **common)
        return ChatOutcome(404, error_body(msg, "model_not_found", 404), {})
    except (UpstreamError, httpx.HTTPError) as e:
        msg = f"upstream stream failed: {e}"
        _log_error(deps, sent, status=502, error=msg, **common)
        return ChatOutcome(502, error_body(msg, "upstream_unreachable", 502), {})

    async def gen() -> AsyncIterator[bytes]:
        buf = bytearray(first[:_STREAM_CAP])
        error: str | None = None
        try:
            if first:
                yield first
            async for chunk in agen:
                if len(buf) < _STREAM_CAP:
                    buf.extend(chunk[: _STREAM_CAP - len(buf)])
                yield chunk
        except (UpstreamError, httpx.HTTPError) as e:
            error = f"stream interrupted: {e}"
        finally:
            deps.store.insert_request(
                RequestRecord(
                    session_id=session_id, turn_idx=turn_idx, upstream_model=model,
                    status=200 if error is None else 502, cache_status=cache_status,
                    compacted=compacted, tokenizer=tokenizer, tokens_in_raw=tokens_raw,
                    tokens_in_sent=tokens_sent, tokens_out=_tokens_out_from_sse(bytes(buf)),
                    pin_tokens=pin_tokens, proxy_ms=proxy_ms,
                    upstream_ms=_ms_since(t_up), llm_ms=llm_ms, error=error,
                )
            )

    return ChatOutcome(200, None, headers, stream=gen())


async def passthrough(body: dict[str, Any], deps: Deps) -> ChatOutcome:
    t0 = time.perf_counter()
    raw = body["messages"]
    tokens_raw = deps.tokens.count_messages(str(body["model"]), raw, body.get("tools")).n
    return await _forward_and_log(
        body, raw, deps, session_id=None, turn_idx=0, cache_status="passthrough", t0=t0,
        tokens_raw=tokens_raw,
    )


def load_session(
    store: Store, session_id: str, config: KeelConfig, policy: str | None
) -> SessionState:
    cfg_c = config.compaction
    spec = policy or cfg_c.strategy
    strategy = canonical_name(parse_strategy(spec, config.validate_.enabled))
    store.ensure_session(session_id, {"strategy": strategy, "compaction": cfg_c.model_dump()})
    sess = store.get_session(session_id) or {}
    return SessionState(
        session_id=session_id,
        compaction=cfg_c,
        strategy=strategy,
        pins=store.list_pins(session_id, active_only=True),
        compactions=store.active_compactions(session_id),
        extracted_upto=int(sess.get("extracted_upto") or 0),
        extracted_hash=sess.get("extracted_hash"),
        next_turn_idx=store.next_turn_idx(session_id),
    )


async def _auto_extract(
    raw: list[Message], hashes: list[str], state: SessionState, deps: Deps
) -> tuple[list[Pin], float]:
    cfg = deps.config.pins
    upto = state.extracted_upto
    start = 0
    if 0 < upto <= len(raw) and hashes[upto - 1] == state.extracted_hash:
        start = upto
    new: list[Pin] = []
    ms_total = 0.0
    for i in range(start, len(raw)):
        if raw[i].get("role") not in ("user", "tool"):
            continue
        cands, ms, _ = await extract_constraints(
            [raw[i]], deps.upstream, cfg.extractor_model, cfg.max_input_chars
        )
        ms_total += ms
        for c in cands:
            new.append(deps.store.add_pin(Pin(
                session_id=state.session_id, text=c.text, source="auto", source_turn=i,
                confidence=c.confidence, active=c.confidence >= cfg.min_confidence,
            )))
    deps.store.set_extracted(state.session_id, len(raw), hashes[-1] if raw else None)
    return new, ms_total


async def capture_constraints(
    raw: list[Message], hashes: list[str], state: SessionState, hdr: KeelHeaders, deps: Deps
) -> tuple[list[Pin], float]:
    new: list[Pin] = []
    llm_ms = 0.0
    if hdr.pin and hdr.pin.strip():
        new.append(deps.store.add_pin(Pin(
            session_id=state.session_id, text=hdr.pin.strip(), source="explicit",
            source_turn=state.next_turn_idx,
        )))
    if deps.config.pins.auto_extract:
        pins, ms = await _auto_extract(raw, hashes, state, deps)
        new.extend(pins)
        llm_ms += ms
    return new, llm_ms


def should_compact(tokens_in: int, cfg: CompactionConfig, strategy: str, force: bool) -> bool:
    return strategy != "none" and (force or tokens_in > cfg.trigger_tokens)


async def compact(
    cache: CacheResult,
    raw: list[Message],
    hashes: list[str],
    state: SessionState,
    body: dict[str, Any],
    turn_idx: int,
    deps: Deps,
) -> tuple[CompactionRecord | None, float]:
    prev = cache.record
    span = find_span(cache.working, state.compaction.keep_last_n,
                     min_end=len(prev.compacted) if prev else 0)
    if span is None:
        return None, 0.0
    s, e = span
    model = str(body["model"])
    state0 = CompactionState(
        messages=list(cache.working), span=span, evicted=[dict(m) for m in cache.working[s:e]]
    )
    ctx = StrategyContext(
        session_id=state.session_id, agent_model=model,
        sampling={k: body[k] for k in ("temperature", "top_p", "seed") if k in body},
        config=deps.config, pins=state.pins, tokens=deps.tokens, llm=deps.upstream,
    )
    out = await run_strategies(parse_strategy(state.strategy), state0, ctx)
    prefix_len = raw_prefix_len(cache, e)
    tools = body.get("tools")
    rec = CompactionRecord(
        session_id=state.session_id, turn_idx=turn_idx, strategy=state.strategy,
        prefix_len=prefix_len, prefix_hash=hashes[prefix_len - 1],
        prefix_hashes=hashes[:prefix_len],
        tokens_before=deps.tokens.count_messages(model, cache.working, tools).n,
        tokens_after=deps.tokens.count_messages(model, out.messages, tools).n,
        evicted=out.evicted, compacted=out.messages[: out.span[1]],
        summary_text=out.summary_text,
        pins_injected=[p.text for p in state.pins] if out.pins_to_inject else [],
        validator=out.validator, llm_tokens=out.llm_tokens,
    )
    rec.id = deps.store.insert_compaction(rec)
    return rec, out.llm_ms


def inject_pins(working: list[Message], pins: list[Pin]) -> tuple[list[Message], str | None]:
    if not pins:
        return working, None
    text = PIN_HEADER + "\n" + "\n".join(f"- {p.text}" for p in pins)
    msg = {"role": "system", "content": text}
    idx = 1 if working and working[0].get("role") == "system" else 0
    return working[:idx] + [msg] + working[idx:], text


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
    hdr = parse_keel_headers(headers)
    if hdr.session_id is None:
        return await passthrough(body, deps)

    sid = hdr.session_id
    model = body["model"]
    tools = body.get("tools")
    try:
        state = load_session(deps.store, sid, deps.config, hdr.policy)
    except StrategyError as e:
        return ChatOutcome(400, error_body(str(e), "invalid_request_error", 400), {})

    raw: list[Message] = body["messages"]
    hashes = message_hashes(raw)
    cache = apply_cache(raw, hashes, state.compactions)
    force = hdr.force_compact
    if cache.stale:
        deps.store.deactivate_compactions([r.id for r in cache.stale if r.id is not None])
        logger.warning("prefix cache mismatch in %s at message %s; recompacting",
                       sid, cache.first_changed)
        force = True
    tokens_raw = deps.tokens.count_messages(model, raw, tools).n
    common = dict(session_id=sid, turn_idx=state.next_turn_idx, cache_status=cache.status,
                  t0=t0, tokens_raw=tokens_raw)

    llm_ms = 0.0
    try:
        _, ms = await capture_constraints(raw, hashes, state, hdr, deps)
        llm_ms += ms
        state.pins = deps.store.list_pins(sid, active_only=True)
        working = cache.working
        record = cache.record
        compacted_now = False
        tc = deps.tokens.count_messages(model, working, tools)
        if should_compact(tc.n, state.compaction, state.strategy, force):
            rec, ms = await compact(cache, raw, hashes, state, body, state.next_turn_idx, deps)
            llm_ms += ms
            if rec is not None:
                working = rec.compacted + raw[rec.prefix_len:]
                record = rec
                compacted_now = True
    except (UpstreamError, httpx.HTTPError, UnknownModelError) as e:
        msg = f"compaction failed: {e}"
        _log_error(deps, body, status=502, error=msg, llm_ms=llm_ms, **common)
        return ChatOutcome(502, error_body(msg, "keel_compaction_failed", 502), {})

    pin_text: str | None = None
    pin_tokens = 0
    if record is not None and "pin" in record.strategy.split("+"):
        working, pin_text = inject_pins(working, state.pins)
        if pin_text:
            pin_tokens = deps.tokens.count_text(model, pin_text) + 4
    n_pins = len(state.pins) if pin_text else 0
    return await _forward_and_log(
        body, working, deps, compacted=compacted_now, pin_tokens=pin_tokens, llm_ms=llm_ms,
        extra_headers={
            "X-Keel-Compacted": "true" if record is not None else "false",
            "X-Keel-Tokens-Saved": "0",
            "X-Keel-Pins-Injected": str(n_pins),
        },
        **common,
    )
