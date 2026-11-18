"""Scenario validation script (python -m bench.validate scenarios/)."""

from __future__ import annotations

import argparse
import math
from collections import Counter
from pathlib import Path

from bench.graders import keywords_present
from bench.mock_tools import ToolSpec, load_tools
from bench.runner import build_history
from bench.schema import Scenario, ToolScriptTurn, UserTurn, load_scenario
from keel.models import text_of
from keel.session import find_span

MIN_TOKENS, MAX_TOKENS = 2500, 7000


def _est_tokens(messages: list) -> int:
    return sum(math.ceil(len(text_of(m)) / 4) + 4 for m in messages)


def validate_scenario(
    s: Scenario, root: Path, tools: dict[str, ToolSpec], keep_last_n: int = 4
) -> list[str]:
    errs: list[str] = []

    def err(msg: str) -> None:
        errs.append(f"{s.id}: {msg}")

    # 1. tools
    for t in s.tools:
        if t not in tools:
            err(f"tool {t!r} is not in tools.yaml")
    for i, turn in enumerate(s.turns, start=1):
        if isinstance(turn, ToolScriptTurn) and turn.tool not in s.tools:
            err(f"turn {i}: tool_script tool {turn.tool!r} not in scenario tools")
    for name, g in (("violation", s.grader.violation), ("task_success", s.grader.task_success)):
        if g.tool is None:
            continue
        if g.tool not in s.tools:
            err(f"{name} grader tool {g.tool!r} not in scenario tools")
        elif g.type == "tool_call_arg" and g.tool in tools:
            params = tools[g.tool].parameters
            if g.arg not in (params.get("properties") or {}):
                err(f"{name} grader arg {g.arg!r} is not a parameter of {g.tool}")
            elif g.arg not in (params.get("required") or []):
                err(f"{name} grader arg {g.arg!r} is not required by {g.tool}")

    # 2. introducing turn
    c = s.constraint
    intro = s.turns[c.introduced_at.turn - 1]
    if c.introduced_at.role == "user":
        if not isinstance(intro, UserTurn):
            err(f"turn {c.introduced_at.turn} should be a user turn")
        elif c.text not in intro.content:
            err("constraint text is not verbatim in the introducing user turn")
    else:
        if not isinstance(intro, ToolScriptTurn):
            err(f"turn {c.introduced_at.turn} should be a tool_script turn")
        elif c.text not in (intro.output or ""):
            err("constraint text is not verbatim in the introducing tool output")

    # 3. keywords in constraint text
    for k in c.keywords:
        if k.casefold() not in c.text.casefold():
            err(f"keyword {k!r} not in constraint text")

    # 5. output files
    for i, turn in enumerate(s.turns, start=1):
        if isinstance(turn, ToolScriptTurn) and turn.output_file is not None:
            if not (root / turn.output_file).is_file():
                err(f"turn {i}: output_file {turn.output_file!r} not found")
    if errs:
        return errs

    history, ends = build_history(s, root)
    intro_idx = ends[c.introduced_at.turn] - 1

    # 4. keyword uniqueness
    if keywords_present(c.keywords, s.system_prompt):
        err("system prompt contains all keywords")
    if keywords_present(c.keywords, s.probe.content):
        err("probe contains all keywords")
    for j, m in enumerate(history[1:], start=1):
        if j != intro_idx and keywords_present(c.keywords, text_of(m)):
            err(f"message {j} (not the introducing one) contains all keywords")

    # 6. evictable
    at = history[: ends[s.compact_at]]
    span = find_span(at, keep_last_n)
    if span is None or not (span[0] <= intro_idx < span[1]):
        err(f"constraint (message {intro_idx}) is not evictable at compact_at={s.compact_at} "
            f"(span {span})")

    # 7. size
    est = _est_tokens(at)
    if not MIN_TOKENS <= est <= MAX_TOKENS:
        err(f"history at compact_at is {est} est. tokens; need {MIN_TOKENS}-{MAX_TOKENS}")
    return errs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m bench.validate")
    p.add_argument("directory", nargs="?", default="scenarios")
    p.add_argument("--tools", default=None)
    p.add_argument("--keep-last-n", type=int, default=4)
    p.add_argument("--expect-count", type=int, default=None)
    args = p.parse_args(argv)

    root = Path(args.directory)
    tools = load_tools(Path(args.tools) if args.tools else root / "tools.yaml")
    errors: list[str] = []
    scenarios: list[Scenario] = []
    for path in sorted(root.glob("*.yaml")):
        if path.name == "tools.yaml":
            continue
        try:
            s = load_scenario(path)
        except ValueError as e:
            errors.append(str(e))
            continue
        if path.stem != s.id:
            errors.append(f"{path.name}: file name does not match id {s.id!r}")
        scenarios.append(s)
    ids = Counter(s.id for s in scenarios)
    errors += [f"duplicate id {i!r}" for i, n in ids.items() if n > 1]
    for s in scenarios:
        errors += validate_scenario(s, root, tools, args.keep_last_n)
    if args.expect_count is not None and len(scenarios) != args.expect_count:
        errors.append(f"expected {args.expect_count} scenarios, found {len(scenarios)}")

    for e in errors:
        print(e)
    if errors:
        print(f"FAILED {len(errors)} errors")
        return 1
    kinds = Counter(s.kind for s in scenarios)
    domains = Counter(s.domain for s in scenarios)
    per = ", ".join(f"{d} {n}" for d, n in sorted(domains.items()))
    print(f"OK {len(scenarios)} scenarios ({kinds['hard']} hard, {kinds['soft']} soft; "
          f"per domain: {per})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
