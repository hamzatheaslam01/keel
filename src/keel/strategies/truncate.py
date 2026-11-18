"""The truncate strategy."""

from __future__ import annotations

from typing import ClassVar

from keel.strategies.base import CompactionState, StrategyContext


class TruncateStrategy:
    name: ClassVar[str] = "truncate"
    order: ClassVar[int] = 10

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        raise NotImplementedError("T-21")
