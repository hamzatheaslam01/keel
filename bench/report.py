"""Inclusion rule, Wilson CI, McNemar, aggregation, results.md/csv."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from keel.models import Episode
from keel.store import Store


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    raise NotImplementedError("T-23")


def mcnemar_exact(b: int, c: int) -> float:
    raise NotImplementedError("T-23")


def included_pairs(episodes: list[Episode], n_seeds: int) -> tuple[set[tuple[str, str]], int]:
    raise NotImplementedError("T-23")


def aggregate(store: Store, run_id: str) -> list[dict[str, Any]]:
    raise NotImplementedError("T-23")


def paired_c1_c3(store: Store, run_id: str) -> list[dict[str, Any]]:
    raise NotImplementedError("T-24")


def extractor_metrics(store: Store, run_id: str) -> list[dict[str, Any]]:
    raise NotImplementedError("T-32")


def validator_metrics(store: Store, run_id: str) -> list[dict[str, Any]]:
    raise NotImplementedError("T-32")


def hypotheses(
    rows: list[dict], extractor: list[dict], validator: list[dict]
) -> list[dict[str, str]]:
    raise NotImplementedError("T-32")


def write_report(out_dir: Path) -> tuple[Path, Path]:
    raise NotImplementedError("T-23")
