from __future__ import annotations

import os
from pathlib import Path

import pytest

from kali_copilot.attachments import (
    AttachmentError,
    attach_file,
    clear_attachments,
    detach_file,
    load_attachment_state,
    read_attachments,
)
from kali_copilot.paths import AppPaths


def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "runtime"
    )


def test_attachment_state_persists_only_reference_and_content_is_sanitized(
    tmp_path: Path,
) -> None:
    app_paths = paths(tmp_path)
    source = tmp_path / "scan.txt"
    source.write_text("open 443\n\x1b[31mapi_key=abcdefghijklmnop\x1b[0m\n")
    reference = attach_file("session", source, max_files=4, max_file_bytes=4096, paths=app_paths)
    state = load_attachment_state("session", app_paths)
    assert state.attachments == [reference]
    state_file = next(app_paths.attachments_dir.iterdir())
    assert state_file.stat().st_mode & 0o777 == 0o600
    state_text = state_file.read_text()
    assert "open 443" not in state_text
    assert "abcdefghijklmnop" not in state_text

    bundle = read_attachments("session", max_file_bytes=4096, paths=app_paths)
    assert "open 443" in bundle.text
    assert "[REDACTED:token_assignment]" in bundle.text
    assert "abcdefghijklmnop" not in bundle.text
    assert "\x1b" not in bundle.text
    assert bundle.attachments == [reference]


def test_detach_and_clear_are_session_scoped(tmp_path: Path) -> None:
    app_paths = paths(tmp_path)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one")
    second.write_text("two")
    attach_file("session", first, max_files=4, max_file_bytes=4096, paths=app_paths)
    attach_file("session", second, max_files=4, max_file_bytes=4096, paths=app_paths)
    assert detach_file("session", first, app_paths)
    assert [item.path for item in load_attachment_state("session", app_paths).attachments] == [
        str(second)
    ]
    assert clear_attachments("session", app_paths) == 1
    assert load_attachment_state("session", app_paths).attachments == []


def test_binary_symlink_oversized_and_replaced_files_are_rejected(tmp_path: Path) -> None:
    app_paths = paths(tmp_path)
    binary = tmp_path / "binary.dat"
    binary.write_bytes(b"header\x00body")
    attach_file("binary", binary, max_files=4, max_file_bytes=4096, paths=app_paths)
    with pytest.raises(AttachmentError, match="binary attachment"):
        read_attachments("binary", max_file_bytes=4096, paths=app_paths)

    link = tmp_path / "link.txt"
    link.symlink_to(binary)
    with pytest.raises(AttachmentError, match="cannot open attachment"):
        attach_file("link", link, max_files=4, max_file_bytes=4096, paths=app_paths)

    oversized = tmp_path / "oversized.txt"
    oversized.write_text("x" * 4097)
    with pytest.raises(AttachmentError, match="max_attachment_file_bytes"):
        attach_file("large", oversized, max_files=4, max_file_bytes=4096, paths=app_paths)

    source = tmp_path / "replace.txt"
    source.write_text("original")
    attach_file("replace", source, max_files=4, max_file_bytes=4096, paths=app_paths)
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("replacement")
    os.replace(replacement, source)
    with pytest.raises(AttachmentError, match="was replaced"):
        read_attachments("replace", max_file_bytes=4096, paths=app_paths)
