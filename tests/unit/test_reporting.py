from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kali_copilot.audit import AuditStore
from kali_copilot.models import AssistantResponse, ContextPacket
from kali_copilot.reporting import json_report, markdown_report


def test_reports_include_redacted_meaning_notes_and_no_raw_context(tmp_path: Path) -> None:
    packet = ContextPacket(
        session_id="s1",
        timestamp=datetime.now(UTC),
        mode="ask",
        question="What happened?",
        hostname="host",
        username="user",
        shell="zsh",
        cwd="/work",
        recent_output="RAW_CONTEXT_MUST_NOT_EXPORT",
        capture_truncated=False,
        redactions=[],
    )
    response = AssistantResponse(answer="A service answered.", proposed_command="printf safe")
    database = tmp_path / "data" / "sessions.db"
    with AuditStore(database) as store:
        interaction = store.record(
            packet, response, None, endpoint_host="127.0.0.1", model="fixture"
        )
        store.update_disposition(interaction, "staged")
        store.name_session("s1", "Lab One")
        store.add_note("s1", "Validate manually", bookmarked=True)
        markdown = markdown_report(store, "s1")
        json_text = json_report(store, "s1")
    assert "Lab One" in markdown
    assert "Validate manually" in markdown
    assert "Disposition: staged" in markdown
    assert "RAW_CONTEXT_MUST_NOT_EXPORT" not in markdown
    assert '"raw_context_included": false' in json_text
    assert "RAW_CONTEXT_MUST_NOT_EXPORT" not in json_text
