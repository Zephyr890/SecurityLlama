from kali_copilot.sanitize import (
    redact_secrets,
    sanitize_for_display,
    strip_terminal_sequences,
    truncate_text,
)


def test_terminal_sequences_and_controls_removed() -> None:
    raw = "ok\x1b[31m red\x1b[0m\x1b]0;malicious title\x07\x00 done\n"
    assert strip_terminal_sequences(raw) == "ok red done\n"
    assert "\x1b" not in sanitize_for_display(raw)


def test_high_confidence_secret_categories_redacted() -> None:
    raw = """Authorization: Bearer abcdefghijklmnopqrstuvwxyz
Cookie: session=topsecretvalue
api_key=abcdefghijklmnop
AKIAABCDEFGHIJKLMNOP
ghp_abcdefghijklmnopqrstuvwxyz123456
eyJabcdefghijk.abcdefghijkl.abcdefghijkl
root:$6$salt$hash:1:2:3:4:5:6:7
-----BEGIN PRIVATE KEY-----
secretmaterial
-----END PRIVATE KEY-----
"""
    result = redact_secrets(raw)
    assert "topsecretvalue" not in result.text
    assert "secretmaterial" not in result.text
    categories = {record.category for record in result.records}
    assert {"authorization_header", "cookie", "token_assignment", "private_key"} <= categories


def test_truncation_keeps_recent_complete_text() -> None:
    result = truncate_text("one\ntwo\nthree\nfour\n", max_lines=2, max_bytes=100)
    assert result.text == "three\nfour\n"
    assert result.truncated
    byte_result = truncate_text("old\n" + "é" * 20 + "\nnew\n", max_lines=10, max_bytes=12)
    assert len(byte_result.text.encode()) <= 12
    assert byte_result.text.endswith("new\n")
