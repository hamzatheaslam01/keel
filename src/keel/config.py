"""Keel configuration models and loader."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("keel")

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8400
    db: str = "keel.db"


class UpstreamConfig(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    models: list[str]
    extra_body: dict[str, Any] = Field(default_factory=dict)
    timeout_s: float = 600.0


class TruncateConfig(BaseModel):
    older_than_turns: int = 3
    head_tokens: int = 200
    tail_tokens: int = 100


class CompactionConfig(BaseModel):
    strategy: str = "none"
    trigger_tokens: int = 6000
    keep_last_n: int = 4
    truncate: TruncateConfig = Field(default_factory=TruncateConfig)
    summarizer: str = "same_as_agent"


class PinsConfig(BaseModel):
    auto_extract: bool = False
    extractor_model: str = "qwen3-1.7b"
    min_confidence: float = 0.6
    max_input_chars: int = 8000


class ValidateConfig(BaseModel):
    enabled: bool = False
    judge_model: str = "qwen3-1.7b"


class KeelConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server: ServerConfig = Field(default_factory=ServerConfig)
    upstreams: list[UpstreamConfig] = Field(default_factory=list)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    pins: PinsConfig = Field(default_factory=PinsConfig)
    validate_: ValidateConfig = Field(default_factory=ValidateConfig, alias="validate")
    tokenizers: dict[str, str] = Field(default_factory=dict)  # model -> local tokenizer.json path
    model_files: dict[str, str] = Field(default_factory=dict)  # model -> local GGUF path


class ConfigError(ValueError):
    """Raised when a config file cannot be read or validated."""


def expand_env(text: str) -> str:
    """Replace each ${VAR} with os.environ.get(VAR, "")."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), text)


def load_config(path: str | Path) -> KeelConfig:
    """Read a YAML config, expand ${VAR}s, drop upstreams with empty base_url, validate."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        data = yaml.safe_load(expand_env(text))
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ConfigError(f"{p}: top level must be a mapping")
        ups = data.get("upstreams")
        if isinstance(ups, list):
            kept = []
            for up in ups:
                if isinstance(up, dict) and not str(up.get("base_url") or "").strip():
                    logger.warning("dropping upstream %r: empty base_url", up.get("name"))
                    continue
                kept.append(up)
            data["upstreams"] = kept
        return KeelConfig.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise ConfigError(f"{p}: {e}") from e
