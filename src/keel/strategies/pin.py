"""The pin strategy: flag that the pin store is re-injected after compaction."""

from __future__ import annotations

import dataclasses
from typing import ClassVar

from keel.strategies.base import CompactionState, StrategyContext


class PinStrategy:
    name: ClassVar[str] = "pin"
    order: ClassVar[int] = 40

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        return dataclasses.replace(state, pins_to_inject=True)
