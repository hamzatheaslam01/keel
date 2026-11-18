"""The truncate strategy: shorten old tool outputs to head + tail."""

from __future__ import annotations

import dataclasses
from typing import ClassVar

from keel.strategies.base import CompactionState, StrategyContext


class TruncateStrategy:
    name: ClassVar[str] = "truncate"
    order: ClassVar[int] = 10

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        s, e = state.span
        cfg = ctx.config.compaction.truncate
        msgs = state.messages
        after = [0] * len(msgs)
        count = 0
        for i in range(len(msgs) - 1, -1, -1):
            after[i] = count
            if msgs[i].get("role") == "assistant":
                count += 1
        out = list(msgs)
        for i in range(s, e):
            m = msgs[i]
            content = m.get("content")
            if m.get("role") != "tool" or not isinstance(content, str):
                continue
            if after[i] < cfg.older_than_turns:
                continue
            head, tail, removed = ctx.tokens.head_tail(
                ctx.agent_model, content, cfg.head_tokens, cfg.tail_tokens
            )
            if removed <= 0:
                continue
            marker = f"{head}\n[truncated {removed} tokens]"
            if cfg.tail_tokens > 0:
                marker += f"\n{tail}"
            out[i] = {**m, "content": marker}
        return dataclasses.replace(state, messages=out)
