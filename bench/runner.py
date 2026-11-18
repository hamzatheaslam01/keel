"""Benchmark runner: conditions, history builder, episode and batch driver."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from bench.mock_tools import ToolSpec
from bench.schema import Scenario
from keel.config import KeelConfig
from keel.models import Episode, Message
from keel.store import Store
from keel.upstream import UpstreamClient


@dataclass(frozen=True)
class Condition:
    id: str
    strategy: str
    pins: Literal["none", "oracle", "auto"]


CONDITIONS = {
    "C0": Condition("C0", "none", "none"),
    "C1": Condition("C1", "summarize", "none"),
    "C2": Condition("C2", "truncate", "none"),
    "C3": Condition("C3", "summarize+pin", "oracle"),
    "C4": Condition("C4", "summarize+pin", "auto"),
    "C5": Condition("C5", "summarize+validate", "oracle"),
    "C6": Condition("C6", "truncate+pin", "oracle"),
}
SAMPLING = {"temperature": 0.7, "top_p": 0.9}
MAX_PROBE_STEPS = 4
BENCH_TRIGGER = 1_000_000_000


def build_history(s: Scenario, root: Path) -> tuple[list[Message], dict[int, int]]:
    raise NotImplementedError("T-17")


def condition_config(
    base: KeelConfig, cond: Condition, summarizer: str | None = None
) -> KeelConfig:
    raise NotImplementedError("T-17")


def session_id_for(run_id: str, scenario_id: str, model: str, cond: str, seed: int) -> str:
    raise NotImplementedError("T-17")


async def run_episode(
    client: httpx.AsyncClient,
    store: Store,
    s: Scenario,
    root: Path,
    model: str,
    cond: Condition,
    seed: int,
    run_id: str,
    tools: dict[str, ToolSpec],
) -> Episode:
    raise NotImplementedError("T-19")


async def run_batch(
    config: KeelConfig,
    scenarios_dir: Path,
    models: list[str],
    conditions: list[str],
    seeds: list[int],
    out: Path,
    limit: int | None = None,
    summarizer: str | None = None,
    upstream: UpstreamClient | None = None,
    stress: int = 0,
) -> str:
    raise NotImplementedError("T-19")
