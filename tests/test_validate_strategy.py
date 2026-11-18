from keel.models import SUMMARY_PREFIX, Pin
from keel.strategies.base import CompactionState
from keel.strategies.validate import ValidateStrategy
from tests.fakes import FakeLLM, make_ctx

PINS = [Pin(id=1, session_id="s", text="Never deploy to prod."),
        Pin(id=2, session_id="s", text="Tag tickets billing-team.")]


def state(summary="S"):
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "user", "content": f"{SUMMARY_PREFIX}\nS"}, {"role": "user", "content": "u"}]
    return CompactionState(msgs, (1, 2), [], summary_text=summary)


async def run(text, pins=PINS, st=None, agent="m1"):
    llm = FakeLLM(text)
    out = await ValidateStrategy().apply(st or state(), make_ctx(llm, pins=pins, agent_model=agent))
    return out, llm


async def test_all_covered_no_repair():
    out, _ = await run('{"covered": [true, true]}')
    assert out.messages == state().messages
    assert out.validator["missing"] == 0 and out.validator["parse_error"] is False


async def test_missing_pin_repaired():
    out, _ = await run('{"covered": [true, false]}')
    assert out.messages[1]["content"].endswith(
        "Standing instructions (verbatim):\n- Tag tickets billing-team.")
    assert out.validator["missing"] == 1 and out.summary_text == "S"


async def test_parse_error_repairs_all():
    out, _ = await run("I think yes")
    assert out.validator["parse_error"] and out.validator["missing"] == 2


async def test_wrong_length_is_parse_error():
    out, _ = await run('{"covered": [true]}')
    assert out.validator["parse_error"]


async def test_think_block_ignored():
    out, _ = await run('<think>{bad}</think>{"covered": [true, true]}')
    assert out.validator["parse_error"] is False


async def test_no_pins_skips_call():
    out, llm = await run("x", pins=[])
    assert llm.calls == [] and out.validator["skipped"] == "no_pins"


async def test_no_summary_skips():
    out, llm = await run("x", st=state(summary=None))
    assert llm.calls == [] and out.validator["skipped"] == "no_summary"


async def test_judge_model_and_determinism():
    _, llm = await run('{"covered": [true, true]}', agent="other")
    (c,) = llm.calls
    assert (c["model"], c["temperature"], c["seed"]) == ("qwen3-1.7b", 0.0, 0)


async def test_tokens_accumulate():
    out, _ = await run('{"covered": [true, true]}')
    assert out.llm_tokens == 120
