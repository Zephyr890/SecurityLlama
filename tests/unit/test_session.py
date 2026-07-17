from __future__ import annotations

from pathlib import Path

from kali_copilot.attachments import attach_file, load_attachment_state
from kali_copilot.paths import AppPaths
from kali_copilot.session import clear_session, current_session


def test_new_session_drops_previous_attachment_context(tmp_path: Path) -> None:
    paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "runtime"
    )
    old_session = current_session(paths)
    source = tmp_path / "evidence.txt"
    source.write_text("bounded evidence")
    attach_file(
        old_session.session_id,
        source,
        max_files=4,
        max_file_bytes=4096,
        paths=paths,
    )
    new_session = clear_session(paths)
    assert new_session.session_id != old_session.session_id
    assert load_attachment_state(old_session.session_id, paths).attachments == []
    assert load_attachment_state(new_session.session_id, paths).attachments == []


def test_console_session_survives_directory_and_terminal_changes(
    tmp_path: Path, monkeypatch
) -> None:
    paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "runtime"
    )
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    monkeypatch.chdir(first_directory)
    first = current_session(paths)

    monkeypatch.chdir(second_directory)
    second = current_session(paths)

    assert second.session_id == first.session_id
