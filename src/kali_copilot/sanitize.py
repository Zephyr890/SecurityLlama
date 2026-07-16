"""Pure terminal cleanup, bounded truncation, and high-confidence redaction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from kali_copilot.models import RedactionRecord

OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)
CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ESC_RE = re.compile(r"\x1b[@-_]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

REDACTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----.*?"
            r"-----END(?: [A-Z0-9]+)? PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("authorization_header", re.compile(r"(?im)^\s*(?:proxy-)?authorization\s*:\s*\S.*$")),
    ("cookie", re.compile(r"(?im)^\s*(?:set-)?cookie\s*:\s*\S.*$")),
    (
        "token_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret(?:[_-]?key)?|password|passwd|pwd)"
            r"\s*[:=]\s*(['\"]?)[^\s'\";]{6,}\2"
        ),
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    (
        "shadow_hash",
        re.compile(r"(?m)^[a-z_][a-z0-9_-]*:\$(?:1|2[aby]?|5|6|y)\$[^:\n]+:[^\n]*$"),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
)


@dataclass(frozen=True)
class TruncationResult:
    text: str
    truncated: bool
    original_lines: int
    original_bytes: int


@dataclass(frozen=True)
class RedactionResult:
    text: str
    records: list[RedactionRecord]


def strip_terminal_sequences(text: str) -> str:
    """Remove CSI, OSC, other escape sequences, and unsafe C0 controls."""
    text = OSC_RE.sub("", text)
    text = CSI_RE.sub("", text)
    text = ESC_RE.sub("", text)
    return CONTROL_RE.sub("", text)


def normalize_text(text: str) -> str:
    """Normalize newlines and remove invalid Unicode replacement hazards."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufffd", "")


def truncate_text(text: str, max_lines: int, max_bytes: int) -> TruncationResult:
    """Keep the most recent text while respecting line and UTF-8 byte bounds."""
    original_lines = len(text.splitlines())
    encoded = text.encode("utf-8")
    original_bytes = len(encoded)
    lines = text.splitlines(keepends=True)
    bounded = "".join(lines[-max_lines:])
    bounded_bytes = bounded.encode("utf-8")
    if len(bounded_bytes) > max_bytes:
        bounded = bounded_bytes[-max_bytes:].decode("utf-8", errors="ignore")
        if "\n" in bounded:
            bounded = bounded.split("\n", 1)[1]
    truncated = bounded != text
    return TruncationResult(bounded, truncated, original_lines, original_bytes)


def redact_secrets(text: str) -> RedactionResult:
    """Redact only known, high-confidence secret shapes."""
    records: list[RedactionRecord] = []
    result = text
    for category, pattern in REDACTION_PATTERNS:
        result, count = pattern.subn(f"[REDACTED:{category}]", result)
        if count:
            records.append(RedactionRecord(category=category, count=count))
    return RedactionResult(result, records)


def sanitize_for_display(text: str) -> str:
    """Make untrusted text safe for literal terminal display."""
    return normalize_text(strip_terminal_sequences(text))
