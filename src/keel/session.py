"""Message hashing, prefix cache and compactable span."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from keel.models import CompactionRecord, Message

_KEYS = ("role", "content", "name", "tool_calls", "tool_call_id")


def canonical_message(msg: Message) -> str:
    d = {k: msg[k] for k in _KEYS if k in msg}
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def message_hashes(messages: list[Message]) -> list[str]:
    out: list[str] = []
    prev = ""
    for m in messages:
        prev = hashlib.sha256((prev + canonical_message(m)).encode("utf-8")).hexdigest()
        out.append(prev)
    return out


def first_changed_index(hashes: list[str], prefix_hashes: list[str]) -> int:
    n = min(len(hashes), len(prefix_hashes))
    for i in range(n):
        if hashes[i] != prefix_hashes[i]:
            return i
    return n


def find_span(
    messages: list[Message], keep_last_n: int, min_end: int = 0
) -> tuple[int, int] | None:
    start = 1 if messages and messages[0].get("role") == "system" else 0
    end = len(messages) - keep_last_n
    while end > start and messages[end].get("role") == "tool":
        end -= 1
    if end <= start or end < min_end:
        return None
    return start, end


@dataclass
class CacheResult:
    working: list[Message]
    record: CompactionRecord | None
    status: Literal["none", "hit", "mismatch"]
    stale: list[CompactionRecord]
    first_changed: int | None


def _matches(raw_len: int, hashes: list[str], rec: CompactionRecord) -> bool:
    return raw_len >= rec.prefix_len > 0 and hashes[rec.prefix_len - 1] == rec.prefix_hash


def apply_cache(
    raw: list[Message], hashes: list[str], records: list[CompactionRecord]
) -> CacheResult:
    if not records:
        return CacheResult(list(raw), None, "none", [], None)
    ordered = sorted(records, key=lambda r: r.prefix_len, reverse=True)
    longest = ordered[0]
    stale: list[CompactionRecord] = []
    for rec in ordered:
        if _matches(len(raw), hashes, rec):
            working = list(rec.compacted) + list(raw[rec.prefix_len:])
            if not stale:
                return CacheResult(working, rec, "hit", [], None)
            return CacheResult(
                working, rec, "mismatch", stale, first_changed_index(hashes, longest.prefix_hashes)
            )
        stale.append(rec)
    return CacheResult(
        list(raw), None, "mismatch", stale, first_changed_index(hashes, longest.prefix_hashes)
    )


def raw_prefix_len(cache: CacheResult, working_end: int) -> int:
    rec = cache.record
    if rec is None:
        return working_end
    n = rec.prefix_len + (working_end - len(rec.compacted))
    if n < rec.prefix_len:
        raise ValueError("working_end falls inside the compacted prefix")
    return n
