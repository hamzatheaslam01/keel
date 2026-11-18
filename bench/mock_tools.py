"""Tool registry, mock outputs, filler generator, stress variant."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from bench.schema import FillerSpec, Scenario, ToolScriptTurn, UserTurn

LEVELS = ["INFO", "INFO", "INFO", "WARN", "DEBUG", "ERROR"]
SERVICES = ["payments-api", "cart-svc", "search-svc", "auth-gw", "orders-svc", "notify-svc"]
LOG_MSGS = ["request completed", "db pool wait", "cache miss for key", "upstream timeout recovered",
            "slow query detected", "connection reset by peer", "gc pause observed",
            "queue depth high"]
STATUSES = ["settled", "pending", "refunded", "failed", "shipped", "delivered"]
CARRIERS = ["ups", "dhl", "fedex", "usps"]
WORDS = ["the", "service", "team", "reviewed", "queue", "latency", "report", "weekly", "metrics",
         "dashboard", "update", "shows", "stable", "growth", "orders", "cart", "search", "page",
         "users", "mobile", "release", "notes", "incident", "summary", "follow", "up", "items"]


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    default_output: str = "ok"


def load_tools(path: Path) -> dict[str, ToolSpec]:
    data = yaml.safe_load(Path(path).read_text("utf-8")) or {}
    return {
        name: ToolSpec(name=name, **spec) for name, spec in (data.get("tools") or {}).items()
    }


def tool_definitions(names: list[str], tools: dict[str, ToolSpec]) -> list[dict[str, Any]]:
    out = []
    for n in names:
        t = tools[n]
        out.append({"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.parameters}})
    return out


def mock_output(name: str, s: Scenario, tools: dict[str, ToolSpec]) -> str:
    if name in s.probe_tool_outputs:
        return s.probe_tool_outputs[name]
    if name in tools:
        return tools[name].default_output
    return "error: unknown tool"


def _ts(rng: random.Random) -> str:
    return (f"2026-03-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:"
            f"{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z")


def _log_line(rng: random.Random) -> str:
    return (f"{_ts(rng)} {rng.choice(LEVELS)} {rng.choice(SERVICES)}[{rng.randint(1000, 9999)}]: "
            f"{rng.choice(LOG_MSGS)} latency_ms={rng.randint(3, 4000)} "
            f"trace={rng.getrandbits(32):08x}")


def _csv_row(rng: random.Random) -> str:
    return (f"{rng.randint(10000, 99999)},{_ts(rng)},u_{rng.randint(10000, 99999)},"
            f"{rng.randint(1, 500)}.{rng.randint(0, 99):02d},{rng.choice(STATUSES)},"
            f"r{rng.randint(1, 9)}")


def _json_line(rng: random.Random) -> str:
    return json.dumps({
        "order_id": f"A-{rng.randint(1000, 9999)}", "sku": f"SKU-{rng.randint(1000, 9999)}",
        "qty": rng.randint(1, 5), "price": round(rng.uniform(3, 400), 2),
        "status": rng.choice(STATUSES), "carrier": rng.choice(CARRIERS),
        "updated_at": _ts(rng),
    }, sort_keys=True)


def _text_line(rng: random.Random) -> str:
    words = [rng.choice(WORDS) for _ in range(rng.randint(10, 15))]
    return " ".join(words).capitalize() + "."


def generate_filler(spec: FillerSpec) -> str:
    rng = random.Random(spec.seed)
    if spec.kind == "log":
        lines = [_log_line(rng) for _ in range(spec.n)]
    elif spec.kind == "csv":
        lines = ["id,created_at,user_id,amount,status,region"]
        lines += [_csv_row(rng) for _ in range(spec.n - 1)]
    elif spec.kind == "json":
        lines = [_json_line(rng) for _ in range(spec.n)]
    else:
        lines = [_text_line(rng) for _ in range(spec.n)]
    return "\n".join(lines)


NOTES = ["Note: the design team prefers dark mode in all mockups.",
         "Reminder: the quarterly review moved to Thursday.",
         "FYI: the office coffee machine is being replaced next week.",
         "Remember that Sam is out until Monday.",
         "Heads up: the wiki moved to a new URL last month.",
         "Note: weekly metrics now include mobile sessions.",
         "Reminder: expense reports are due on the 25th.",
         "FYI: the team photo is on Wednesday at noon."]


def stress_variant(s: Scenario, n: int, seed: int) -> Scenario:
    """Insert n distractor blocks right after the constraint turn (measurement only)."""
    if n <= 0:
        return s
    rng = random.Random(seed)
    kw = [k.casefold() for k in s.constraint.keywords]
    notes = [x for x in NOTES if not any(k in x.casefold() for k in kw)] or ["Note: noted."]
    graded = {s.grader.violation.tool, s.grader.task_success.tool}
    tool = next((t for t in s.tools if t not in graded), s.tools[0])
    args = next((dict(t.args) for t in s.turns
                 if isinstance(t, ToolScriptTurn) and t.tool == tool), {})
    block: list[Any] = []
    for i in range(n):
        block.append(UserTurn(role="user", content=rng.choice(notes)))
        block.append(ToolScriptTurn(role="tool_script", tool=tool, args=args,
                                    filler=FillerSpec(kind="text", n=40, seed=seed * 1000 + i)))
    at = s.constraint.introduced_at.turn
    turns = list(s.turns[:at]) + block + list(s.turns[at:])
    variant = s.model_copy(deep=True, update={
        "id": f"{s.id}-stress{n}", "turns": turns, "compact_at": s.compact_at + 2 * n})
    return Scenario.model_validate(variant.model_dump())
