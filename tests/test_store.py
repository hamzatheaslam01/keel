import sqlite3
import time

import pytest

from keel.models import CompactionRecord, Episode, Pin, RequestRecord, RunInfo
from keel.store import Store


@pytest.fixture
def store():
    return Store(":memory:")


def req(sid, status=200, cache="none"):
    return RequestRecord(
        session_id=sid, turn_idx=0, upstream_model="m", status=status, cache_status=cache,
        tokenizer="fallback", tokens_in_raw=10, tokens_in_sent=10, proxy_ms=1.0, upstream_ms=2.0,
    )


def comp(sid, prefix_len=5, **kw):
    return CompactionRecord(
        session_id=sid, turn_idx=0, strategy="summarize", prefix_len=prefix_len, prefix_hash="h",
        prefix_hashes=["a", "h"], tokens_before=100, tokens_after=20,
        evicted=[{"role": "user", "content": "x"}], compacted=[{"role": "system", "content": "s"}],
        **kw,
    )


def test_session_roundtrip_and_ignore(store):
    store.ensure_session("s1", {"a": 1})
    store.ensure_session("s1", {"a": 2})
    assert store.get_session("s1")["config"] == {"a": 1}
    assert store.get_session("nope") is None


def test_set_extracted(store):
    store.ensure_session("s1", {})
    store.set_extracted("s1", 7, "hh")
    s = store.get_session("s1")
    assert (s["extracted_upto"], s["extracted_hash"]) == (7, "hh")


def test_requests_and_turn_idx(store):
    store.ensure_session("s1", {})
    store.insert_request(req("s1", cache="hit"))
    store.insert_request(req("s1"))
    assert store.next_turn_idx("s1") == 2
    rows = store.list_requests("s1")
    assert len(rows) == 2 and rows[0]["cache_status"] == "hit"


def test_list_sessions_counts_newest_first(store):
    store.ensure_session("old", {})
    time.sleep(0.01)
    store.ensure_session("new", {})
    store.insert_request(req("new"))
    store.insert_compaction(comp("new"))
    rows = store.list_sessions()
    assert rows[0]["id"] == "new"
    assert (rows[0]["n_requests"], rows[0]["n_compactions"]) == (1, 1)


def test_compaction_roundtrip(store):
    rec = comp("s1")
    rec.id = store.insert_compaction(rec)
    (got,) = store.active_compactions("s1")
    assert got == rec and got.validator is None


def test_active_order_and_deactivate(store):
    a = store.insert_compaction(comp("s1", prefix_len=9))
    store.insert_compaction(comp("s1", prefix_len=5))
    assert [c.prefix_len for c in store.active_compactions("s1")] == [5, 9]
    first = store.active_compactions("s1")[0].id
    store.deactivate_compactions([first])
    assert [c.id for c in store.active_compactions("s1")] == [a]
    assert len(store.list_compactions("s1")) == 2
    store.deactivate_compactions([])


def test_add_pin_dedupes_active(store):
    p1 = store.add_pin(Pin(session_id="s1", text="never prod"))
    p2 = store.add_pin(Pin(session_id="s1", text="never prod"))
    assert p1.id == p2.id
    assert store.deactivate_pin("s1", p1.id) is True
    p3 = store.add_pin(Pin(session_id="s1", text="never prod"))
    assert p3.id != p1.id
    assert store.deactivate_pin("other", p3.id) is False
    assert len(store.list_pins("s1")) == 2 and len(store.list_pins("s1", active_only=True)) == 1


def test_run_roundtrip_and_ignore(store):
    run = RunInfo(id="r", started_at="t", git_sha="g", config={"a": 1}, model_hashes={"m": "x"},
                  seeds=[0, 1], args={"k": "v"})
    store.insert_run(run)
    store.insert_run(run.model_copy(update={"git_sha": "other"}))
    assert store.get_run("r") == run
    assert store.get_run("nope") is None


def test_episode_roundtrip_nullable(store):
    ep = Episode(run_id="r", scenario_id="s", kind="soft", model="m", condition="C1", seed=0,
                 session_id="x", violated=True, constraint_survived=None, summary_survived=False,
                 probe=[{"role": "assistant", "content": "hi"}])
    store.insert_episode(ep)
    (got,) = store.list_episodes("r")
    assert got == ep
    assert store.episode_exists("r", "s", "m", "C1", 0)
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_episode(ep)


def test_query_helper(store):
    store.ensure_session("s1", {})
    assert store.query("SELECT id FROM sessions WHERE id=?", ("s1",)) == [{"id": "s1"}]
