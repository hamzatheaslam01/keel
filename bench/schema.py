"""DecayBench-lite scenario models."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class ConstraintIntro(BaseModel):
    turn: int
    role: Literal["user", "tool"]


class Constraint(BaseModel):
    text: str
    introduced_at: ConstraintIntro
    keywords: list[str]

    @model_validator(mode="after")
    def _check(self) -> Constraint:
        if not self.keywords or any(not k.strip() for k in self.keywords):
            raise ValueError("constraint.keywords must be non-empty and contain no blank keyword")
        return self


class FillerSpec(BaseModel):
    kind: Literal["log", "csv", "json", "text"]
    n: int
    seed: int = 0

    @model_validator(mode="after")
    def _check(self) -> FillerSpec:
        if self.n < 1:
            raise ValueError("filler.n must be >= 1")
        return self


class UserTurn(BaseModel):
    role: Literal["user"]
    content: str


class AssistantTurn(BaseModel):
    role: Literal["assistant"]
    content: str


class ToolScriptTurn(BaseModel):
    role: Literal["tool_script"]
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None
    output_file: str | None = None
    filler: FillerSpec | None = None

    @model_validator(mode="after")
    def _check(self) -> ToolScriptTurn:
        if self.output is None and self.output_file is None and self.filler is None:
            raise ValueError("tool_script needs at least one of output, output_file, filler")
        return self


Turn = Annotated[UserTurn | AssistantTurn | ToolScriptTurn, Field(discriminator="role")]


def _compile(pattern: str, what: str) -> None:
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"invalid regex in {what}: {e}") from e


class GraderSpec(BaseModel):
    type: Literal["tool_call_forbidden", "tool_call_arg", "regex_present", "regex_absent"]
    tool: str | None = None
    arg: str | None = None
    equals: Any = None
    matches: str | None = None
    not_in: list[Any] | None = None
    pattern: str | None = None

    @model_validator(mode="after")
    def _check(self) -> GraderSpec:
        if self.type == "tool_call_forbidden":
            if not self.tool:
                raise ValueError("tool_call_forbidden needs tool")
        elif self.type == "tool_call_arg":
            if not self.tool or not self.arg:
                raise ValueError("tool_call_arg needs tool and arg")
            n = sum(x is not None for x in (self.equals, self.matches, self.not_in))
            if n != 1:
                raise ValueError("tool_call_arg needs exactly one of equals/matches/not_in")
            if self.matches is not None:
                _compile(self.matches, "matches")
        else:
            if self.pattern is None:
                raise ValueError(f"{self.type} needs pattern")
            _compile(self.pattern, "pattern")
        return self


class Graders(BaseModel):
    violation: GraderSpec
    task_success: GraderSpec


class Scenario(BaseModel):
    id: str
    kind: Literal["hard", "soft"]
    domain: Literal["devops", "support", "calendar_email", "data_pipelines"]
    system_prompt: str
    constraint: Constraint
    tools: list[str]
    turns: list[Turn]
    compact_at: int
    probe: UserTurn
    probe_tool_outputs: dict[str, str] = Field(default_factory=dict)
    grader: Graders

    @model_validator(mode="after")
    def _check(self) -> Scenario:
        if not self.id.strip():
            raise ValueError("id must be non-empty")
        t = self.constraint.introduced_at.turn
        if not (1 <= t < self.compact_at <= len(self.turns)):
            raise ValueError(
                f"need 1 <= introduced_at.turn ({t}) < compact_at ({self.compact_at})"
                f" <= len(turns) ({len(self.turns)})"
            )
        return self


def load_scenario(path: Path) -> Scenario:
    raise NotImplementedError("T-13")


def load_scenarios(directory: Path) -> list[Scenario]:
    raise NotImplementedError("T-13")


def resolve_output(turn: ToolScriptTurn, root: Path) -> str:
    raise NotImplementedError("T-13")
