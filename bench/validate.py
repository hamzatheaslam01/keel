"""Scenario validation script (python -m bench.validate scenarios/)."""

from __future__ import annotations

from pathlib import Path

from bench.mock_tools import ToolSpec
from bench.schema import Scenario


def validate_scenario(
    s: Scenario, root: Path, tools: dict[str, ToolSpec], keep_last_n: int = 4
) -> list[str]:
    raise NotImplementedError("T-18")


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("T-18")


if __name__ == "__main__":
    raise SystemExit(main())
