import json
import math

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from keel.tokens import TokenRegistry


@pytest.fixture
def tok_path(tmp_path):
    vocab = {"[UNK]": 0, "hello": 1, "world": 2, "a": 3, "b": 4}
    tok = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    p = tmp_path / "tokenizer.json"
    tok.save(str(p))
    return str(p)


def test_hf_count(tok_path):
    reg = TokenRegistry({"m": tok_path})
    assert reg.count_text("m", "hello world hello") == 3
    assert reg.method("m") == "hf"


def test_fallback_count():
    reg = TokenRegistry({})
    assert reg.count_text("x", "abcdefghi") == 3
    assert reg.count_text("x", "") == 0
    assert reg.method("x") == "fallback"


def test_missing_file_falls_back(tmp_path):
    reg = TokenRegistry({"m": str(tmp_path / "nope.json")})
    assert reg.method("m") == "fallback"


def test_count_messages_overhead():
    reg = TokenRegistry({})
    msgs = [{"role": "user", "content": "abcdefgh"}, {"role": "user", "content": "12345678"}]
    tc = reg.count_messages("x", msgs)
    assert tc.n == 12 and tc.method == "fallback"
    tools = [{"a": 1}]
    extra = math.ceil(len(json.dumps(tools, sort_keys=True)) / 4)
    assert reg.count_messages("x", msgs, tools).n == 12 + extra


def test_head_tail_hf(tok_path):
    reg = TokenRegistry({"m": tok_path})
    head, tail, removed = reg.head_tail("m", "a b a b a b a b", 2, 1)
    assert removed == 5
    assert head.split() == ["a", "b"]
    assert tail.split() == ["b"]


def test_head_tail_short_text_untouched():
    reg = TokenRegistry({})
    assert reg.head_tail("x", "0123456789", 200, 100) == ("0123456789", "", 0)


def test_head_tail_fallback():
    reg = TokenRegistry({})
    head, tail, removed = reg.head_tail("x", "x" * 100, 5, 5)
    assert len(head) == 20 and len(tail) == 20 and removed == 15


def test_count_cache_reuses_result(tok_path, monkeypatch):
    reg = TokenRegistry({"m": tok_path})
    assert reg.count_text("m", "hello world") == 2
    tok = reg._get("m")
    calls = []
    real = tok.encode
    monkeypatch.setattr(reg, "_get", lambda model: type("T", (), {
        "encode": lambda self, *a, **k: (calls.append(1), real(*a, **k))[1]})())
    assert reg.count_text("m", "hello world") == 2 and calls == []
    assert reg.count_text("m", "hello world hello") == 3 and calls == [1]


def test_count_cache_is_bounded(tok_path):
    reg = TokenRegistry({"m": tok_path}, max_cached_counts=3)
    for i in range(10):
        reg.count_text("m", "hello " * (i + 1))
    assert len(reg._counts) <= 3
    assert reg.count_text("m", "hello hello") == 2


def test_count_cache_is_per_model(tok_path, tmp_path):
    vocab = {"[UNK]": 0, "hello": 1}
    tok = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    p2 = tmp_path / "t2.json"
    tok.save(str(p2))
    reg = TokenRegistry({"a": tok_path, "b": str(p2)})
    assert reg.count_text("a", "hello world") == 2
    assert reg.count_text("b", "hello world") == 1


def test_warm_loads_tokenizers(tok_path):
    reg = TokenRegistry({"m": tok_path})
    reg.warm()
    assert reg._cache["m"] is not None
