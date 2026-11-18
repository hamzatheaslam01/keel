"""The summarize strategy: replace the span with one LLM-written summary message."""

from __future__ import annotations

import dataclasses
import hashlib
import re
from typing import Any, ClassVar

from keel.models import SUMMARY_PREFIX, Message
from keel.strategies.base import CompactionState, StrategyContext

SUMMARIZER_SYSTEM = (
    "You compress conversation history for an AI agent so it can keep working with less context."
)
SUMMARIZER_INSTRUCTION = (
    "Summarize the conversation below. Keep the facts, decisions, tool results and open "
    "tasks the agent needs to continue. Write plain prose or short bullets, at most 300 words.\n\n"
    "<conversation>\n{transcript}\n</conversation>"
)
SUMMARIZER_PROMPT_HASH = hashlib.sha256(
    (SUMMARIZER_SYSTEM + SUMMARIZER_INSTRUCTION).encode()
).hexdigest()[:12]

_THINK = re.compile(r"<think>.*?</think>", re.S)


def _content(c: Any) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(
            str(p.get("text", "")) for p in c if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def render_transcript(messages: list[Message]) -> str:
    blocks: list[str] = []
    for m in messages:
        role = m.get("role")
        text = _content(m.get("content"))
        if role == "assistant":
            if text:
                blocks.append(f"ASSISTANT: {text}")
            for c in m.get("tool_calls") or []:
                fn = c.get("function") or {}
                blocks.append(f"ASSISTANT called {fn.get('name')}({fn.get('arguments')})")
        elif role == "tool":
            blocks.append(f"TOOL RESULT: {text}")
        elif role == "system":
            blocks.append(f"SYSTEM: {text}")
        else:
            blocks.append(f"USER: {text}")
    return "\n".join(blocks)


class SummarizeStrategy:
    name: ClassVar[str] = "summarize"
    order: ClassVar[int] = 20

    async def apply(self, state: CompactionState, ctx: StrategyContext) -> CompactionState:
        s, e = state.span
        if e <= s:
            return state
        cfg = ctx.config.compaction
        model = ctx.agent_model if cfg.summarizer == "same_as_agent" else cfg.summarizer
        prompt = SUMMARIZER_INSTRUCTION.format(transcript=render_transcript(state.messages[s:e]))
        res = await ctx.llm.complete(
            model,
            [{"role": "system", "content": SUMMARIZER_SYSTEM}, {"role": "user", "content": prompt}],
            temperature=ctx.sampling.get("temperature", 0.7),
            top_p=ctx.sampling.get("top_p"),
            seed=ctx.sampling.get("seed"),
            max_tokens=1024,
        )
        text = _THINK.sub("", res.text).strip()
        summary = {"role": "user", "content": f"{SUMMARY_PREFIX}\n{text}"}
        return dataclasses.replace(
            state,
            messages=state.messages[:s] + [summary] + state.messages[e:],
            span=(s, s + 1),
            summary_text=text,
            llm_tokens=state.llm_tokens + res.prompt_tokens + res.completion_tokens,
            llm_ms=state.llm_ms + res.ms,
        )
