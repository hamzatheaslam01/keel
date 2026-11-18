import sqlite3

import pytest

from keel.config import load_config
from keel.store import Store, utcnow
from keel.strategies.base import CompactionState

TABLES = {"sessions", "requests", "compactions", "pins", "runs", "episodes"}


def test_ddl_creates_tables():
    store = Store(":memory:")
    rows = store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert TABLES <= {r["name"] for r in rows}


def test_init_idempotent(tmp_path):
    path = str(tmp_path / "k.db")
    Store(path).close()
    Store(path).close()


def test_episode_unique(tmp_path):
    store = Store(str(tmp_path / "k.db"))
    c = store._conn
    c.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)", ("r1", utcnow(), "sha", "{}", "{}", "[]", "{}")
    )
    sql = (
        "INSERT INTO episodes (run_id, scenario_id, kind, model, condition, seed, violated,"
        " task_done, session_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
    )
    row = ("r1", "s1", "hard", "m", "C0", 0, 0, 0, "sid", utcnow())
    c.execute(sql, row)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(sql, row)


def test_pin_source_check():
    store = Store(":memory:")
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO pins (session_id, text, source, created_at) VALUES (?,?,?,?)",
            ("s", "t", "oracle", utcnow()),
        )


def test_compaction_state_defaults():
    st = CompactionState(messages=[], span=(0, 0), evicted=[])
    assert st.pins_to_inject is False
    assert st.llm_tokens == 0


def test_example_config_loads(monkeypatch):
    monkeypatch.delenv("HOSTED_BASE_URL", raising=False)
    cfg = load_config("keel.example.yaml")
    assert len(cfg.upstreams) == 1
    assert cfg.tokenizers["qwen3-1.7b"].endswith("tokenizer.json")
