"""Deterministic graders. No LLM, ever."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bench.schema import GraderSpec, Scenario
from keel.models import Message


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ProbeTrace:
    tool_calls: tuple[ToolCall, ...]
    text: str


def strip_think(text: str) -> str:
    raise NotImplementedError("T-12")


def probe_trace(messages: list[Message]) -> ProbeTrace:
    raise NotImplementedError("T-12")


def fires(spec: GraderSpec, trace: ProbeTrace) -> bool:
    raise NotImplementedError("T-12")


def grade(scenario: Scenario, trace: ProbeTrace) -> tuple[bool, bool]:
    raise NotImplementedError("T-12")


def keywords_present(keywords: list[str], text: str) -> bool:
    raise NotImplementedError("T-12")


def constraint_survived(keywords: list[str], messages: list[Message]) -> bool:
    raise NotImplementedError("T-12")


def keyword_hits(keywords: list[str], text: str) -> int:
    raise NotImplementedError("T-12")
