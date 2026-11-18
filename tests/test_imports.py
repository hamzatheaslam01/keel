import importlib

MODULES = [
    "keel.tokens", "keel.upstream", "keel.session", "keel.pipeline", "keel.app",
    "keel.extract", "keel.cli", "keel.strategies.truncate", "keel.strategies.summarize",
    "keel.strategies.validate", "keel.strategies.pin", "bench.mock_tools", "bench.runner",
    "bench.report", "bench.validate", "bench.toy_loop",
]


def test_all_modules_import():
    for m in MODULES:
        importlib.import_module(m)


def test_conditions_table():
    from bench.runner import CONDITIONS

    assert CONDITIONS["C5"].strategy == "summarize+validate"
    assert CONDITIONS["C4"].pins == "auto"


def test_strategy_class_attrs():
    from keel.strategies.pin import PinStrategy
    from keel.strategies.summarize import SummarizeStrategy
    from keel.strategies.truncate import TruncateStrategy
    from keel.strategies.validate import ValidateStrategy

    got = [(c.name, c.order) for c in
           (TruncateStrategy, SummarizeStrategy, ValidateStrategy, PinStrategy)]
    assert got == [("truncate", 10), ("summarize", 20), ("validate", 30), ("pin", 40)]
