from __future__ import annotations

import io
import sys
from pathlib import Path

from kali_copilot import cli
from kali_copilot.config import AppConfig, AuditConfig
from kali_copilot.models import AssistantResponse, PolicyAssessment
from kali_copilot.ollama import ChatResult, InvalidModelResponseError
from kali_copilot.paths import AppPaths
from kali_copilot.proposal import stage_proposal
from kali_copilot.session import SessionState
from kali_copilot.tmux import TmuxError


def test_empty_cli_is_safe() -> None:
    assert cli.main([]) == 0


def test_open_chat_cli_forwards_validated_tmux_metadata(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def open_chat_window(*, pane_id: str, cwd: str, executable: str) -> None:
        seen.update(pane_id=pane_id, cwd=cwd, executable=executable)

    monkeypatch.setattr(cli, "open_chat_window", open_chat_window)

    assert (
        cli.main(
            [
                "_open-chat",
                "--pane",
                "%7",
                "--cwd",
                "/assessment",
                "--executable",
                "/opt/securityllama/bin/securityllama",
            ]
        )
        == 0
    )
    assert seen == {
        "pane_id": "%7",
        "cwd": "/assessment",
        "executable": "/opt/securityllama/bin/securityllama",
    }


def test_open_chat_failure_is_visible_in_tmux_status(monkeypatch, capsys) -> None:
    messages: list[str] = []

    def fail(**kwargs: str) -> None:
        raise TmuxError("fixture launch failure")

    monkeypatch.setattr(cli, "open_chat_window", fail)
    monkeypatch.setattr(cli, "display_message", messages.append)

    result = cli.main(
        [
            "_open-chat",
            "--pane",
            "%7",
            "--cwd",
            "/assessment",
            "--executable",
            "/opt/securityllama/bin/securityllama",
        ]
    )

    assert result == 6
    assert messages == ["SecurityLlama chat failed: fixture launch failure"]
    assert "fixture launch failure" in capsys.readouterr().err


def test_debug_prints_redacted_model_response_diagnostics(monkeypatch, capsys) -> None:
    result = ChatResult(
        content="api_key=abcdefghijklmnop {bad",
        done=True,
        done_reason="length",
        prompt_eval_count=300,
        eval_count=256,
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise InvalidModelResponseError("invalid response", result, result)

    monkeypatch.setattr(cli, "load_config", lambda: AppConfig())
    monkeypatch.setattr(cli, "ask_model", fail)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    assert cli.main(["--debug", "ask", "test"]) == 5
    stderr = capsys.readouterr().err
    assert "done_reason='length'" in stderr
    assert "[REDACTED:token_assignment]" in stderr
    assert "abcdefghijklmnop" not in stderr


def test_consume_proposal_cli_writes_inert_private_command_once(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "runtime"
    )
    response = AssistantResponse(
        answer="Review", proposed_command="printf safe", risk="low", network_effect="none"
    )
    assessment = PolicyAssessment(
        scope_status="not_applicable",
        risk_status="low",
        explicit_targets=[],
        blocked_reasons=[],
        confirmation_required=False,
        insertion_allowed=True,
    )
    stage_proposal(
        response,
        assessment,
        session_id="session",
        pane_id="%4",
        ttl_seconds=60,
        paths=paths,
    )
    monkeypatch.setattr(cli, "resolve_paths", lambda: paths)
    monkeypatch.setattr(cli, "current_session", lambda *_args: SessionState("session"))
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(audit=AuditConfig(enabled=False)))
    command_file = tmp_path / "command"
    argv = ["_consume-proposal", "--pane", "%4", "--command-file", str(command_file)]
    assert cli.main(argv) == 0
    assert capsys.readouterr().out.strip() == "insert"
    assert command_file.read_text() == "printf safe"
    assert command_file.stat().st_mode & 0o777 == 0o600
    command_file.unlink()
    assert cli.main(argv) == 0
    assert capsys.readouterr().out.strip() == "none"
    assert not command_file.exists()
