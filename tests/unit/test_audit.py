from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kali_copilot.audit import AuditStore
from kali_copilot.models import AssistantResponse, ContextPacket


def test_audit_omits_raw_context_and_supports_memory(tmp_path: Path) -> None:
    database = tmp_path / "private" / "sessions.db"
    packet = ContextPacket(
        session_id="session",
        timestamp=datetime.now(UTC),
        mode="ask",
        question="What happened?",
        hostname="host",
        username="user",
        shell="zsh",
        cwd="/work",
        recent_output="SEEDED_RAW_SECRET_MUST_NOT_PERSIST",
        capture_truncated=False,
        redactions=[],
    )
    response = AssistantResponse(
        answer="A service answered.",
        proposed_command=None,
        command_explanation=None,
        risk="none",
        requires_root=False,
        network_effect="none",
        target_candidates=[],
        findings=["MEDIUM — BREACH lead: compression side channel; validate exploit prerequisites"],
        warnings=[],
        assumptions=[],
    )
    with AuditStore(database) as store:
        store.record(packet, response, None, endpoint_host="127.0.0.1", model="fixture")
        turns = store.recent_turns("session", 4)
        assert turns[0].question == "What happened?"
        assert "Ranked findings:" in turns[0].answer
        assert "MEDIUM — BREACH lead" in turns[0].answer
        assert store.history()[0]["mode"] == "ask"
    assert database.stat().st_mode & 0o777 == 0o600
    assert b"SEEDED_RAW_SECRET_MUST_NOT_PERSIST" not in database.read_bytes()
