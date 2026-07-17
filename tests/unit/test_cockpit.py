from __future__ import annotations

import io
from datetime import UTC, datetime

from rich.console import Console

from kali_copilot.attachments import attach_file, load_attachment_state
from kali_copilot.cockpit import Cockpit, context_usage
from kali_copilot.config import AppConfig, AuditConfig, ContextConfig, OllamaConfig
from kali_copilot.models import ContextPacket, ConversationTurn, RedactionRecord
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
