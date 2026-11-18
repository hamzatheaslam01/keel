from pathlib import Path

import yaml

from bench.mock_tools import load_tools
from bench.schema import Scenario
from bench.validate import main, validate_scenario

FIX = Path("tests/fixtures/scenarios")
TOOLS = Path("scenarios/tools.yaml")


def load(name):
    return yaml.safe_load((FIX / f"{name}.yaml").read_text("utf-8"))


def errors_for(d, tools=None):
    return validate_scenario(Scenario.model_validate(d), FIX, tools or load_tools(TOOLS))


def test_examples_valid():
    assert main([str(FIX), "--tools", str(TOOLS), "--expect-count", "3"]) == 0


def test_missing_tool_detected():
    d = load("ex-hard-ops")
    d["tools"] = ["run_shell", "deploy"]
    assert any("read_logs" in e for e in errors_for(d))


def test_constraint_not_verbatim():
    d = load("ex-hard-ops")
    d["turns"][1]["content"] = "Please be careful with deploys."
    assert any("verbatim" in e for e in errors_for(d))


def test_keyword_not_unique():
    d = load("ex-hard-ops")
    d["probe"]["content"] += " staging only, not prod"
    assert any("probe contains all keywords" in e for e in errors_for(d))


def test_not_evictable():
    d = load("ex-hard-ops")
    d["compact_at"] = 3
    assert any("not evictable" in e for e in errors_for(d))


def test_grader_arg_not_required(tmp_path):
    t = yaml.safe_load(TOOLS.read_text("utf-8"))
    t["tools"]["deploy"]["parameters"]["required"] = ["service"]
    p = tmp_path / "tools.yaml"
    p.write_text(yaml.safe_dump(t))
    assert any("not required" in e for e in errors_for(load("ex-hard-ops"), load_tools(p)))


def test_expect_count_mismatch():
    assert main([str(FIX), "--tools", str(TOOLS), "--expect-count", "4"]) == 1
