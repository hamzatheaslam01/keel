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


def parse_strategy(spec: str, validate_enabled: bool = False) -> list[Strategy]:
    """Parse "a+b" into strategy instances in canonical order."""
    raise NotImplementedError("T-15")


def canonical_name(strategies: list[Strategy]) -> str:
    """Names joined by "+" in order; "none" when empty."""
    raise NotImplementedError("T-15")


async def run_strategies(
    strategies: list[Strategy], state: CompactionState, ctx: StrategyContext
) -> CompactionState:
    """Apply strategies in sequence."""
    raise NotImplementedError("T-15")
