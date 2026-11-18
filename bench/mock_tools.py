"""Tool registry, mock outputs, filler generator, stress variant."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from bench.schema import FillerSpec, Scenario


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    default_output: str = "ok"


def load_tools(path: Path) -> dict[str, ToolSpec]:
    raise NotImplementedError("T-13")


def tool_definitions(names: list[str], tools: dict[str, ToolSpec]) -> list[dict[str, Any]]:
    raise NotImplementedError("T-13")


def mock_output(name: str, s: Scenario, tools: dict[str, ToolSpec]) -> str:
    raise NotImplementedError("T-13")


def generate_filler(spec: FillerSpec) -> str:
    raise NotImplementedError("T-13")


def stress_variant(s: Scenario, n: int, seed: int) -> Scenario:
    raise NotImplementedError("T-40")
