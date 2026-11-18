import httpx
import pytest

from keel.app import create_app
from keel.config import KeelConfig, ServerConfig, UpstreamConfig
from keel.store import Store

UP = "http://upstream.test/v1"


def chat_json(content="ok", tool_calls=None, prompt_tokens=10, completion_tokens=2) -> dict:
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "id": "c1", "object": "chat.completion", "model": "m1",
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


@pytest.fixture
def config() -> KeelConfig:
    return KeelConfig(
        server=ServerConfig(db=":memory:"),
        upstreams=[UpstreamConfig(name="up", base_url=UP, models=["m1", "judge"])],
    )


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


@pytest.fixture
def make_client(store):
    def factory(cfg: KeelConfig) -> httpx.AsyncClient:
        app = create_app(cfg, store=store)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://keel")

    return factory
