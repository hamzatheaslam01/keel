"""keel serve / bench run / bench report."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="keel")
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the Keel proxy")
    serve.add_argument("--config", default="keel.yaml")

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
    report = bsub.add_parser("report", help="Write results.md and results.csv")
    report.add_argument("out_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError("T-10")


if __name__ == "__main__":
    raise SystemExit(main())
