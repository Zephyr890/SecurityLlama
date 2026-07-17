from __future__ import annotations

import asyncio
import io
from contextlib import suppress
from datetime import UTC, datetime

from rich.console import Console

import kali_copilot.cockpit as cockpit_module
from kali_copilot.attachments import attach_file, load_attachment_state
from kali_copilot.cockpit import COCKPIT_KEY_BINDINGS, Cockpit, context_usage
from kali_copilot.config import AppConfig, AuditConfig, ContextConfig, OllamaConfig
from kali_copilot.models import (
    AssistantResponse,
    BackgroundJob,
    ContextPacket,
    ConversationTurn,
    PolicyAssessment,
    RedactionRecord,
)
from kali_copilot.paths import AppPaths
from kali_copilot.session import current_session


def test_context_usage_exposes_budget_sources_without_raw_text() -> None:
    config = AppConfig(ollama=OllamaConfig(num_ctx=4096, num_predict=512))
    packet = ContextPacket(
        session_id="session",
        timestamp=datetime.now(UTC),
        mode="ask",
        question="What failed?",
        hostname="host",
        username="user",
        shell="zsh",
        cwd="/work",
        recent_output="bounded output",
        capture_truncated=True,
        redactions=[RedactionRecord(category="token", count=2)],
        recent_turns=[ConversationTurn(question="Earlier?", answer="Earlier answer")],
    )
    usage = context_usage(packet, config)
    assert usage["capacity"] == 4096
    assert usage["reserved_response"] == 512
    assert usage["terminal_chars"] == len("bounded output")
    assert usage["memory_turns"] == 1
    assert usage["redactions"] == 2
    assert usage["truncated"] is True


def test_cockpit_has_meta_o_and_control_g_close_bindings() -> None:
    keys = {tuple(str(key) for key in binding.keys) for binding in COCKPIT_KEY_BINDINGS.bindings}
    assert ("Keys.Escape", "o") in keys
    assert ("Keys.ControlG",) in keys


def test_cockpit_prompt_animates_while_background_job_runs() -> None:
    cockpit = Cockpit(
        AppConfig(audit=AuditConfig(enabled=False)),
        "%1",
        console=Console(file=io.StringIO(), force_terminal=False),
    )
    cockpit._running_jobs["a" * 32] = datetime.now(UTC)

    message = cockpit._prompt_message()

    assert "1 request" in message
    assert "s> " in message


def test_cockpit_monitor_renders_completed_job_without_reopen(monkeypatch) -> None:
    cockpit = Cockpit(
        AppConfig(audit=AuditConfig(enabled=False)),
        "%1",
        console=Console(file=io.StringIO(), force_terminal=False),
    )
    completed = BackgroundJob(
        job_id="a" * 32,
        session_id=current_session(cockpit.paths).session_id,
        pane_id="%1",
        mode="ask",
        question="Finished?",
        model="fixture-model",
        status="completed",
        pid=123,
        created_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        response=AssistantResponse(answer="Finished."),
        assessment=PolicyAssessment(
            scope_status="not_applicable",
            risk_status="none",
            explicit_targets=[],
            blocked_reasons=["no proposed command"],
            confirmation_required=False,
            insertion_allowed=False,
        ),
    )
    rendered: list[str] = []
    monkeypatch.setattr(cockpit_module, "list_jobs", lambda session_id, paths: [completed])
    monkeypatch.setattr(cockpit, "_render_job", lambda job: rendered.append(job.job_id))

    async def run_in_place(callback):
        callback()

    monkeypatch.setattr(cockpit_module, "run_in_terminal", run_in_place)

    async def exercise_monitor() -> None:
        task = asyncio.create_task(cockpit._monitor_background())
        await asyncio.sleep(0.25)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(exercise_monitor())
    assert rendered == [completed.job_id]


def test_multiple_answers_render_as_ordered_question_answer_cards() -> None:
    output = io.StringIO()
    cockpit = Cockpit(
        AppConfig(audit=AuditConfig(enabled=False)),
        "%1",
        console=Console(file=output, force_terminal=False, width=120),
    )
    assessment = PolicyAssessment(
        scope_status="not_applicable",
        risk_status="none",
        explicit_targets=[],
        blocked_reasons=["no proposed command"],
        confirmation_required=False,
        insertion_allowed=False,
    )

    def completed(job_id: str, question: str, answer: str) -> BackgroundJob:
        now = datetime.now(UTC)
        return BackgroundJob(
            job_id=job_id * 32,
            session_id="ordered-session",
            pane_id="%1",
            mode="ask",
            question=question,
            model="fixture-model",
            status="completed",
            pid=123,
            created_at=now,
            finished_at=now,
            response=AssistantResponse(answer=answer),
            assessment=assessment,
            viewed_at=now,
        )

    cockpit._render_job(completed("a", "FIRST_UNIQUE_QUESTION", "FIRST_UNIQUE_ANSWER"))
    cockpit._render_job(completed("b", "SECOND_UNIQUE_QUESTION", "SECOND_UNIQUE_ANSWER"))

    rendered = output.getvalue()
    positions = [
        rendered.index(marker)
        for marker in (
            "FIRST_UNIQUE_QUESTION",
            "FIRST_UNIQUE_ANSWER",
            "SECOND_UNIQUE_QUESTION",
            "SECOND_UNIQUE_ANSWER",
        )
    ]
    assert positions == sorted(positions)
    assert "Request aaaaaaaa" in rendered
    assert "Answer bbbbbbbb" in rendered


