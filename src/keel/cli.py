"""keel serve / bench run / bench report."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="keel")
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the Keel proxy")
    serve.add_argument("--config", default="keel.yaml")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    bench = sub.add_parser("bench", help="DecayBench-lite")
    bsub = bench.add_subparsers(dest="bench_command", required=True)
    run = bsub.add_parser("run", help="Run benchmark episodes")
    run.add_argument("--scenarios", default="scenarios")
    run.add_argument("--models", required=True)
    run.add_argument("--conditions", default="C0,C1,C2,C3,C4,C5,C6")
    run.add_argument("--seeds", type=int, default=3)
    run.add_argument("--out", required=True)
    run.add_argument("--config", default="keel.yaml")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--summarizer", default=None)
    run.add_argument("--stress", type=int, default=0)
    report = bsub.add_parser("report", help="Write results.md and results.csv")
    report.add_argument("out_dir")
    return p


def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _serve(args: argparse.Namespace) -> int:
    from keel.app import create_app
    from keel.config import ConfigError, load_config

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        return _err(str(e))
    host = args.host or cfg.server.host
    port = args.port or cfg.server.port
    uvicorn.run(create_app(cfg), host=host, port=port)
    return 0


def _bench_run(args: argparse.Namespace) -> int:
    from bench.runner import CONDITIONS, run_batch
    from keel.config import ConfigError, load_config
    from keel.upstream import UpstreamClient

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    bad = [c for c in conditions if c not in CONDITIONS]
    if bad:
        return _err(f"unknown condition(s): {', '.join(bad)}")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        return _err(str(e))
    if args.summarizer and args.summarizer not in UpstreamClient(cfg.upstreams).models():
        return _err(f"unknown summarizer model: {args.summarizer}")
    print(f"bench run: models={models} conditions={conditions} seeds={args.seeds} "
          f"summarizer={args.summarizer or 'same_as_agent'} stress={args.stress}", flush=True)
    from bench.runner import BenchAborted

    try:
        run_id = asyncio.run(run_batch(
            cfg, Path(args.scenarios), models, conditions, list(range(args.seeds)),
            Path(args.out), limit=args.limit, summarizer=args.summarizer, stress=args.stress,
        ))
    except BenchAborted as e:
        return _err(str(e))
    print(run_id)
    return 0


def _bench_report(args: argparse.Namespace) -> int:
    from bench.report import write_report

    out = Path(args.out_dir)
    if not (out / "keel.db").is_file():
        return _err(f"{out / 'keel.db'} not found")
    try:
        md, csv = write_report(out)
    except PermissionError as e:
        return _err(f"cannot write {e.filename}: close it if it is open (e.g. in Excel) and retry")
    print(md)
    print(csv)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.bench_command == "run":
        return _bench_run(args)
    return _bench_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
