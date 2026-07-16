"""Context collection with mandatory cleanup before packet construction."""

from __future__ import annotations

from dataclasses import dataclass

from kali_copilot.config import AppConfig
from kali_copilot.models import ContextPacket
from kali_copilot.sanitize import (
    normalize_text,
    redact_secrets,
    strip_terminal_sequences,
    truncate_text,
)
from kali_copilot.tmux import capture_pane


@dataclass
class ContextCollector:
    config: AppConfig

    def collect_tmux(self, pane_id: str, mode: str, question: str) -> ContextPacket:
        """Capture an originating pane and return a sanitized basic packet."""
        from kali_copilot.app import make_basic_packet

        capture = capture_pane(pane_id, self.config.context.max_capture_lines)
        cleaned = normalize_text(strip_terminal_sequences(capture.text))
        bounded = truncate_text(
            cleaned, self.config.context.max_capture_lines, self.config.context.max_capture_bytes
        )
        redacted = redact_secrets(bounded.text) if self.config.privacy.redact_secrets else None
        safe_question = redact_secrets(normalize_text(strip_terminal_sequences(question)))
        packet = make_basic_packet(
            mode, safe_question.text, redacted.text if redacted else bounded.text
        )
        return packet.model_copy(
            update={
                "pane_id": capture.pane_id,
                "capture_truncated": bounded.truncated,
                "redactions": (redacted.records if redacted else []) + safe_question.records,
            }
        )
