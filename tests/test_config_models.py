import pytest

from keel.config import ConfigError, KeelConfig, load_config
from keel.models import Episode, Pin, text_of

YAML = """\
server: {host: 127.0.0.1, port: 8400, db: keel.db}
upstreams:
  - name: local
    base_url: http://127.0.0.1:8080/v1
    models: [qwen3-1.7b, qwen3-4b]
  - name: hosted
    base_url: ${HOSTED_BASE_URL}
    api_key: ${HOSTED_API_KEY}
    models: [hosted-small]
compaction:
  strategy: summarize+pin
  trigger_tokens: 6000
  keep_last_n: 4
  truncate: {older_than_turns: 3, head_tokens: 200, tail_tokens: 100}
  summarizer: same_as_agent
pins: {auto_extract: false, extractor_model: qwen3-1.7b, min_confidence: 0.6}
validate: {enabled: false, judge_model: qwen3-1.7b}
"""


def _write(tmp_path, text):
    p = tmp_path / "keel.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_config_full(tmp_path, monkeypatch):
    monkeypatch.setenv("HOSTED_BASE_URL", "https://h.example/v1")
    monkeypatch.setenv("HOSTED_API_KEY", "k1")
    cfg = load_config(_write(tmp_path, YAML))
    assert len(cfg.upstreams) == 2
    assert cfg.upstreams[1].api_key == "k1"
    assert cfg.compaction.truncate.head_tokens == 200
    assert cfg.validate_.judge_model == "qwen3-1.7b"
    assert cfg.server.port == 8400


def test_unset_env_drops_upstream(tmp_path, monkeypatch):
    monkeypatch.delenv("HOSTED_BASE_URL", raising=False)
    cfg = load_config(_write(tmp_path, YAML))
    assert [u.name for u in cfg.upstreams] == ["local"]


def test_defaults():
    cfg = KeelConfig()
    assert cfg.compaction.strategy == "none"
    assert cfg.compaction.keep_last_n == 4
    assert cfg.pins.min_confidence == 0.6
    assert cfg.tokenizers == {}


def test_bad_yaml_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "server: [unclosed"))


def test_extra_body_parsed(tmp_path):
    text = (
        "upstreams:\n"
        "  - name: local\n"
        "    base_url: http://x/v1\n"
        "    models: [m]\n"
        "    extra_body: {chat_template_kwargs: {enable_thinking: false}}\n"
    )
    cfg = load_config(_write(tmp_path, text))
    assert cfg.upstreams[0].extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_text_of_string_list_and_tool_calls():
    assert text_of({"role": "user", "content": "hi"}) == "hi"
    parts = [{"type": "text", "text": "a"}, {"type": "image_url"}, {"type": "text", "text": "b"}]
    assert text_of({"role": "user", "content": parts}) == "a\nb"
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"function": {"name": "deploy", "arguments": '{"env":"prod"}'}}],
    }
    assert text_of(msg) == '\ndeploy {"env":"prod"}'


def test_episode_and_record_defaults():
    ep = Episode(
        run_id="r", scenario_id="s", kind="hard", model="m", condition="C0", seed=0,
        session_id="x",
    )
    assert ep.probe == []
    assert ep.error is None
    assert Pin(session_id="s", text="t").source == "explicit"
