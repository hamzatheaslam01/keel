"""Benchmark runner: conditions, history builder, episode and batch driver."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from bench.graders import (
    constraint_survived,
    grade,
    keyword_hits,
    keywords_present,
    probe_trace,
)
from bench.mock_tools import ToolSpec, load_tools, mock_output, stress_variant, tool_definitions
from bench.schema import AssistantTurn, Scenario, UserTurn, load_scenarios, resolve_output
from keel.config import KeelConfig
from keel.models import Episode, Message, RunInfo
from keel.store import Store, utcnow
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
    msgs: list[Message] = [{"role": "system", "content": s.system_prompt}]
    ends: dict[int, int] = {}
    for i, t in enumerate(s.turns, start=1):
        if isinstance(t, UserTurn):
            msgs.append({"role": "user", "content": t.content})
        elif isinstance(t, AssistantTurn):
            msgs.append({"role": "assistant", "content": t.content})
        else:
            cid = f"call_{i}"
            msgs.append({"role": "assistant", "content": "", "tool_calls": [{
                "id": cid, "type": "function",
                "function": {"name": t.tool, "arguments": json.dumps(t.args, sort_keys=True)},
            }]})
            msgs.append({"role": "tool", "tool_call_id": cid, "content": resolve_output(t, root)})
        ends[i] = len(msgs)
    return msgs, ends


def condition_config(
    base: KeelConfig, cond: Condition, summarizer: str | None = None
) -> KeelConfig:
    cfg = base.model_copy(deep=True)
    cfg.compaction.strategy = cond.strategy
    cfg.compaction.trigger_tokens = BENCH_TRIGGER
    cfg.pins.auto_extract = cond.pins == "auto"
    cfg.validate_.enabled = False
    if summarizer:
        cfg.compaction.summarizer = summarizer
    return cfg


def session_id_for(run_id: str, scenario_id: str, model: str, cond: str, seed: int) -> str:
    return f"{run_id}:{scenario_id}:{model}:{cond}:s{seed}"


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
    sid = session_id_for(run_id, s.id, model, cond.id, seed)
    base_ep = dict(run_id=run_id, scenario_id=s.id, kind=s.kind, model=model,
                   condition=cond.id, seed=seed, session_id=sid)
    kw = s.constraint.keywords
    probe_msgs: list[Message] = []
    try:
        if cond.pins == "oracle":
            r = await client.post(f"/v1/sessions/{sid}/pins", json={
                "text": s.constraint.text, "source_turn": s.constraint.introduced_at.turn})
            if r.status_code != 201:
                raise ValueError(f"pin request {r.status_code}: {r.text[:300]}")
        history, ends = build_history(s, root)
        base = {"model": model, "tools": tool_definitions(s.tools, tools), **SAMPLING,
                "seed": seed}
        headers = {"X-Keel-Session": sid}
        r = await client.post(
            "/v1/chat/completions",
            json={**base, "messages": history[: ends[s.compact_at]], "max_tokens": 1},
            headers={**headers, "X-Keel-Force-Compact": "true"},
        )
        if r.status_code != 200:
            raise ValueError(f"compact request {r.status_code}: {r.text[:300]}")

        raw = history + [{"role": "user", "content": s.probe.content}]
        msgs = list(raw)
        for _ in range(MAX_PROBE_STEPS):
            r = await client.post("/v1/chat/completions", json={**base, "messages": msgs},
                                  headers=headers)
            if r.status_code != 200:
                raise ValueError(f"probe request {r.status_code}: {r.text[:300]}")
            m = r.json()["choices"][0]["message"]
            am: Message = {"role": m.get("role") or "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                am["tool_calls"] = m["tool_calls"]
            msgs.append(am)
            probe_msgs.append(am)
            calls = am.get("tool_calls") or []
            if not calls:
                break
            for call in calls:
                name = (call.get("function") or {}).get("name", "")
                tm = {"role": "tool", "tool_call_id": call.get("id", ""),
                      "content": mock_output(name, s, tools)}
                msgs.append(tm)
                probe_msgs.append(tm)

        violated, task_done = grade(s, probe_trace(probe_msgs))
        ep = Episode(**base_ep, violated=violated, task_done=task_done, probe=probe_msgs)
        active = [c for c in store.list_compactions(sid) if c.active]
        if active:
            rec = active[-1]
            ep.constraint_survived = constraint_survived(kw, rec.compacted + raw[rec.prefix_len:])
            if rec.summary_text is not None:
                ep.summary_survived = keywords_present(kw, rec.summary_text)
            if rec.validator:
                ep.validator_missing = rec.validator.get("missing")
        if cond.pins == "auto":
            auto = [p for p in store.list_pins(sid) if p.source == "auto" and p.active]
            need = math.ceil(len(kw) / 2)
            ep.auto_pins_total = len(auto)
            ep.auto_pins_tp = sum(keyword_hits(kw, p.text) >= need for p in auto)
        return ep
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        return Episode(**base_ep, probe=probe_msgs, error=f"{type(e).__name__}: {e}"[:500])


def git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                               timeout=10).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _redacted_config(config: KeelConfig) -> dict[str, Any]:
    d = config.model_dump(by_alias=True)
    for up in d.get("upstreams", []):
        if up.get("api_key"):
            up["api_key"] = "***"
    return d


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
    from keel.app import create_app
    from keel.strategies.summarize import SUMMARIZER_PROMPT_HASH

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    store = Store(str(out / "keel.db"))
    run_id = out.name
    scenarios = load_scenarios(scenarios_dir)
    if limit is not None:
        scenarios = scenarios[:limit]
    if stress > 0:
        scenarios = [stress_variant(s, stress, seed=0) for s in scenarios]
    tools = load_tools(Path(scenarios_dir) / "tools.yaml")

    model_hashes = {}
    for m in models:
        f = config.model_files.get(m)
        model_hashes[m] = file_sha256(f) if f and Path(f).is_file() else "unknown"
    store.insert_run(RunInfo(
        id=run_id, started_at=utcnow(), git_sha=git_sha(), config=_redacted_config(config),
        model_hashes=model_hashes, seeds=list(seeds),
        args={"scenarios_dir": str(scenarios_dir), "models": models, "conditions": conditions,
              "seeds": list(seeds), "limit": limit, "summarizer": summarizer, "stress": stress,
              "summarizer_prompt_hash": SUMMARIZER_PROMPT_HASH,
              "judge_model": config.validate_.judge_model,
              "extractor_model": config.pins.extractor_model, "sampling": SAMPLING,
              "max_probe_steps": MAX_PROBE_STEPS},
    ))
    upstream = upstream or UpstreamClient(config.upstreams)
    for c in conditions:
        cond = CONDITIONS[c]
        app = create_app(condition_config(config, cond, summarizer), store=store,
                         upstream=upstream)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://keel", timeout=None) as client:
            for model in models:
                for s in scenarios:
                    for seed in seeds:
                        if store.episode_exists(run_id, s.id, model, c, seed):
                            continue
                        t0 = time.perf_counter()
                        ep = await run_episode(client, store, s, Path(scenarios_dir), model, cond,
                                               seed, run_id, tools)
                        store.insert_episode(ep)
                        print(f"{c} {model} {s.id} s{seed} violated={ep.violated} "
                              f"err={bool(ep.error)} {time.perf_counter() - t0:.1f}s", flush=True)
    store.close()
    return run_id
