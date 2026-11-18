"""Tokenizer registry with chars/4 fallback. Tokenizers load only from local files."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tokenizers import Tokenizer

from keel.models import Message, text_of

logger = logging.getLogger("keel")


@dataclass
class TokenCount:
    n: int
    method: Literal["hf", "fallback"]


class TokenRegistry:
    def __init__(self, paths: dict[str, str]) -> None:
        self._paths = dict(paths)
        self._cache: dict[str, Tokenizer | None] = {}

    def _get(self, model: str) -> Tokenizer | None:
        if model in self._cache:
            return self._cache[model]
        tok: Tokenizer | None = None
        path = self._paths.get(model)
        if path and Path(path).is_file():
            try:
                tok = Tokenizer.from_file(path)
            except Exception:  # noqa: BLE001 - any load failure means fallback
                tok = None
        if tok is None:
            logger.warning("tokenizer fallback for %s", model)
        self._cache[model] = tok
        return tok

    def method(self, model: str) -> Literal["hf", "fallback"]:
        return "hf" if self._get(model) is not None else "fallback"

    def count_text(self, model: str, text: str) -> int:
        if not text:
            return 0
        tok = self._get(model)
        if tok is None:
            return math.ceil(len(text) / 4)
        return len(tok.encode(text, add_special_tokens=False).ids)

    def count_messages(
        self, model: str, messages: list[Message], tools: list[dict] | None = None
    ) -> TokenCount:
        n = sum(self.count_text(model, text_of(m)) + 4 for m in messages)
        if tools:
            n += self.count_text(model, json.dumps(tools, sort_keys=True))
        return TokenCount(n, self.method(model))

    def head_tail(self, model: str, text: str, head: int, tail: int) -> tuple[str, str, int]:
        tok = self._get(model)
        if tok is not None:
            ids = tok.encode(text, add_special_tokens=False).ids
            if len(ids) <= head + tail:
                return text, "", 0
            head_text = tok.decode(ids[:head])
            tail_text = tok.decode(ids[-tail:]) if tail > 0 else ""
            return head_text, tail_text, len(ids) - head - tail
        h, t = head * 4, tail * 4
        if len(text) <= h + t:
            return text, "", 0
        head_text = text[:h]
        tail_text = text[-t:] if t else ""
        return head_text, tail_text, self.count_text(model, text[h : len(text) - t])
