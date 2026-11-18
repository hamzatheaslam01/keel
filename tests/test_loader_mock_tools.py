import pytest
import yaml

from bench.mock_tools import generate_filler, load_tools, mock_output, tool_definitions
from bench.schema import FillerSpec, Scenario, ToolScriptTurn, load_scenarios, resolve_output

FORBIDDEN = ["prod", "production", "staging", "limit", "analytics", "legal", "billing", "retry",
             "retries", "freeze", "secret", "email", "password", "customers", "pii", "eu-west",
             "us-east", "batch-1", "batch-2", "tier2", "canary"]


def minimal(sid):
    return {
        "id": sid, "kind": "hard", "domain": "devops", "system_prompt": "S",
        "constraint": {"text": "x", "introduced_at": {"turn": 1, "role": "user"},
                       "keywords": ["x"]},
        "tools": ["deploy"],
        "turns": [{"role": "user", "content": "x"}, {"role": "user", "content": "b"},
                  {"role": "user", "content": "c"}],
        "compact_at": 2, "probe": {"role": "user", "content": "p"},
        "grader": {"violation": {"type": "tool_call_forbidden", "tool": "deploy"},
                   "task_success": {"type": "tool_call_forbidden", "tool": "deploy"}},
    }


def test_load_scenarios_skips_tools_and_sorts(tmp_path):
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(minimal("b-1")))
    (tmp_path / "a.yaml").write_text(yaml.safe_dump(minimal("a-1")))
    (tmp_path / "tools.yaml").write_text("tools: {}\n")
    assert [s.id for s in load_scenarios(tmp_path)] == ["a-1", "b-1"]


def test_duplicate_ids_raise(tmp_path):
    (tmp_path / "a.yaml").write_text(yaml.safe_dump(minimal("a-1")))
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(minimal("a-1")))
    with pytest.raises(ValueError):
        load_scenarios(tmp_path)


def test_resolve_output_order(tmp_path):
    (tmp_path / "f.txt").write_text("FILE\n")
    t = ToolScriptTurn(role="tool_script", tool="x", output_file="f.txt", output="OUT",
                       filler=FillerSpec(kind="text", n=2, seed=1))
    lines = resolve_output(t, tmp_path).split("\n")
    assert lines[:2] == ["FILE", "OUT"] and len(lines) == 4


@pytest.mark.parametrize("kind", ["log", "csv", "json", "text"])
def test_filler_deterministic_and_line_count(kind):
    a = generate_filler(FillerSpec(kind=kind, n=25, seed=1))
    assert a == generate_filler(FillerSpec(kind=kind, n=25, seed=1))
    assert len(a.split("\n")) == 25
    assert a != generate_filler(FillerSpec(kind=kind, n=25, seed=2))


@pytest.mark.parametrize("kind", ["log", "csv", "json", "text"])
def test_filler_vocabulary_clean(kind):
    for seed in range(10):
        text = generate_filler(FillerSpec(kind=kind, n=200, seed=seed)).casefold()
        assert not [w for w in FORBIDDEN if w in text]


@pytest.mark.parametrize("kind,lo,hi", [("log", 80, 130), ("csv", 35, 70), ("json", 90, 160),
                                        ("text", 50, 110)])
def test_filler_lengths_roughly(kind, lo, hi):
    lines = generate_filler(FillerSpec(kind=kind, n=200, seed=3)).split("\n")
    avg = sum(map(len, lines)) / len(lines)
    assert lo <= avg <= hi


def test_tools_registry(tmp_path):
    p = tmp_path / "tools.yaml"
    p.write_text(yaml.safe_dump({"tools": {
        "deploy": {"description": "d", "parameters": {"type": "object", "properties": {
            "env": {"type": "string"}}, "required": ["env"]}},
        "read_logs": {"description": "r", "parameters": {"type": "object"},
                      "default_output": "none"},
    }}))
    tools = load_tools(p)
    defs = tool_definitions(["read_logs", "deploy"], tools)
    assert [d["function"]["name"] for d in defs] == ["read_logs", "deploy"]
    with pytest.raises(KeyError):
        tool_definitions(["zz"], tools)


def test_mock_output_precedence(tmp_path):
    s = Scenario.model_validate({**minimal("m"), "probe_tool_outputs": {"deploy": "P"}})
    p = tmp_path / "tools.yaml"
    p.write_text(yaml.safe_dump({"tools": {
        "deploy": {"description": "d", "parameters": {}, "default_output": "D"},
        "read_logs": {"description": "r", "parameters": {}, "default_output": "R"}}}))
    tools = load_tools(p)
    assert mock_output("deploy", s, tools) == "P"
    assert mock_output("read_logs", s, tools) == "R"
    assert mock_output("zz", s, tools) == "error: unknown tool"
