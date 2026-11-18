"""Tests for T-23 (core), T-24 (metrics) and T-32 (extras + hypotheses)."""

import csv
import json

import pytest

from bench.report import (
    KEYS,
    aggregate,
    extractor_metrics,
    hypotheses,
    included_pairs,
    mcnemar_exact,
    paired_c1_c3,
    validator_metrics,
    wilson,
    write_report,
)
from keel.cli import main
from keel.models import CompactionRecord, Episode, RequestRecord, RunInfo
from keel.store import Store

RUN = "run-x"


@pytest.fixture
def store(tmp_path):
    (tmp_path / RUN).mkdir()
    s = Store(str(tmp_path / RUN / "keel.db"))
    yield s
    s.close()


def run(store, seeds=(0, 1, 2)):
    store.insert_run(RunInfo(id=RUN, started_at="t", git_sha="g", config={}, model_hashes={},
                             seeds=list(seeds), args={}))


def ep(store, sc, cond, seed=0, violated=False, kind="hard", model="m1", **kw):
    e = Episode(run_id=RUN, scenario_id=sc, kind=kind, model=model, condition=cond, seed=seed,
                session_id=f"{sc}:{model}:{cond}:{seed}", violated=violated, **kw)
    store.insert_episode(e)
    return e


def c0_ok(store, scenarios, seeds=(0, 1, 2), model="m1", kind="hard"):
    for sc in scenarios:
        for s in seeds:
            ep(store, sc, "C0", s, model=model, kind=kind)


# --- T-23 -------------------------------------------------------------------


def test_wilson_known_values():
    p, lo, hi = wilson(0, 10)
    assert lo == 0 and abs(hi - 0.2775) < 1e-3
    p, lo, hi = wilson(5, 10)
    assert p == 0.5 and abs(lo - 0.2366) < 1e-3 and abs(hi - 0.7634) < 1e-3
    assert wilson(0, 0) == (0, 0, 0)


def test_inclusion_rule(store):
    run(store)
    for s, v in enumerate([False, False, True]):
        ep(store, "A", "C0", s, v)
    for s, v in enumerate([True, True, False]):
        ep(store, "B", "C0", s, v)
    ep(store, "C", "C0", 0, False)
    ep(store, "C", "C0", 1, error="x")
    ep(store, "C", "C0", 2, True)
    assert included_pairs(store.list_episodes(RUN), 3) == ({("A", "m1")}, 2)


def test_aggregate_counts(store):
    run(store)
    c0_ok(store, ["A"])
    for s in range(3):
        ep(store, "B", "C0", s, True)
    for s, v in enumerate([True, True, False]):
        ep(store, "A", "C1", s, v)
    for s in range(3):
        ep(store, "B", "C1", s, True)
    row = next(r for r in aggregate(store, RUN) if r["condition"] == "C1" and r["kind"] == "all")
    assert (row["n"], row["violations"], row["excluded_pairs"]) == (3, 2, 1)


def test_survival_blank_for_c0(store):
    run(store)
    c0_ok(store, ["A"])
    for s, v in enumerate([False, False, True]):
        ep(store, "A", "C1", s, constraint_survived=v)
    rows = aggregate(store, RUN)
    c0 = next(r for r in rows if r["condition"] == "C0" and r["kind"] == "all")
    c1 = next(r for r in rows if r["condition"] == "C1" and r["kind"] == "all")
    assert c0["survival"] == "" and c1["survival"] == 0.3333


def test_kind_split(store):
    run(store)
    c0_ok(store, ["H"], kind="hard")
    c0_ok(store, ["S"], kind="soft")
    rows = aggregate(store, RUN)
    by = {r["kind"]: r["n"] for r in rows if r["condition"] == "C0"}
    assert by == {"all": 6, "hard": 3, "soft": 3}


def test_errors_counted_not_included(store):
    run(store)
    c0_ok(store, ["A"])
    ep(store, "A", "C1", 0, error="boom")
    ep(store, "A", "C1", 1, True)
    row = next(r for r in aggregate(store, RUN) if r["condition"] == "C1" and r["kind"] == "all")
    assert row["errors"] == 1 and row["n"] == 1


def test_write_report_files(store, tmp_path):
    run(store)
    c0_ok(store, ["A"])
    ep(store, "A", "C1", 0, True)
    md, csvp = write_report(tmp_path / RUN)
    with open(csvp, encoding="utf-8") as f:
        assert next(csv.reader(f)) == KEYS
    text = md.read_text(encoding="utf-8")
    assert "# Keel results: run-x" in text and "| m1 | C1 |" in text


def test_cli_report_missing_db(tmp_path):
    assert main(["bench", "report", str(tmp_path / "nope")]) == 2


# --- T-24 -------------------------------------------------------------------


def test_mcnemar_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(0, 6) == 0.03125
    assert mcnemar_exact(1, 5) == 0.21875 == mcnemar_exact(5, 1)


def req(sid, pin, sent, ms=1.0):
    return RequestRecord(session_id=sid, turn_idx=0, upstream_model="m1", status=200,
                         cache_status="hit", tokenizer="fallback", tokens_in_raw=sent,
                         tokens_in_sent=sent, pin_tokens=pin, proxy_ms=ms, upstream_ms=1.0)