def test_cockpit_renders_proposed_command_only_once() -> None:
    output = io.StringIO()
    cockpit = Cockpit(
        AppConfig(audit=AuditConfig(enabled=False)),
        "%1",
        console=Console(file=output, force_terminal=False, width=120),
    )
    now = datetime.now(UTC)
    job = BackgroundJob(
        job_id="c" * 32,
        session_id="session",
        pane_id="%1",
        mode="suggest",
        question="Suggest one inert check command",
        model="fixture-model",
        status="completed",
        pid=123,
        created_at=now,
        finished_at=now,
        response=AssistantResponse(
            answer="Use this check.",
            proposed_command="printf unique-proposal",
            risk="low",
        ),
        assessment=PolicyAssessment(
            scope_status="not_applicable",
            risk_status="low",
            explicit_targets=[],
            blocked_reasons=[],
            confirmation_required=False,
            insertion_allowed=True,
        ),
        viewed_at=now,
    )

    cockpit._render_job(job)

    assert output.getvalue().count("printf unique-proposal") == 1


def test_cockpit_suppresses_legacy_conceptual_shell_proposal() -> None:
    output = io.StringIO()
    cockpit = Cockpit(
        AppConfig(audit=AuditConfig(enabled=False)),
        "%1",
        console=Console(file=output, force_terminal=False, width=120),
    )
    now = datetime.now(UTC)
    job = BackgroundJob(
        job_id="d" * 32,
        session_id="session",
        pane_id="%1",
        mode="ask",
        question="explain the basics of web app fuzzing with burpsuite community",
        model="fixture-model",
        status="completed",
        pid=123,
        created_at=now,
        finished_at=now,
        response=AssistantResponse(
            answer="Web fuzzing exercises application inputs.",
            proposed_command="/usr/bin/zsh -l",
            risk="unknown",
            network_effect="active",
        ),
        assessment=PolicyAssessment(
            scope_status="no_active_scope",
            risk_status="unknown",
            explicit_targets=[],
            blocked_reasons=["network proposal requires an active engagement scope"],
            confirmation_required=True,
            insertion_allowed=False,
        ),
        viewed_at=now,
    )

    cockpit._render_job(job)

    rendered = output.getvalue()
    assert "Web fuzzing exercises" in rendered
    assert "/usr/bin/zsh -l" not in rendered
    assert not cockpit.state.proposals


def test_cockpit_packet_keeps_session_attachment_and_omits_raw_persistence(tmp_path) -> None:
    app_paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "runtime"
    )
    source = tmp_path / "result.txt"
    source.write_text("port 8443 open\npassword=hunter2value\n")
    session_id = current_session(app_paths).session_id
    attach_file(
        session_id,
        source,
        max_files=4,
        max_file_bytes=4096,
        paths=app_paths,
    )
    config = AppConfig(
        audit=AuditConfig(enabled=False),
        context=ContextConfig(max_attachment_file_bytes=4096),
    )
    cockpit = Cockpit(config, "%1")
    cockpit.paths = app_paths
    cockpit.state.include_terminal = False
    packet = cockpit._packet("Review the attached result")
    assert "ATTACHMENT_BEGIN" in packet.recent_output
    assert "port 8443 open" in packet.recent_output
    assert "hunter2value" not in packet.recent_output
    assert "[REDACTED:token_assignment]" in packet.recent_output
    assert len(cockpit._last_attachments.attachments) == 1
    assert not app_paths.database_file.exists()


def test_cockpit_attach_survives_reopen_until_detached(tmp_path) -> None:
    app_paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "runtime"
    )
    source = tmp_path / "scan results.txt"
    source.write_text("service evidence")
    config = AppConfig(audit=AuditConfig(enabled=False))
    first = Cockpit(config, "%1", console=Console(file=io.StringIO(), force_terminal=False))
    first.paths = app_paths
    assert first._handle(f'/attach "{source}"')

    second_output = io.StringIO()
    reopened = Cockpit(config, "%1", console=Console(file=second_output, force_terminal=False))
    reopened.paths = app_paths
    assert reopened._handle("/attachments")
    assert "scan results.txt" in second_output.getvalue()
    assert reopened._handle("/detach all")
    assert load_attachment_state(current_session(app_paths).session_id, app_paths).attachments == []
