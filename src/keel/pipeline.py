"""Request pipeline (steps 1-9)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from keel.config import CompactionConfig, KeelConfig
from keel.models import CompactionRecord, Message, Pin, SessionState
from keel.session import CacheResult
from keel.store import Store
from keel.tokens import TokenRegistry
from keel.upstream import UpstreamClient


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


def parse_keel_headers(headers: Mapping[str, str]) -> KeelHeaders:
    raise NotImplementedError("T-09")


async def handle_chat(
    body: dict[str, Any], headers: Mapping[str, str], deps: Deps
) -> ChatOutcome:
    raise NotImplementedError("T-09")


async def passthrough(body: dict[str, Any], deps: Deps) -> ChatOutcome:
    raise NotImplementedError("T-09")


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


def error_body(message: str, type_: str, code: int) -> dict[str, Any]:
    raise NotImplementedError("T-09")
