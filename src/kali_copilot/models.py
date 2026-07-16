"""Versioned models at model, shell, policy, and persistence boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RedactionRecord(BoundaryModel):
    category: str = Field(min_length=1, max_length=64)
    count: int = Field(ge=1, le=10000)


class ScopeSummary(BoundaryModel):
    name: str = Field(min_length=1, max_length=128)
    authorized: bool
    permissions: list[str] = Field(max_length=50)
    allowed_cidrs: list[str] = Field(max_length=100)
    allowed_domains: list[str] = Field(max_length=100)
    denied_categories: list[str] = Field(max_length=50)


class ConversationTurn(BoundaryModel):
    question: str = Field(max_length=4000)
    answer: str = Field(max_length=12000)


class ContextPacket(BoundaryModel):
    schema_version: Literal["1"] = "1"
    session_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    mode: Literal["ask", "explain", "review", "suggest"]
    question: str = Field(max_length=20000)
    hostname: str = Field(max_length=255)
    username: str = Field(max_length=255)
    shell: str = Field(max_length=255)
    cwd: str = Field(max_length=4096)
    pane_id: str | None = Field(default=None, max_length=64)
    current_buffer: str | None = Field(default=None, max_length=16000)
    cursor_position: int | None = Field(default=None, ge=0, le=16000)
    last_exit_status: int | None = Field(default=None, ge=0, le=255)
    recent_output: str = Field(max_length=1_048_576)
    capture_truncated: bool
    redactions: list[RedactionRecord] = Field(max_length=50)
    active_scope: ScopeSummary | None = None
    conversation_summary: str = Field(default="", max_length=10000)
    recent_turns: list[ConversationTurn] = Field(default_factory=list, max_length=20)


class AssistantResponse(BoundaryModel):
    schema_version: Literal["1"] = "1"
    answer: str = Field(min_length=1, max_length=12000)
    proposed_command: str | None = Field(default=None, max_length=16000)
    command_explanation: str | None = Field(default=None, max_length=8000)
    risk: Literal["none", "low", "medium", "high", "critical", "unknown"]
    requires_root: bool | None
    network_effect: Literal["none", "passive", "active", "unknown"]
    target_candidates: list[str] = Field(max_length=50)
    warnings: list[str] = Field(max_length=50)
    assumptions: list[str] = Field(max_length=50)

    @field_validator("proposed_command")
    @classmethod
    def single_line_command(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("proposed command must be a single line without control characters")
        return value


class PolicyAssessment(BoundaryModel):
    scope_status: Literal[
        "not_applicable", "in_scope", "out_of_scope", "unknown", "no_active_scope"
    ]
    risk_status: Literal["none", "low", "medium", "high", "critical", "unknown"]
    explicit_targets: list[str] = Field(max_length=100)
    blocked_reasons: list[str] = Field(max_length=50)
    confirmation_required: bool
    insertion_allowed: bool


class ShellWidgetRequest(BoundaryModel):
    schema_version: Literal["1"] = "1"
    shell: str = Field(max_length=255)
    cwd: str = Field(max_length=4096)
    buffer: str = Field(max_length=16000)
    cursor_position: int = Field(ge=0, le=16000)
    last_exit_status: int | None = Field(default=None, ge=0, le=255)
    tmux_pane: str | None = Field(default=None, max_length=64)
    mode_hint: Literal["ask", "explain", "review", "suggest"] | None = None


class ShellWidgetResponse(BoundaryModel):
    schema_version: Literal["1"] = "1"
    action: Literal["none", "insert", "copy"]
    command: str | None = Field(default=None, max_length=16000)
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("command")
    @classmethod
    def safe_command(cls, value: str | None) -> str | None:
        if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("command is not safe for a line-editing buffer")
        return value
