import copy

from keel.config import KeelConfig, TruncateConfig
from keel.strategies.base import CompactionState, canonical_name, parse_strategy
from keel.strategies.truncate import TruncateStrategy
from tests.fakes import make_ctx


def ctx():
    cfg = KeelConfig()
    cfg.compaction.truncate = TruncateConfig(head_tokens=5, tail_tokens=5, older_than_turns=2)
    return make_ctx(config=cfg, agent_model="m")


def msgs(n_after=2, content="x" * 400):
    m = [{"role": "system", "content": "S"}, {"role": "user", "content": "u"},
         {"role": "assistant", "content": "", "tool_calls": [
             {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
         {"role": "tool", "tool_call_id": "c1", "content": content}]
    for _ in range(n_after):
        m += [{"role": "assistant", "content": "a"}, {"role": "user", "content": "u"}]
    return m


async def run(m, span):
    return await TruncateStrategy().apply(CompactionState(m, span, m[span[0]:span[1]]), ctx())


async def test_old_tool_output_truncated():
    out = await run(msgs(), (1, 6))
    c = out.messages[3]["content"]
    assert c.startswith("x" * 20) and "[truncated 90 tokens]" in c and c.endswith("x" * 20)
    assert out.messages[3]["tool_call_id"] == "c1"


async def test_recent_tool_output_kept():
    m = msgs(n_after=1)
    out = await run(m, (1, 5))
    assert out.messages[3] == m[3]


async def test_user_and_assistant_untouched():
    m = msgs()
    m[1]["content"] = "y" * 1000
    out = await run(m, (1, 6))
    assert out.messages[1] == m[1]


async def test_outside_span_untouched():
    m = msgs(n_after=3)
    out = await run(m, (1, 3))
    assert out.messages[3] == m[3]


async def test_short_tool_output_untouched():
    m = msgs(content="z" * 30)
    out = await run(m, (1, 6))
    assert out.messages[3] == m[3]


async def test_span_and_count_unchanged():
    m = msgs()
    before = copy.deepcopy(m)
    out = await run(m, (1, 6))
    assert len(out.messages) == len(m) and out.span == (1, 6) and m == before


def test_composes_with_pin_via_parse():
    assert canonical_name(parse_strategy("pin+truncate")) == "truncate+pin"
