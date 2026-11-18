"""Auto pin extractor."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel

from keel.models import Message, text_of
from keel.strategies.base import LLMClient

EXTRACTOR_SYSTEM = (
    "You find standing instructions in messages. A standing instruction is a rule, restriction "
    "or policy meant to apply to future actions (for example: never do X, always do Y, only use "
    "Z). One-off requests are not standing instructions. Answer only with JSON."
)
EXTRACTOR_USER = (
    "Message ({role}):\n<message>\n{text}\n</message>\n\n"
    'Reply with JSON only: {{"instructions": [{{"text": "<the instruction, copied verbatim>", '
    '"confidence": <number from 0 to 1>}}]}}. Use an empty list if there are none.'
)

_THINK = re.compile(r"<think>.*?</think>", re.S)
_OBJ = re.compile(r"\{[\s\S]*\}")


class Candidate(BaseModel):
    text: str
    confidence: float


def parse_candidates(text: str) -> list[Candidate]:
    m = _OBJ.search(_THINK.sub("", text))
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    items = data.get("instructions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[Candidate] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        t = it.get("text")
        if not isinstance(t, str) or not t.strip():
            continue
        try:
            conf = float(it.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = min(1.0, max(0.0, conf))
        key = t.strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(Candidate(text=t.strip(), confidence=conf))
    return out


async def extract_constraints(
    messages: list[Message], llm: LLMClient, model: str, max_input_chars: int
) -> tuple[list[Candidate], float, int]:
    cands: list[Candidate] = []
    ms = 0.0
    tokens = 0
    for m in messages:
        role = m.get("role")
        if role not in ("user", "tool"):
            continue
        text = text_of(m)
        if not text.strip():
            continue
        prompt = EXTRACTOR_USER.format(role=role, text=text[:max_input_chars])
        res = await llm.complete(
            model,
            [{"role": "system", "content": EXTRACTOR_SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.0, seed=0, max_tokens=512,
        )
        ms += res.ms
        tokens += res.prompt_tokens + res.completion_tokens
        cands.extend(parse_candidates(res.text))
    return cands, ms, tokens
