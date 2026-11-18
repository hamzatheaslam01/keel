"""The pin strategy."""

from __future__ import annotations

from typing import ClassVar

from keel.strategies.base import CompactionState, StrategyContext


class PinStrategy:
    name: ClassVar[str] = "pin"
    order: ClassVar[int] = 40

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        raise NotImplementedError("T-22")
