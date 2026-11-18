"""The validate strategy: a fixed judge checks pin coverage and repairs the summary."""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any, ClassVar

from keel.strategies.base import CompactionState, StrategyContext

JUDGE_SYSTEM = "You check whether a summary preserves specific instructions. Answer only with JSON."
JUDGE_USER = (
    "Summary:\n<summary>\n{summary}\n</summary>\n\nInstructions:\n{numbered}\n\n"
    "For each instruction, is it stated (same meaning) in the summary? "
    'Reply with JSON only: {{"covered": [true or false for each instruction, in order]}}'
)
REPAIR_HEADER = "Standing instructions (verbatim):"

_THINK = re.compile(r"<think>.*?</think>", re.S)
_OBJ = re.compile(r"\{[\s\S]*\}")


def _parse_covered(text: str, n: int) -> list[bool] | None:
    m = _OBJ.search(_THINK.sub("", text))
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    cov = data.get("covered") if isinstance(data, dict) else None
    if not isinstance(cov, list) or len(cov) != n or not all(isinstance(c, bool) for c in cov):
        return None
    return cov


class ValidateStrategy:
    name: ClassVar[str] = "validate"
    order: ClassVar[int] = 30

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        judge = ctx.config.validate_.judge_model
        if state.summary_text is None or not ctx.pins:
            reason = "no_summary" if state.summary_text is None else "no_pins"
            skip = {"judge_model": judge, "pins": [], "missing": 0, "parse_error": False,
                    "skipped": reason}
            return dataclasses.replace(state, validator=skip)

        pins = ctx.pins
        numbered = "\n".join(f"{i + 1}. {p.text}" for i, p in enumerate(pins))
        res = await ctx.llm.complete(
            judge,
            [{"role": "system", "content": JUDGE_SYSTEM},
             {"role": "user",
              "content": JUDGE_USER.format(summary=state.summary_text, numbered=numbered)}],
            temperature=0.0, seed=0, max_tokens=256,
        )
        covered = _parse_covered(res.text, len(pins))
        parse_error = covered is None
        if covered is None:
            covered = [False] * len(pins)
        missing = [p for p, c in zip(pins, covered, strict=True) if not c]

        messages = list(state.messages)
        if missing:
            i = state.span[0]
            msg = messages[i]
            block = "\n".join(f"- {p.text}" for p in missing)
            messages[i] = {**msg, "content": f"{msg['content']}\n\n{REPAIR_HEADER}\n{block}"}

        validator: dict[str, Any] = {
            "judge_model": judge,
            "pins": [{"id": p.id, "text": p.text, "covered": c}
                     for p, c in zip(pins, covered, strict=True)],
            "missing": len(missing),
            "parse_error": parse_error,
            "prompt_tokens": res.prompt_tokens,
            "completion_tokens": res.completion_tokens,
        }
        return dataclasses.replace(
            state, messages=messages, validator=validator,
            llm_tokens=state.llm_tokens + res.prompt_tokens + res.completion_tokens,
            llm_ms=state.llm_ms + res.ms,
        )
