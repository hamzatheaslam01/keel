"""The validate strategy."""

from __future__ import annotations

from typing import ClassVar

from keel.strategies.base import CompactionState, StrategyContext


class ValidateStrategy:
    name: ClassVar[str] = "validate"
    order: ClassVar[int] = 30

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        raise NotImplementedError("T-29")
