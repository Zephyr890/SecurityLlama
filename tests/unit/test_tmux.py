from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

from kali_copilot.tmux import (
    TmuxError,
    capture_pane,
    copy_to_buffer,
    current_chat_origin_pane,
    open_chat_window,
)


def test_invalid_pane_is_rejected_before_process_call() -> None:
    with pytest.raises(TmuxError, match="invalid"):
        capture_pane("; dangerous", 20)


def test_capture_uses_argument_array(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        output = "/assessment\n" if command[1] == "display-message" else "captured"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = capture_pane("%12", 42)
    assert result.text == "captured"
    assert result.cwd == "/assessment"
    assert seen == [
        ["tmux", "capture-pane", "-p", "-J", "-S", "-42", "-t", "%12"],
        ["tmux", "display-message", "-p", "-t", "%12", "#{pane_current_path}"],
    ]


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


def _launcher(tmp_path: Path) -> Path:
    launcher = tmp_path / "bin" / "securityllama"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o700)
    return launcher


def test_open_chat_creates_marked_window_with_fixed_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _launcher(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        operation = command[1]
        if operation == "display-message":
            output = "@2\n" if command[-1] == "#{window_id}" else "$0\n"
        elif operation == "list-windows":
            output = "@2\t\n"
        elif operation == "new-window":
            output = "@3\n"
        else:
            output = ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = open_chat_window(pane_id="%7", cwd=str(tmp_path), executable=str(launcher))

    assert result.action == "created"
    assert result.window_id == "@3"
    new_window = next(call for call in calls if call[1] == "new-window")
    assert "-c" in new_window
    assert new_window[new_window.index("-c") + 1] == str(tmp_path)
    assert new_window[-1] == shlex.join([str(launcher), "chat", "--pane", "%7"])
    assert ["tmux", "set-option", "-w", "-t", "@3", "@securityllama_chat", "1"] in calls
    assert ["tmux", "select-window", "-t", "@3"] in calls
    assert all("send-keys" not in call for call in calls)


def test_open_chat_focuses_existing_window_and_updates_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _launcher(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        operation = command[1]
        if operation == "display-message":
            output = "@2\n" if command[-1] == "#{window_id}" else "$0\n"
        elif operation == "show-options":
            output = ""
        elif operation == "list-windows":
            output = "@1\t1\n@2\t\n"
        else:
            output = ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = open_chat_window(pane_id="%9", cwd=str(tmp_path), executable=str(launcher))

    assert result.action == "focused"
    assert result.window_id == "@1"
    assert [
        "tmux",
        "set-option",
        "-w",
        "-t",
        "@1",
        "@securityllama_origin_pane",
        "%9",
    ] in calls
    assert ["tmux", "select-window", "-t", "@1"] in calls
    assert not any(call[1] == "new-window" for call in calls)


def test_open_chat_from_chat_window_returns_to_previous_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _launcher(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        operation = command[1]
        if operation == "display-message":
            output = "@1\n" if command[-1] == "#{window_id}" else "$0\n"
        elif operation == "show-options":
            output = "1\n"
        else:
            output = ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = open_chat_window(pane_id="%3", cwd=str(tmp_path), executable=str(launcher))

    assert result.action == "returned"
    assert ["tmux", "last-window", "-t", "$0"] in calls
    assert not any(call[1] in {"list-windows", "new-window"} for call in calls)


def test_chat_reads_latest_origin_from_private_tmux_window_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TMUX_PANE", "%20")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        option = command[-1]
        output = "1\n" if option == "@securityllama_chat" else "%8\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert current_chat_origin_pane("%1") == "%8"
