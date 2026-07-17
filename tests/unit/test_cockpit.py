from __future__ import annotations

from datetime import UTC, datetime

from kali_copilot.cockpit import context_usage
from kali_copilot.config import AppConfig, OllamaConfig
from kali_copilot.models import ContextPacket, ConversationTurn, RedactionRecord


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
