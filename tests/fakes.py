"""Shared test doubles."""

from keel.config import KeelConfig
from keel.strategies.base import LLMResult, StrategyContext
from keel.tokens import TokenRegistry


class FakeLLM:
    def __init__(self, text="Summary: user asked to fix payments.", texts=None):
        self.text, self.texts, self.calls = text, list(texts or []), []

    async def complete(self, model, messages, *, temperature, top_p=None, seed=None,
                       max_tokens=1024):
        self.calls.append(dict(model=model, messages=messages, temperature=temperature,
                               top_p=top_p, seed=seed, max_tokens=max_tokens))
        text = self.texts.pop(0) if self.texts else self.text
        return LLMResult(text=text, prompt_tokens=100, completion_tokens=20, ms=5.0)


def make_ctx(llm=None, config=None, pins=None, agent_model="m1", sampling=None):
    return StrategyContext(
        session_id="s", agent_model=agent_model,
        sampling={"temperature": 0.7, "seed": 3} if sampling is None else sampling,
        config=config or KeelConfig(), pins=pins or [], tokens=TokenRegistry({}),
        llm=llm or FakeLLM(),
    )
