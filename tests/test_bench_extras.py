"""T-37 serve flags, T-39 summarizer swap, T-40 stress variant."""

import json
import shutil

import httpx
import respx
import yaml

from bench.mock_tools import stress_variant
from bench.runner import build_history, run_batch
from bench.schema import Scenario, load_scenario
from keel import cli
from keel.cli import main
from keel.session import find_span
from keel.store import Store
from keel.upstream import UpstreamClient
from tests.conftest import UP
from tests.test_runner import Bench

FIX = "tests/fixtures/scenarios/ex-hard-ops.yaml"


def test_serve_overrides(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: seen.update(kw))
    p = tmp_path / "keel.yaml"
    p.write_text("server: {db: ':memory:'}\n")
    assert main(["serve", "--config", str(p), "--host", "0.0.0.0", "--port", "9999"]) == 0
    assert seen == {"host": "0.0.0.0", "port": 9999}


def sc_dir(tmp_path):
    d = tmp_path / "sc"
    d.mkdir()
    shutil.copy(FIX, d)
    shutil.copy("scenarios/tools.yaml", d)
    return d


@respx.mock
async def test_summarizer_model_used(config, tmp_path):
    config.upstreams[0].models.append("big")
    b = Bench()
    respx.post(f"{UP}/chat/completions").mock(side_effect=b)
    rid = await run_batch(config, sc_dir(tmp_path), ["m1"], ["C1"], [0], tmp_path / "r",
                          summarizer="big", upstream=UpstreamClient(config.upstreams))
    summ = [x for x in b.bodies if x["messages"][0]["content"].startswith("You compress")]
    agent = [x for x in b.bodies if x not in summ]
    assert summ and all(x["model"] == "big" for x in summ)
    assert all(x["model"] == "m1" for x in agent)
    assert Store(str(tmp_path / "r" / "keel.db")).get_run(rid).args["summarizer"] == "big"


def test_cli_rejects_unknown_summarizer(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text(yaml.safe_dump({"upstreams": [
        {"name": "u", "base_url": "http://x/v1", "models": ["m1"]}]}))
    assert main(["bench", "run", "--models", "m1", "--out", str(tmp_path / "r"),
                 "--config", str(p), "--summarizer", "zzz"]) == 2


def test_variant_shape():
    s = load_scenario(FIX)
    v = stress_variant(s, 3, seed=0)
    at = s.constraint.introduced_at.turn
    assert len(v.turns) == len(s.turns) + 6 and v.compact_at == s.compact_at + 6
    assert v.id == "ex-hard-ops-stress3"
    assert v.turns[at - 1] == s.turns[at - 1]
    assert v.turns[at].role == "user" and v.turns[at + 1].role == "tool_script"


def test_variant_deterministic():
    s = load_scenario(FIX)
    assert stress_variant(s, 2, 1).model_dump() == stress_variant(s, 2, 1).model_dump()


def test_notes_avoid_keywords():
    d = yaml.safe_load(open(FIX, encoding="utf-8"))
    d["constraint"]["keywords"] = ["dark mode"]
    d["constraint"]["text"] = "Use dark mode."
    s = Scenario.model_validate(d)
    v = stress_variant(s, 8, seed=0)
    assert not any("dark mode" in t.content.casefold()
                   for t in v.turns if t.role == "user" and t not in s.turns)


def test_constraint_still_evictable(tmp_path):
    v = stress_variant(load_scenario(FIX), 3, 0)
    hist, ends = build_history(v, tmp_path)
    span = find_span(hist[: ends[v.compact_at]], 4)
    idx = ends[v.constraint.introduced_at.turn] - 1
    assert span[0] <= idx < span[1]


@respx.mock
async def test_run_batch_stress_args(config, tmp_path):
    respx.post(f"{UP}/chat/completions").mock(side_effect=Bench())
    rid = await run_batch(config, sc_dir(tmp_path), ["m1"], ["C1"], [0], tmp_path / "r",
                          stress=2, upstream=UpstreamClient(config.upstreams))
    store = Store(str(tmp_path / "r" / "keel.db"))
    (e,) = store.list_episodes(rid)
    assert e.scenario_id == "ex-hard-ops-stress2" and store.get_run(rid).args["stress"] == 2
    assert json.dumps(store.get_run(rid).args)


def test_httpx_available():
    assert httpx.__version__
