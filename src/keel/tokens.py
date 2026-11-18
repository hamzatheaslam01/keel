"""Tokenizer registry with chars/4 fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from keel.models import Message


@dataclass
class TokenCount:
    n: int
    method: Literal["hf", "fallback"]


class TokenRegistry:
    def __init__(self, paths: dict[str, str]) -> None:
        raise NotImplementedError("T-06")

    def method(self, model: str) -> Literal["hf", "fallback"]:
        raise NotImplementedError("T-06")

    def count_text(self, model: str, text: str) -> int:
        raise NotImplementedError("T-06")

    def count_messages(
        self, model: str, messages: list[Message], tools: list[dict] | None = None
    ) -> TokenCount:
        raise NotImplementedError("T-06")

    def head_tail(self, model: str, text: str, head: int, tail: int) -> tuple[str, str, int]:
        raise NotImplementedError("T-06")
