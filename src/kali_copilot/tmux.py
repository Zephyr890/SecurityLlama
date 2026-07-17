"""Bounded tmux capture, chat-window control, and safe paste-buffer operations."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kali_copilot.sanitize import sanitize_for_display

PANE_PATTERN = re.compile(r"^%[0-9]+$")
WINDOW_PATTERN = re.compile(r"^@[0-9]+$")
SESSION_PATTERN = re.compile(r"^\$[0-9]+$")
CHAT_WINDOW_OPTION = "@securityllama_chat"
CHAT_ORIGIN_PANE_OPTION = "@securityllama_origin_pane"
CHAT_ORIGIN_CWD_OPTION = "@securityllama_origin_cwd"


class TmuxError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureResult:
    text: str
    pane_id: str
    cwd: str


@dataclass(frozen=True)
class ChatWindowResult:
    action: str
    window_id: str


def validate_pane_id(pane_id: str) -> str:
    if not PANE_PATTERN.fullmatch(pane_id):
        raise TmuxError("invalid tmux pane identifier")
    return pane_id


def _validate_window_id(window_id: str) -> str:
    if not WINDOW_PATTERN.fullmatch(window_id):
        raise TmuxError("invalid tmux window identifier")
    return window_id


def _validate_session_id(session_id: str) -> str:
    if not SESSION_PATTERN.fullmatch(session_id):
        raise TmuxError("invalid tmux session identifier")
    return session_id


def _tmux_output(
    arguments: list[str], *, optional: bool = False, socket_name: str | None = None
) -> str:
    command = ["tmux"]
    if socket_name:
        command.extend(["-L", socket_name])
    command.extend(arguments)
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable and validated arguments
            command, check=False, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TmuxError(f"tmux command failed: {sanitize_for_display(str(exc))}") from exc
    if result.returncode != 0:
        if optional:
            return ""
        detail = sanitize_for_display(result.stderr.strip()) or "tmux returned a non-zero status"
        raise TmuxError(f"tmux command failed: {detail}")
    return result.stdout.rstrip("\r\n")


def _window_option(target: str, option: str) -> str:
    return _tmux_output(["show-options", "-w", "-v", "-t", target, option], optional=True)


def _set_chat_origin(window_id: str, pane_id: str, cwd: str) -> None:
    for option, value in (
        (CHAT_WINDOW_OPTION, "1"),
        (CHAT_ORIGIN_PANE_OPTION, pane_id),
        (CHAT_ORIGIN_CWD_OPTION, cwd),
    ):
        _tmux_output(["set-option", "-w", "-t", window_id, option, value])


def _resolve_executable(executable: str) -> str:
    candidate = Path(executable).expanduser()
    if not candidate.is_absolute():
        located = shutil.which(executable)
        if located is None:
            raise TmuxError("securityllama executable is unavailable; reinstall the package")
        candidate = Path(located)
    candidate = candidate.resolve()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise TmuxError("securityllama executable is unavailable; reinstall the package")
    return str(candidate)


def open_chat_window(*, pane_id: str, cwd: str, executable: str) -> ChatWindowResult:
    """Create, focus, or toggle one persistent SecurityLlama window in a tmux session."""
    origin_pane = validate_pane_id(pane_id)
    if "\x00" in cwd or len(cwd) > 4096 or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise TmuxError(
            "originating pane directory is unavailable; change to an existing directory"
        )
    launcher = _resolve_executable(executable)
    current_window = _validate_window_id(
        _tmux_output(["display-message", "-p", "-t", origin_pane, "#{window_id}"])
    )
    session_id = _validate_session_id(
        _tmux_output(["display-message", "-p", "-t", origin_pane, "#{session_id}"])
    )
    if _window_option(current_window, CHAT_WINDOW_OPTION) == "1":
        _tmux_output(["last-window", "-t", session_id])
        return ChatWindowResult("returned", current_window)

    listed = _tmux_output(
        ["list-windows", "-t", session_id, "-F", "#{window_id}\t#{@securityllama_chat}"]
    )
    chat_window = ""
    for line in listed.splitlines():
        window_id, separator, marker = line.partition("\t")
        if separator and marker == "1":
            chat_window = _validate_window_id(window_id)
            break
    if chat_window:
        _set_chat_origin(chat_window, origin_pane, cwd)
        _tmux_output(["select-window", "-t", chat_window])
        return ChatWindowResult("focused", chat_window)

    # tmux accepts one shell-command for a new window. Every value here is local,
    # validated metadata; terminal capture and model output never enter this command.
    chat_command = shlex.join([launcher, "chat", "--pane", origin_pane])
    chat_window = _validate_window_id(
        _tmux_output(
            [
                "new-window",
                "-d",
                "-P",
                "-F",
                "#{window_id}",
                "-t",
                f"{session_id}:",
                "-n",
                "securityllama",
                "-c",
                cwd,
                chat_command,
            ]
        )
    )
    _set_chat_origin(chat_window, origin_pane, cwd)
    _tmux_output(["select-window", "-t", chat_window])
    return ChatWindowResult("created", chat_window)


def current_chat_origin_pane(default_pane: str) -> str:
    """Return the latest pane that opened this chat window, or the validated fallback."""
    fallback = validate_pane_id(default_pane)
    chat_pane = os.environ.get("TMUX_PANE")
    if not chat_pane or not PANE_PATTERN.fullmatch(chat_pane):
        return fallback
    if _window_option(chat_pane, CHAT_WINDOW_OPTION) != "1":
        return fallback
    origin = _window_option(chat_pane, CHAT_ORIGIN_PANE_OPTION)
    return origin if PANE_PATTERN.fullmatch(origin) else fallback


def pane_current_path(pane_id: str, *, socket_name: str | None = None) -> str:
    """Read and sanitize the current directory reported by one validated pane."""
    target = validate_pane_id(pane_id)
    cwd = sanitize_for_display(
        _tmux_output(
            ["display-message", "-p", "-t", target, "#{pane_current_path}"],
            socket_name=socket_name,
        )
    )
    if "\n" in cwd or "\x00" in cwd or len(cwd) > 4096 or not Path(cwd).is_absolute():
        raise TmuxError(f"tmux pane {target} reported an invalid working directory")
    return cwd


def display_message(message: str) -> None:
    """Display one sanitized diagnostic in the tmux status line."""
    safe = sanitize_for_display(message).replace("\n", " ")[:500]
    _tmux_output(["display-message", safe])


def capture_pane(pane_id: str, max_lines: int, *, socket_name: str | None = None) -> CaptureResult:
    """Capture only the explicitly identified originating pane."""
    target = validate_pane_id(pane_id)
    command = ["tmux"]
    if socket_name:
        command.extend(["-L", socket_name])
    command.extend(["capture-pane", "-p", "-J", "-S", f"-{max_lines}", "-t", target])
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable and validated pane argument
            command, check=True, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TmuxError(f"could not capture tmux pane {target}: {exc}") from exc
    return CaptureResult(result.stdout, target, pane_current_path(target, socket_name=socket_name))


def copy_to_buffer(command_text: str, *, socket_name: str | None = None) -> None:
    """Copy a proposal through stdin; never type it into a pane."""
    if any(char in command_text for char in ("\n", "\r", "\x00")):
        raise TmuxError("refusing to copy a multiline or NUL-containing command")
    command = ["tmux"]
    if socket_name:
        command.extend(["-L", socket_name])
    command.extend(["load-buffer", "-"])
    try:
        subprocess.run(  # noqa: S603 - fixed executable; proposal is stdin data, not an argument
            command, input=command_text, text=True, check=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TmuxError(f"could not copy proposal to tmux buffer: {exc}") from exc
