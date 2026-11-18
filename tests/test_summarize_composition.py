import pytest

from keel.config import KeelConfig
from keel.models import SUMMARY_PREFIX
from keel.strategies.base import (
    CompactionState,
    StrategyError,
    canonical_name,
    parse_strategy,
    run_strategies,
)
from keel.strategies.summarize import SUMMARIZER_INSTRUCTION, SUMMARIZER_SYSTEM, SummarizeStrategy
from tests.fakes import FakeLLM, make_ctx

MSGS = [
    {"role": "system", "content": "SYS"},
    {"role": "user", "content": "u1"},
    {"role": "assistant", "content": "a1"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "read_logs", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c", "content": "LOGS"},
    {"role": "user", "content": "u2"},
    {"role": "assistant", "content": "a2"},
]


def state():
    return CompactionState(messages=list(MSGS), span=(1, 5), evicted=MSGS[1:5])


def test_parse_canonical_order():
    assert canonical_name(parse_strategy("pin+summarize")) == "summarize+pin"
    assert canonical_name(parse_strategy("truncate+pin")) == "truncate+pin"
    assert parse_strategy("") == [] and parse_strategy("none") == []
    assert canonical_name([]) == "none"


@pytest.mark.parametrize("spec", ["none+pin", "foo", "pin+pin", "validate"])
def test_parse_errors(spec):
    with pytest.raises(StrategyError):
        parse_strategy(spec)


def test_validate_enabled_adds_validate():
    assert canonical_name(parse_strategy("summarize+pin", True)) == "summarize+validate+pin"
    assert canonical_name(parse_strategy("truncate", True)) == "truncate"


async def test_summarize_replaces_span():
    out = await SummarizeStrategy().apply(state(), make_ctx())
    assert len(out.messages) == 4
    assert out.messages[1]["content"].startswith(SUMMARY_PREFIX)
    assert out.messages[2:] == MSGS[5:]
    assert out.span == (1, 2) and out.llm_tokens == 120 and out.evicted == MSGS[1:5]


async def test_summarizer_uses_agent_model_and_sampling():
    llm = FakeLLM()
    await SummarizeStrategy().apply(state(), make_ctx(llm))
    (c,) = llm.calls
    assert (c["model"], c["temperature"], c["seed"]) == ("m1", 0.7, 3)
    prompt = c["messages"][1]["content"]
    assert "TOOL RESULT:" in prompt and "ASSISTANT called" in prompt


async def test_summarizer_named_model():
    cfg = KeelConfig()
    cfg.compaction.summarizer = "big"
    llm = FakeLLM()
    await SummarizeStrategy().apply(state(), make_ctx(llm, cfg))
    assert llm.calls[0]["model"] == "big"


async def test_summarize_strips_think():
    out = await SummarizeStrategy().apply(state(), make_ctx(FakeLLM("<think>x</think>\nS")))
    assert out.summary_text == "S"


def test_prompt_never_mentions_constraints():
    p = (SUMMARIZER_SYSTEM + SUMMARIZER_INSTRUCTION).casefold()
    assert not [w for w in ("constraint", "rule", "instruction", "policy", "never") if w in p]


async def test_run_strategies_sequence():
    a = await run_strategies(parse_strategy("summarize"), state(), make_ctx())
    b = await SummarizeStrategy().apply(state(), make_ctx())
    assert a.messages == b.messages
