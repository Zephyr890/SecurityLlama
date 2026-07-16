from __future__ import annotations

import subprocess

import pytest

from kali_copilot.tmux import TmuxError, capture_pane, copy_to_buffer


def test_invalid_pane_is_rejected_before_process_call() -> None:
    with pytest.raises(TmuxError, match="invalid"):
        capture_pane("; dangerous", 20)


def test_capture_uses_argument_array(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.extend(command)
        return subprocess.CompletedProcess(command, 0, "captured", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = capture_pane("%12", 42)
    assert result.text == "captured"
    assert seen == ["tmux", "capture-pane", "-p", "-J", "-S", "-42", "-t", "%12"]


def test_copy_uses_load_buffer_stdin_and_no_pane_typing(monkeypatch: pytest.MonkeyPatch) -> None:
    call: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        call["command"] = command
        call.update(kwargs)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    copy_to_buffer("printf safe")
    assert call["command"] == ["tmux", "load-buffer", "-"]
    assert call["input"] == "printf safe"


def test_copy_rejects_multiline() -> None:
    with pytest.raises(TmuxError):
        copy_to_buffer("first\nsecond")
