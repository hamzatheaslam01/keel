"""Message hashing, prefix cache and compactable span."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from keel.models import CompactionRecord, Message


def canonical_message(msg: Message) -> str:
    raise NotImplementedError("T-14")


def message_hashes(messages: list[Message]) -> list[str]:
    raise NotImplementedError("T-14")


def first_changed_index(hashes: list[str], prefix_hashes: list[str]) -> int:
    raise NotImplementedError("T-14")


def find_span(
    messages: list[Message], keep_last_n: int, min_end: int = 0
) -> tuple[int, int] | None:
    raise NotImplementedError("T-14")


@dataclass
class CacheResult:
    working: list[Message]
    record: CompactionRecord | None
    status: Literal["none", "hit", "mismatch"]
    stale: list[CompactionRecord]
    first_changed: int | None


def apply_cache(
    raw: list[Message], hashes: list[str], records: list[CompactionRecord]
) -> CacheResult:
    raise NotImplementedError("T-14")


def raw_prefix_len(cache: CacheResult, working_end: int) -> int:
    raise NotImplementedError("T-14")
