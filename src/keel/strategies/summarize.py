"""The summarize strategy."""

from __future__ import annotations

from typing import ClassVar

from keel.strategies.base import CompactionState, StrategyContext


class SummarizeStrategy:
    name: ClassVar[str] = "summarize"
    order: ClassVar[int] = 20

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        raise NotImplementedError("T-15")
