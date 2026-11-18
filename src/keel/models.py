"""Shared data models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from keel.config import CompactionConfig

Message = dict[str, Any]
PIN_HEADER = "Standing instructions (pinned):"
SUMMARY_PREFIX = "[Summary of earlier conversation]"


def text_of(msg: Message) -> str:
    """Content text plus "\\n<name> <arguments>" for each tool call."""
    content = msg.get("content")
    if isinstance(content, str):
        out = content
    elif isinstance(content, list):
        out = "\n".join(
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    else:
        out = ""
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") or {}
        out += "\n" + str(fn.get("name", "")) + " " + str(fn.get("arguments", ""))
    return out


class Pin(BaseModel):
    id: int | None = None
    session_id: str
    text: str
    source: Literal["explicit", "auto"] = "explicit"
    source_turn: int | None = None
    confidence: float = 1.0
    active: bool = True


class CompactionRecord(BaseModel):
    id: int | None = None
    session_id: str
    turn_idx: int
    strategy: str
    prefix_len: int
    prefix_hash: str
    prefix_hashes: list[str]
    tokens_before: int
    tokens_after: int
    evicted: list[Message]
    compacted: list[Message]
    summary_text: str | None = None
    pins_injected: list[str] = Field(default_factory=list)
    validator: dict[str, Any] | None = None
    llm_tokens: int = 0
    active: bool = True


class RequestRecord(BaseModel):
    session_id: str | None
    turn_idx: int
    upstream_model: str
    status: int
    cache_status: Literal["passthrough", "none", "hit", "mismatch"]
    compacted: bool = False
    tokenizer: Literal["hf", "fallback"]
    tokens_in_raw: int
    tokens_in_sent: int
    tokens_out: int | None = None
    pin_tokens: int = 0
    proxy_ms: float
    upstream_ms: float
    llm_ms: float = 0.0
    error: str | None = None


class SessionState(BaseModel):
    session_id: str
    compaction: CompactionConfig
    strategy: str
    pins: list[Pin]
    compactions: list[CompactionRecord]
    extracted_upto: int = 0
    extracted_hash: str | None = None
    next_turn_idx: int = 0


class RunInfo(BaseModel):
    id: str
    started_at: str
    git_sha: str
    config: dict[str, Any]
    model_hashes: dict[str, str]
    seeds: list[int]
    args: dict[str, Any]


class Episode(BaseModel):
    run_id: str
    scenario_id: str
    kind: Literal["hard", "soft"]
    model: str
    condition: str
    seed: int
    session_id: str
    violated: bool = False
    task_done: bool = False
    constraint_survived: bool | None = None
    summary_survived: bool | None = None
    validator_missing: int | None = None
    auto_pins_total: int | None = None
    auto_pins_tp: int | None = None
    probe: list[Message] = Field(default_factory=list)
    error: str | None = None
