from keel.extract import extract_constraints, parse_candidates
from tests.fakes import FakeLLM


def test_parse_basic():
    (c,) = parse_candidates('{"instructions": [{"text": "Never deploy to prod.", "confidence": 0.9}]}')
    assert c.text == "Never deploy to prod." and c.confidence == 0.9


def test_parse_clamps_and_defaults():
    cs = parse_candidates('{"instructions": [{"text": "a", "confidence": 1.7}, {"text": "b"},'
                          ' {"text": "c", "confidence": "high"}]}')
    assert [c.confidence for c in cs] == [1.0, 0.5, 0.5]


def test_parse_garbage():
    assert parse_candidates("no json here") == []
    assert parse_candidates('{"instructions": "x"}') == []


def test_parse_dedupes_and_strips_think():
    cs = parse_candidates('<think>{"x":1}</think>{"instructions": [{"text": "A "},'
                          ' {"text": "a"}]}')
    assert [c.text for c in cs] == ["A"]


async def test_only_user_and_tool_messages():
    llm = FakeLLM('{"instructions": []}')
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"}, {"role": "tool", "content": "t"}]
    await extract_constraints(msgs, llm, "judge", 8000)
    assert len(llm.calls) == 2 and "Message (tool)" in llm.calls[1]["messages"][1]["content"]


async def test_truncates_input():
    llm = FakeLLM('{"instructions": []}')
    await extract_constraints([{"role": "tool", "content": "x" * 20000}], llm, "judge", 100)
    prompt = llm.calls[0]["messages"][1]["content"]
    block = prompt.split("<message>\n")[1].split("\n</message>")[0]
    assert block == "x" * 100


async def test_fixed_sampling():
    llm = FakeLLM('{"instructions": []}')
    await extract_constraints([{"role": "user", "content": "u"}], llm, "judge", 100)
    c = llm.calls[0]
    assert (c["temperature"], c["seed"], c["model"]) == (0.0, 0, "judge")


async def test_returns_ms_and_tokens():
    llm = FakeLLM('{"instructions": [{"text": "x", "confidence": 1}]}')
    cands, ms, tokens = await extract_constraints(
        [{"role": "user", "content": "u"}, {"role": "user", "content": "v"}], llm, "j", 100)
    assert len(cands) == 2 and ms == 10.0 and tokens == 240
