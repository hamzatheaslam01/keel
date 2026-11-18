"""Auto pin extractor."""

from __future__ import annotations

from pydantic import BaseModel

from keel.models import Message
from keel.strategies.base import LLMClient


class Candidate(BaseModel):
    text: str
    confidence: float


def parse_candidates(text: str) -> list[Candidate]:
    raise NotImplementedError("T-30")


async def extract_constraints(
    messages: list[Message], llm: LLMClient, model: str, max_input_chars: int
) -> tuple[list[Candidate], float, int]:
    raise NotImplementedError("T-30")
