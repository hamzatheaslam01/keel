"""Tokenizer registry with chars/4 fallback. Tokenizers load only from local files."""

from __future__ import annotations

import hashlib
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
    def __init__(self, paths: dict[str, str], max_cached_counts: int = 50_000) -> None:
        self._paths = dict(paths)
        self._cache: dict[str, Tokenizer | None] = {}
        # Clients resend the whole history every turn, so the same message texts are
        # counted again and again. Remember counts by a digest of (model, text).
        self._counts: dict[bytes, int] = {}
        self._max_counts = max_cached_counts

    def warm(self) -> None:
        """Load every configured tokenizer now instead of on the first request."""
        for model in self._paths:
            self._get(model)

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
        key = self._key(model, text)
        n = self._counts.get(key)
        if n is None:
            n = len(tok.encode(text, add_special_tokens=False).ids)
            if len(self._counts) >= self._max_counts:
                self._counts.clear()
            self._counts[key] = n
        return n

    def _key(self, model: str, text: str) -> bytes:
        return hashlib.blake2b(f"{model}\x00{text}".encode(), digest_size=16).digest()

    def _prime(self, model: str, texts: list[str]) -> None:
        """Tokenize all not-yet-counted texts in one parallel batch and cache the counts."""
        tok = self._get(model)
        if tok is None:
            return
        todo: dict[bytes, str] = {}
        for t in texts:
            if t:
                k = self._key(model, t)
                if k not in self._counts:
                    todo[k] = t
        if len(todo) < 2:
            return
        encs = tok.encode_batch(list(todo.values()), add_special_tokens=False)
        if len(self._counts) + len(todo) > self._max_counts:
            self._counts.clear()
        for k, enc in zip(todo, encs, strict=True):
            self._counts[k] = len(enc.ids)

    def count_messages(
        self, model: str, messages: list[Message], tools: list[dict] | None = None
    ) -> TokenCount:
        texts = [text_of(m) for m in messages]
        tools_text = json.dumps(tools, sort_keys=True) if tools else ""
        self._prime(model, texts + [tools_text])
        n = sum(self.count_text(model, t) + 4 for t in texts)
        if tools_text:
            n += self.count_text(model, tools_text)
        return TokenCount(n, self.method(model))

    def head_tail(self, model: str, text: str, head: int, tail: int) -> tuple[str, str, int]:
        tok = self._get(model)
        if tok is not None:
            if self.count_text(model, text) <= head + tail:  # cached; avoids a re-encode
                return text, "", 0
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