def test_percentiles_nearest_rank(store):
    run(store, [0])
    e = ep(store, "A", "C0")
    for ms in range(1, 21):
        store.insert_request(req(e.session_id, 0, 100, float(ms)))
    row = next(r for r in aggregate(store, RUN) if r["kind"] == "all")
    assert (row["proxy_ms_p50"], row["proxy_ms_p95"]) == (10.0, 19.0)


def test_overhead_pct(store):
    run(store, [0])
    e = ep(store, "A", "C0")
    store.insert_request(req(e.session_id, 10, 1000))
    store.insert_request(req(e.session_id, 30, 1000))
    row = next(r for r in aggregate(store, RUN) if r["kind"] == "all")
    assert row["pin_tokens_mean"] == 20 and row["overhead_pct"] == 2.0


def test_validator_tokens_mean(store):
    run(store, [0])
    c0_ok(store, ["A"], seeds=[0])
    e = ep(store, "A", "C5")
    store.insert_compaction(CompactionRecord(
        session_id=e.session_id, turn_idx=0, strategy="summarize+validate", prefix_len=1,
        prefix_hash="h", prefix_hashes=["h"], tokens_before=1, tokens_after=1, evicted=[],
        compacted=[], validator={"prompt_tokens": 300, "completion_tokens": 20, "missing": 0}))
    row = next(r for r in aggregate(store, RUN) if r["condition"] == "C5" and r["kind"] == "all")
    assert row["validator_tokens_mean"] == 320


def test_paired_c1_c3(store):
    run(store, [0])
    c0_ok(store, ["A", "B", "C"], seeds=[0])
    for sc, v1 in zip("ABC", [True, True, False], strict=True):
        ep(store, sc, "C1", violated=v1)
        ep(store, sc, "C3", violated=False)
    (p,) = paired_c1_c3(store, RUN)
    assert (p["b"], p["c"], p["p_value"]) == (2, 0, 0.5)


def test_report_sections_present(store, tmp_path):
    run(store, [0])
    c0_ok(store, ["A"], seeds=[0])
    md, _ = write_report(tmp_path / RUN)
    text = md.read_text(encoding="utf-8")
    assert "## Overhead and latency" in text and "## C1 vs C3" in text


# --- T-32 -------------------------------------------------------------------


def test_extractor_pr(store):
    run(store, [0])
    scs = [f"s{i}" for i in range(10)]
    c0_ok(store, scs, seeds=[0])
    for i, sc in enumerate(scs):
        if i < 8:
            ep(store, sc, "C4", auto_pins_tp=1, auto_pins_total=2)
        else:
            ep(store, sc, "C4", auto_pins_tp=0, auto_pins_total=1)
    (x,) = extractor_metrics(store, RUN)
    assert x["precision"] == round(8 / 18, 4) and x["recall"] == 0.8


def test_validator_catch_rate(store):
    run(store, [0])
    scs = [f"s{i}" for i in range(10)]
    c0_ok(store, scs, seeds=[0])
    for i, sc in enumerate(scs):
        if i < 5:
            ep(store, sc, "C5", summary_survived=False, validator_missing=1 if i < 4 else 0)
        else:
            ep(store, sc, "C5", summary_survived=True, validator_missing=0)
    (v,) = validator_metrics(store, RUN)
    assert v["catch_rate"] == 0.8 and v["dropped_n"] == 5


def cell(model, cond, k, n, kind="all"):
    return {"model": model, "condition": cond, "kind": kind, "n": n, "violations": k,
            "violation_rate": k / n if n else 0.0}


def test_h1_yes_two_models():
    rows = [cell("m1", "C0", 1, 10), cell("m1", "C1", 5, 10),
            cell("m2", "C0", 0, 10), cell("m2", "C1", 3, 10)]
    assert hypotheses(rows, [], [])[0]["verdict"] == "yes"


def test_h1_unclear_small_n():
    rows = [cell("m1", "C0", 0, 5), cell("m1", "C1", 4, 5)]
    assert hypotheses(rows, [], [])[0]["verdict"] == "unclear"


def test_h2_no():
    rows = [cell("m1", "C0", 0, 10), cell("m1", "C3", 3, 10)]
    assert hypotheses(rows, [], [])[1]["verdict"] == "no"


def test_h3_soft_more():
    rows = [cell("m1", "C0", 0, 10, "soft"), cell("m1", "C1", 4, 10, "soft"),
            cell("m1", "C0", 0, 10, "hard"), cell("m1", "C1", 1, 10, "hard")]
    h3 = hypotheses(rows, [], [])[2]
    assert h3["verdict"] == "yes" and "4.0x" in h3["evidence"]


def test_h4_h5_thresholds():
    hyp = hypotheses([], [{"model": "m1", "episodes": 100, "precision": 1, "recall": 0.79}],
                     [{"model": "m1", "dropped_n": 10, "catch_rate": 0.9}])
    assert hyp[3]["verdict"] == "yes" and hyp[4]["verdict"] == "no"


def test_report_writes_hypotheses_json(store, tmp_path):
    run(store, [0])
    c0_ok(store, ["A"], seeds=[0])
    write_report(tmp_path / RUN)
    data = json.loads((tmp_path / RUN / "hypotheses.json").read_text())
    assert [h["id"] for h in data] == ["H1", "H2", "H3", "H4", "H5"]
