"""Strategy protocol, compaction state and `+` composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from pydantic import BaseModel

from keel.config import KeelConfig
from keel.models import Message, Pin

if TYPE_CHECKING:
    from keel.tokens import TokenRegistry


class LLMResult(BaseModel):
    text: str
    prompt_tokens: int
    completion_tokens: int
    ms: float


class LLMClient(Protocol):
    async def complete(
        self,
        model: str,
        messages: list[Message],
        *,
        temperature: float,
        top_p: float | None = None,
        seed: int | None = None,
        max_tokens: int = 1024,
    ) -> LLMResult: ...


@dataclass
class CompactionState:
    messages: list[Message]  # working list being rewritten (whole request)
    span: tuple[int, int]  # [start, end) the strategy may rewrite
    evicted: list[Message]  # copy of original messages[start:end]
    summary_text: str | None = None
    validator: dict[str, Any] | None = None
    pins_to_inject: bool = False
    llm_tokens: int = 0
    llm_ms: float = 0.0


@dataclass
class StrategyContext:
    session_id: str
    agent_model: str
    sampling: dict[str, Any]  # temperature/top_p/seed from the request (may be empty)
    config: KeelConfig
    pins: list[Pin]
    tokens: TokenRegistry
    llm: LLMClient


class Strategy(Protocol):
    name: ClassVar[str]
    order: ClassVar[int]  # truncate 10, summarize 20, validate 30, pin 40

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState: ...


class StrategyError(ValueError):
    """Invalid strategy specification."""


def _registry() -> dict[str, type]:
    from keel.strategies.pin import PinStrategy
    from keel.strategies.summarize import SummarizeStrategy
    from keel.strategies.truncate import TruncateStrategy
    from keel.strategies.validate import ValidateStrategy

    return {c.name: c for c in (TruncateStrategy, SummarizeStrategy, ValidateStrategy, PinStrategy)}


def parse_strategy(spec: str, validate_enabled: bool = False) -> list[Strategy]:
    """Parse "a+b" into strategy instances in canonical order."""
    names = [p.strip() for p in (spec or "").split("+") if p.strip()]
    if not names or names == ["none"]:
        return []
    if "none" in names:
        raise StrategyError("'none' cannot be combined with other strategies")
    reg = _registry()
    unknown = [n for n in names if n not in reg]
    if unknown:
        raise StrategyError(f"unknown strategy: {', '.join(unknown)}")
    if len(set(names)) != len(names):
        raise StrategyError(f"duplicate strategy in {spec!r}")
    if validate_enabled and "summarize" in names and "validate" not in names:
        names.append("validate")
    if "validate" in names and "summarize" not in names:
        raise StrategyError("'validate' requires 'summarize'")
    return sorted((reg[n]() for n in names), key=lambda s: s.order)


def canonical_name(strategies: list[Strategy]) -> str:
    """Names joined by "+" in order; "none" when empty."""
    return "+".join(s.name for s in strategies) or "none"


async def run_strategies(
    strategies: list[Strategy], state: CompactionState, ctx: StrategyContext
) -> CompactionState:
    """Apply strategies in sequence."""
    for s in strategies:
        state = await s.apply(state, ctx)
    return state
