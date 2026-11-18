from keel.models import CompactionRecord
from keel.session import (
    CacheResult,
    apply_cache,
    find_span,
    first_changed_index,
    message_hashes,
    raw_prefix_len,
)


def u(t): return {"role": "user", "content": t}
def a(t): return {"role": "assistant", "content": t}
def sys(t="SYS"): return {"role": "system", "content": t}
def call(i, n="f"): return {"role": "assistant", "content": "", "tool_calls": [
    {"id": i, "type": "function", "function": {"name": n, "arguments": "{}"}}]}
def tool(i, t="r"): return {"role": "tool", "tool_call_id": i, "content": t}


def hist(n):
    return [sys()] + [(u if k % 2 == 0 else a)(f"m{k}") for k in range(n)]


def rec(raw, prefix_len, compacted):
    h = message_hashes(raw)
    return CompactionRecord(
        session_id="s", turn_idx=0, strategy="summarize", prefix_len=prefix_len,
        prefix_hash=h[prefix_len - 1], prefix_hashes=h[:prefix_len], tokens_before=0,
        tokens_after=0, evicted=[], compacted=compacted,
    )


def test_hash_stable_and_chained():
    x = hist(5)
    assert message_hashes(x) == message_hashes([dict(m) for m in x])
    y = [dict(m) for m in x]
    y[2]["content"] = "changed"
    hx, hy = message_hashes(x), message_hashes(y)
    assert hx[:2] == hy[:2] and all(p != q for p, q in zip(hx[2:], hy[2:], strict=True))
    assert message_hashes([{"content": "c", "role": "user"}]) == message_hashes([u("c")])
    assert message_hashes([{**u("c"), "reasoning_content": "z"}]) == message_hashes([u("c")])


def test_first_changed_index():
    assert first_changed_index(["a", "b", "c"], ["a", "x"]) == 1
    assert first_changed_index(["a", "b"], ["a", "b"]) == 2


def test_find_span_basic():
    assert find_span([sys(), u(1), a(1), u(2), a(2), u(3), a(3)], 4) == (1, 3)


def test_find_span_no_system():
    assert find_span([u(1), a(1), u(2), a(2), u(3), a(3)], 2) == (0, 4)


def test_find_span_keeps_tool_group():
    m = [sys(), u(1), call("c1"), tool("c1"), tool("c1", "r2"), a(1), u(2)]
    assert find_span(m, 3) == (1, 2)


def test_find_span_none_when_too_short():
    assert find_span([sys(), u(1), a(1)], 4) is None
    assert find_span(hist(7), 4, min_end=5) is None


def test_apply_cache_none():
    raw = hist(3)
    c = apply_cache(raw, message_hashes(raw), [])
    assert c.status == "none" and c.working == raw


def test_apply_cache_hit():
    raw = hist(9)
    summary = u("SUMMARY")
    r = rec(raw, 6, [sys(), summary])
    nxt = hist(11)
    c = apply_cache(nxt, message_hashes(nxt), [r])
    assert c.status == "hit" and c.working == [sys(), summary] + nxt[6:12]


def test_apply_cache_mismatch_falls_back():
    raw = hist(9)
    r4, r8 = rec(raw, 4, [sys(), u("S4")]), rec(raw, 8, [sys(), u("S8")])
    edited = [dict(m) for m in raw]
    edited[6]["content"] = "edit"
    c = apply_cache(edited, message_hashes(edited), [r4, r8])
    assert c.status == "mismatch" and c.record is r4 and c.stale == [r8]
    assert c.first_changed == 6


def test_apply_cache_mismatch_no_match():
    raw = hist(9)
    recs = [rec(raw, 4, [sys()]), rec(raw, 8, [sys()])]
    edited = [dict(m) for m in raw]
    edited[1]["content"] = "edit"
    c = apply_cache(edited, message_hashes(edited), recs)
    assert c.record is None and c.working == edited and len(c.stale) == 2


def test_apply_cache_shorter_raw_is_mismatch():
    raw = hist(9)
    short = raw[:5]
    c = apply_cache(short, message_hashes(short), [rec(raw, 8, [sys()])])
    assert c.status == "mismatch"


def test_raw_prefix_len_chained():
    r = rec(hist(9), 6, [sys(), u("S")])
    assert raw_prefix_len(CacheResult([], r, "hit", [], None), 5) == 9
    assert raw_prefix_len(CacheResult([], None, "none", [], None), 5) == 5
