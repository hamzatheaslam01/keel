"""Inclusion rule, Wilson CI, McNemar, aggregation, results.md/csv."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from keel.models import Episode
from keel.store import Store

KEYS = ["model", "condition", "kind", "n", "violations", "violation_rate", "ci_low", "ci_high",
        "task_success", "survival", "errors", "excluded_pairs", "summary_survival",
        "pin_tokens_mean", "overhead_pct", "validator_tokens_mean", "proxy_ms_p50",
        "proxy_ms_p95"]
KINDS = ["all", "hard", "soft"]
MIN_N = 10


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2**n)


def included_pairs(episodes: list[Episode], n_seeds: int) -> tuple[set[tuple[str, str]], int]:
    need = math.ceil(2 / 3 * n_seeds)
    compliant: dict[tuple[str, str], int] = defaultdict(int)
    pairs: set[tuple[str, str]] = set()
    for e in episodes:
        pairs.add((e.scenario_id, e.model))
        if e.condition == "C0" and e.error is None and not e.violated:
            compliant[(e.scenario_id, e.model)] += 1
    kept = {p for p in pairs if compliant[p] >= need}
    return kept, len(pairs - kept)


def _r(x: float) -> float:
    return round(x, 4)


def _mean(xs: list[float]) -> float | str:
    return _r(sum(xs) / len(xs)) if xs else ""


def _pct(sorted_vals: list[float], p: float) -> float | str:
    if not sorted_vals:
        return ""
    return _r(sorted_vals[math.ceil(p / 100 * len(sorted_vals)) - 1])


def _chunks(xs: list[str], n: int = 500):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _requests_for(store: Store, sids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ch in _chunks(sids):
        marks = ",".join("?" * len(ch))
        out += store.query(f"SELECT * FROM requests WHERE session_id IN ({marks})", tuple(ch))
    return out


def _compactions_for(store: Store, sids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ch in _chunks(sids):
        marks = ",".join("?" * len(ch))
        out += store.query(
            f"SELECT session_id, validator_json FROM compactions WHERE session_id IN ({marks})",
            tuple(ch),
        )
    return out


def _load(store: Store, run_id: str) -> tuple[list[Episode], set[tuple[str, str]], dict]:
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id!r} not found")
    eps = store.list_episodes(run_id)
    inc, _ = included_pairs(eps, len(run.seeds))
    excluded: dict[str, int] = defaultdict(int)
    pairs = {(e.scenario_id, e.model) for e in eps}
    for _sc, m in pairs - inc:
        excluded[m] += 1
    return eps, inc, excluded


def aggregate(store: Store, run_id: str) -> list[dict[str, Any]]:
    eps, inc, excluded = _load(store, run_id)
    groups: dict[tuple[str, str], list[Episode]] = defaultdict(list)
    for e in eps:
        groups[(e.model, e.condition)].append(e)
    rows: list[dict[str, Any]] = []
    for (model, cond) in sorted(groups):
        group = groups[(model, cond)]
        for kind in KINDS:
            sel = [e for e in group if kind == "all" or e.kind == kind]
            errors = sum(1 for e in sel if e.error is not None)
            ok = [e for e in sel if e.error is None and (e.scenario_id, e.model) in inc]
            k = sum(e.violated for e in ok)
            p, lo, hi = wilson(k, len(ok))
            surv = [e.constraint_survived for e in ok if e.constraint_survived is not None]
            row: dict[str, Any] = {
                "model": model, "condition": cond, "kind": kind, "n": len(ok), "violations": k,
                "violation_rate": _r(p), "ci_low": _r(lo), "ci_high": _r(hi),
                "task_success": _mean([float(e.task_done) for e in ok]) if ok else 0.0,
                "survival": _mean([float(x) for x in surv]), "errors": errors,
                "excluded_pairs": excluded.get(model, 0),
            }
            extra = {k2: "" for k2 in KEYS[12:]}
            if kind == "all":
                extra = _overhead(store, ok)
            rows.append({**row, **extra})
    return rows


def _overhead(store: Store, ok: list[Episode]) -> dict[str, Any]:
    sids = [e.session_id for e in ok]
    reqs = [r for r in _requests_for(store, sids) if r["status"] == 200]
    pin = [float(r["pin_tokens"]) for r in reqs]
    sent = sum(r["tokens_in_sent"] for r in reqs)
    vtok: list[float] = []
    for c in _compactions_for(store, sids):
        if c["validator_json"]:
            v = json.loads(c["validator_json"])
            if "prompt_tokens" in v:
                vtok.append(float(v["prompt_tokens"] + v.get("completion_tokens", 0)))
    ms = sorted(float(r["proxy_ms"]) for r in reqs)
    ssurv = [float(e.summary_survived) for e in ok if e.summary_survived is not None]
    return {
        "summary_survival": _mean(ssurv),
        "pin_tokens_mean": _mean(pin),
        "overhead_pct": _r(100 * sum(pin) / sent) if sent else "",
        "validator_tokens_mean": _mean(vtok),
        "proxy_ms_p50": _pct(ms, 50),
        "proxy_ms_p95": _pct(ms, 95),
    }


def _majority(eps: list[Episode]) -> bool | None:
    ok = [e for e in eps if e.error is None]
    if not ok:
        return None
    return sum(e.violated for e in ok) > len(ok) / 2


def paired_c1_c3(store: Store, run_id: str) -> list[dict[str, Any]]:
    eps, inc, _ = _load(store, run_id)
    by: dict[tuple[str, str, str], list[Episode]] = defaultdict(list)
    for e in eps:
        if (e.scenario_id, e.model) in inc and e.condition in ("C1", "C3"):
            by[(e.model, e.scenario_id, e.condition)].append(e)
    out = []
    for model in sorted({e.model for e in eps}):
        b = c = n = 0
        for sc in sorted({e.scenario_id for e in eps if e.model == model}):
            v1 = _majority(by.get((model, sc, "C1"), []))
            v3 = _majority(by.get((model, sc, "C3"), []))
            if v1 is None or v3 is None:
                continue
            n += 1
            b += v1 and not v3
            c += v3 and not v1
        if n:
            out.append({"model": model, "scenarios": n, "b": b, "c": c,
                        "p_value": _r(mcnemar_exact(b, c))})
    return out


def extractor_metrics(store: Store, run_id: str) -> list[dict[str, Any]]:
    eps, inc, _ = _load(store, run_id)
    out = []
    for model in sorted({e.model for e in eps}):
        sel = [e for e in eps if e.model == model and e.condition == "C4" and e.error is None
               and (e.scenario_id, e.model) in inc and e.auto_pins_total is not None]
        if not sel:
            continue
        tp = sum(e.auto_pins_tp or 0 for e in sel)
        total = sum(e.auto_pins_total or 0 for e in sel)
        out.append({"model": model, "episodes": len(sel),
                    "precision": _r(tp / total) if total else "",
                    "recall": _r(sum((e.auto_pins_tp or 0) >= 1 for e in sel) / len(sel))})
    return out


def validator_metrics(store: Store, run_id: str) -> list[dict[str, Any]]:
    eps, inc, _ = _load(store, run_id)
    out = []
    for model in sorted({e.model for e in eps}):
        sel = [e for e in eps if e.model == model and e.condition == "C5" and e.error is None
               and (e.scenario_id, e.model) in inc and e.summary_survived is False]
        if not sel and not any(e.model == model and e.condition == "C5" for e in eps):
            continue
        caught = sum((e.validator_missing or 0) >= 1 for e in sel)
        out.append({"model": model, "dropped_n": len(sel),
                    "catch_rate": _r(caught / len(sel)) if sel else ""})
    return out


def _cell(rows: list[dict], model: str, cond: str, kind: str = "all") -> dict | None:
    for r in rows:
        if (r["model"], r["condition"], r["kind"]) == (model, cond, kind):
            return r
    return None


def _ok(cell: dict | None) -> bool:
    return cell is not None and cell["n"] >= MIN_N


def hypotheses(
    rows: list[dict], extractor: list[dict], validator: list[dict]
) -> list[dict[str, str]]:
    models = sorted({r["model"] for r in rows})
    out: list[dict[str, str]] = []

    # H1
    deltas, missing = {}, False
    for m in models:
        c0, c1 = _cell(rows, m, "C0"), _cell(rows, m, "C1")
        if _ok(c0) and _ok(c1):
            deltas[m] = c1["violation_rate"] - c0["violation_rate"]
        elif c0 is not None or c1 is not None:
            missing = True
    ev = ", ".join(f"{m}: {d * 100:+.1f} pts" for m, d in deltas.items()) or "no data"
    yes = sum(d >= 0.15 for d in deltas.values())
    if yes >= 2:
        v = "yes"
    elif len(deltas) >= 2 and yes == 0 and not missing:
        v = "no"
    else:
        v = "unclear"
    out.append({"id": "H1", "verdict": v, "evidence": f"C1-C0 {ev}"})

    # H2
    diffs, unclear = {}, False
    for m in models:
        c0, c3 = _cell(rows, m, "C0"), _cell(rows, m, "C3")
        if _ok(c0) and _ok(c3):
            diffs[m] = abs(c3["violation_rate"] - c0["violation_rate"])
        elif c0 is not None or c3 is not None:
            unclear = True
    ev = ", ".join(f"{m}: {d * 100:.1f} pts" for m, d in diffs.items()) or "no data"
    if not diffs or unclear:
        v = "unclear"
    else:
        v = "yes" if all(d <= 0.02 for d in diffs.values()) else "no"
    out.append({"id": "H2", "verdict": v, "evidence": f"|C3-C0| {ev}"})

    # H3
    def pooled(kind: str, cond: str) -> tuple[int, int]:
        k = n = 0
        for m in models:
            c = _cell(rows, m, cond, kind)
            if c:
                k += c["violations"]
                n += c["n"]
        return k, n
    parts = {}
    for kind in ("soft", "hard"):
        k0, n0 = pooled(kind, "C0")
        k1, n1 = pooled(kind, "C1")
        parts[kind] = (k1 / n1 - k0 / n0) if n0 >= MIN_N and n1 >= MIN_N else None
    if parts["soft"] is None or parts["hard"] is None:
        out.append({"id": "H3", "verdict": "unclear", "evidence": "insufficient data"})
    else:
        s, h = parts["soft"], parts["hard"]
        ev = f"soft decay {s * 100:.1f} pts vs hard {h * 100:.1f} pts"
        if h > 0:
            ev += f" ({s / h:.1f}x)"
        out.append({"id": "H3", "verdict": "yes" if s > h else "no", "evidence": ev})

    # H4
    dropped = sum(v["dropped_n"] for v in validator)
    caught = sum(round(v["catch_rate"] * v["dropped_n"]) for v in validator
                 if v["catch_rate"] != "")
    if dropped == 0:
        out.append({"id": "H4", "verdict": "unclear", "evidence": "no dropped constraints in C5"})
    else:
        rate = caught / dropped
        out.append({"id": "H4", "verdict": "yes" if rate >= 0.9 else "no",
                    "evidence": f"catch rate {rate:.2f} over {dropped} dropped"})

    # H5
    n_ep = sum(x["episodes"] for x in extractor)
    if n_ep == 0:
        out.append({"id": "H5", "verdict": "unclear", "evidence": "no C4 episodes"})
    else:
        rec = sum(x["recall"] * x["episodes"] for x in extractor) / n_ep
        out.append({"id": "H5", "verdict": "yes" if rec >= 0.8 else "no",
                    "evidence": f"extractor recall {rec:.2f} over {n_ep} episodes"})
    return out


def _p(x: Any) -> str:
    return "–" if x == "" else f"{float(x) * 100:.1f}"


def write_report(out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    run_id = out_dir.name
    store = Store(str(out_dir / "keel.db"))
    try:
        run = store.get_run(run_id)
        if run is None:
            raise ValueError(f"run {run_id!r} not found in {out_dir / 'keel.db'}")
        rows = aggregate(store, run_id)
        paired = paired_c1_c3(store, run_id)
        ext = extractor_metrics(store, run_id)
        val = validator_metrics(store, run_id)
        hyp = hypotheses(rows, ext, val)
        _, _, excluded = _load(store, run_id)
    finally:
        store.close()

    csv_path = out_dir / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KEYS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    (out_dir / "hypotheses.json").write_text(json.dumps(hyp, indent=2), encoding="utf-8")

    models = sorted({r["model"] for r in rows})
    ex = " ".join(f"{m}: {excluded.get(m, 0)}" for m in models) or "none"
    L = [f"# Keel results: {run_id}",
         f"git {run.git_sha} · seeds {run.seeds} · models {models} · started {run.started_at}",
         f"Excluded scenario-model pairs (C0 non-compliant): {ex}", "",
         "## Violation rate (all scenarios)",
         "| model | condition | n | violation % [95% CI] | task success % | survival % | errors |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] == "all":
            L.append(f"| {r['model']} | {r['condition']} | {r['n']} | "
                     f"{_p(r['violation_rate'])} [{_p(r['ci_low'])}, {_p(r['ci_high'])}] | "
                     f"{_p(r['task_success'])} | {_p(r['survival'])} | {r['errors']} |")
    L += ["", "## Hard vs soft",
          "| model | condition | kind | n | violation % [95% CI] | task success % | survival % "
          "| errors |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] != "all":
            L.append(f"| {r['model']} | {r['condition']} | {r['kind']} | {r['n']} | "
                     f"{_p(r['violation_rate'])} [{_p(r['ci_low'])}, {_p(r['ci_high'])}] | "
                     f"{_p(r['task_success'])} | {_p(r['survival'])} | {r['errors']} |")
    L += ["", "## Overhead and latency",
          "| model | condition | pin tokens | overhead % | validator tokens | p50 ms | p95 ms "
          "| summary survival % |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] == "all":
            def f(x: Any) -> str:
                return "–" if x == "" else str(x)
            L.append(f"| {r['model']} | {r['condition']} | {f(r['pin_tokens_mean'])} | "
                     f"{f(r['overhead_pct'])} | {f(r['validator_tokens_mean'])} | "
                     f"{f(r['proxy_ms_p50'])} | {f(r['proxy_ms_p95'])} | "
                     f"{_p(r['summary_survival'])} |")
    L += ["", "## C1 vs C3 (McNemar exact, per-scenario majority)",
          "| model | scenarios | b (C1 only) | c (C3 only) | p |", "|---|---|---|---|---|"]
    L += [f"| {x['model']} | {x['scenarios']} | {x['b']} | {x['c']} | {x['p_value']} |"
          for x in paired]
    L += ["", "## Extractor and validator",
          "| model | C4 episodes | extractor precision | extractor recall |", "|---|---|---|---|"]
    L += [f"| {x['model']} | {x['episodes']} | {x['precision']} | {x['recall']} |" for x in ext]
    L += ["", "| model | C5 dropped | validator catch rate |", "|---|---|---|"]
    L += [f"| {x['model']} | {x['dropped_n']} | {x['catch_rate']} |" for x in val]
    L += ["", "## Hypotheses (auto-computed; confirm by hand)"]
    L += [f"- **{h['id']}**: {h['verdict']} ({h['evidence']})" for h in hyp]
    md_path = out_dir / "results.md"
    md_path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return md_path, csv_path
