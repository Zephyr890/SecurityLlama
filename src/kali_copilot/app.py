"""Application orchestration for non-interactive assistant modes."""

from __future__ import annotations

import getpass
import os
import platform
import socket
from datetime import UTC, datetime
from pathlib import Path

from kali_copilot.audit import AuditStore
from kali_copilot.config import AppConfig
from kali_copilot.models import AssistantResponse, ContextPacket
from kali_copilot.ollama import OllamaClient
from kali_copilot.paths import resolve_paths
from kali_copilot.policy import assess_proposal
from kali_copilot.sanitize import normalize_text, redact_secrets, strip_terminal_sequences
from kali_copilot.scope import active_scope
from kali_copilot.session import current_session


def make_basic_packet(
    mode: str,
    question: str,
    recent_output: str,
    *,
    current_buffer: str | None = None,
    cwd: str | None = None,
) -> ContextPacket:
    """Construct the non-tmux packet used by Milestone 1 commands."""
    session_id = current_session().session_id
    shell = Path(os.environ.get("SHELL", "unknown")).name
    return ContextPacket(
        session_id=session_id,
        timestamp=datetime.now(UTC),
        mode=mode,  # type: ignore[arg-type]
        question=question,
        hostname=socket.gethostname() or platform.node(),
        username=getpass.getuser(),
        shell=shell,
        cwd=cwd or os.getcwd(),
        current_buffer=current_buffer,
        recent_output=recent_output,
        capture_truncated=False,
        redactions=[],
        conversation_summary="",
        recent_turns=[],
    )


def ask_model(
    config: AppConfig,
    mode: str,
    question: str,
    recent_output: str,
    *,
    current_buffer: str | None = None,
) -> AssistantResponse:
    """Build a context packet and request a validated response."""
    cleaned_output = normalize_text(strip_terminal_sequences(recent_output))
    redacted_output = redact_secrets(cleaned_output)
    redacted_question = redact_secrets(normalize_text(strip_terminal_sequences(question)))
    redacted_buffer = redact_secrets(normalize_text(strip_terminal_sequences(current_buffer or "")))
    packet = make_basic_packet(
        mode,
        redacted_question.text,
        redacted_output.text,
        current_buffer=redacted_buffer.text if current_buffer is not None else None,
    )
    paths = resolve_paths()
    scope = active_scope(paths)
    updates: dict[str, object] = {
        "redactions": redacted_question.records + redacted_output.records + redacted_buffer.records,
        "active_scope": scope.summary() if scope else None,
    }
    if config.audit.enabled:
        with AuditStore(paths.database_file) as store:
            updates["recent_turns"] = store.recent_turns(
                packet.session_id, config.context.recent_turns
            )
    packet = packet.model_copy(update=updates)
    response = OllamaClient(config).chat(packet)
    policy = assess_proposal(response, scope, config.policy)
    if config.audit.enabled:
        from urllib.parse import urlsplit

        safe_response = response.model_copy(
            update={
                "answer": redact_secrets(strip_terminal_sequences(response.answer)).text,
                "command_explanation": redact_secrets(
                    strip_terminal_sequences(response.command_explanation or "")
                ).text
                or None,
                "warnings": [
                    redact_secrets(strip_terminal_sequences(item)).text
                    for item in response.warnings
                ],
                "assumptions": [
                    redact_secrets(strip_terminal_sequences(item)).text
                    for item in response.assumptions
                ],
            }
        )
        with AuditStore(paths.database_file) as store:
            store.record(
                packet,
                safe_response,
                policy,
                endpoint_host=urlsplit(config.ollama.base_url).hostname or "unknown",
                model=config.ollama.model,
            )
    return response
