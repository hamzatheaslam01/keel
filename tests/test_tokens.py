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
