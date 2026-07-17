from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

from kali_copilot import background
from kali_copilot.background import list_jobs, load_job, mark_viewed, run_job, start_job
from kali_copilot.config import AppConfig, AuditConfig
from kali_copilot.models import AssistantResponse, ContextPacket
from kali_copilot.paths import AppPaths
from kali_copilot.prompting import enforce_request_contract


class _Pipe(io.BytesIO):
    def close(self) -> None:
        self.was_closed = True


class _Process:
    def __init__(self) -> None:
        self.pid = 43210
        self.stdin = _Pipe()
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True


def _paths(root: Path) -> AppPaths:
    return AppPaths(root / "config", root / "data", root / "cache", root / "runtime")


def _packet() -> ContextPacket:
    return ContextPacket(
        session_id="session-1",
        timestamp=datetime.now(UTC),
        mode="ask",
        question="What should I verify?",
        hostname="kali",
        username="operator",
        shell="zsh",
        cwd="/assessment",
        recent_output="sensitive synthetic terminal evidence",
        capture_truncated=False,
        redactions=[],
    )


def test_start_job_keeps_raw_context_in_anonymous_pipe(monkeypatch, tmp_path: Path) -> None:
    process = _Process()
    monkeypatch.setattr(background.subprocess, "Popen", lambda *args, **kwargs: process)
    paths = _paths(tmp_path)

    job = start_job(
        AppConfig(audit=AuditConfig(enabled=False)),
        _packet(),
        None,
        paths=paths,
    )

    record = (paths.jobs_dir / f"{job.job_id}.json").read_text()
    assert "sensitive synthetic terminal evidence" not in record
    assert "sensitive synthetic terminal evidence" in process.stdin.getvalue().decode()
    assert job.status == "queued"
    assert (paths.jobs_dir / f"{job.job_id}.json").stat().st_mode & 0o077 == 0


def test_worker_publishes_sanitized_result_and_view_state(monkeypatch, tmp_path: Path) -> None:
    process = _Process()
    monkeypatch.setattr(background.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        background.OllamaClient,
        "chat",
        lambda self, packet: AssistantResponse(
            answer="Review complete. password=supersecretvalue",
            proposed_command="nmap -sV 10.10.10.25",
            risk="low",
            network_effect="active",
        ),
    )
    paths = _paths(tmp_path)
    config = AppConfig(audit=AuditConfig(enabled=False))
    packet = _packet()
    job = start_job(config, packet, None, paths=paths)
    payload = json.dumps(
        {
            "config": config.model_dump(mode="json"),
            "packet": packet.model_dump(mode="json"),
            "scope": None,
        }
    ).encode()

    run_job(job.job_id, payload, paths)

    completed = load_job(job.job_id, paths)
    assert completed.status == "completed"
    assert completed.response is not None
    assert "supersecretvalue" not in completed.response.answer
    assert completed.assessment is not None
    assert completed.assessment.insertion_allowed is False
    assert list_jobs("session-1", paths) == [completed]
    assert mark_viewed(completed, paths).viewed_at is not None


def test_secret_bearing_proposal_is_omitted_instead_of_rewritten() -> None:
    response = background._safe_response(
        AssistantResponse(
            answer="Use the configured credential.",
            proposed_command="tool --password=supersecretvalue",
            risk="low",
        )
    )

    assert response.proposed_command is None
    assert any("omitted" in warning for warning in response.warnings)


def test_conceptual_question_cannot_publish_model_generated_shell_command() -> None:
    packet = _packet().model_copy(
        update={
            "question": "explain the basics of web app fuzzing with burpsuite community",
            "shell": "/usr/bin/zsh -l",
        }
    )
    response = enforce_request_contract(
        AssistantResponse(
            answer="Web fuzzing tests application inputs.",
            proposed_command="/usr/bin/zsh -l",
            command_explanation="Run the shell.",
            risk="unknown",
            requires_root=False,
            network_effect="active",
            warnings=["Network effect is active"],
        ),
        packet,
    )

    assert response.proposed_command is None
    assert response.command_explanation is None
    assert response.risk == "none"
    assert response.network_effect == "none"
    assert response.requires_root is None
    assert "Network effect is active" not in response.warnings
    assert any("did not ask for one" in warning for warning in response.warnings)
