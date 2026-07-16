"""Bounded tmux capture and safe paste-buffer copy operations."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

PANE_PATTERN = re.compile(r"^%[0-9]+$")


class TmuxError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureResult:
    text: str
    pane_id: str


def validate_pane_id(pane_id: str) -> str:
    if not PANE_PATTERN.fullmatch(pane_id):
        raise TmuxError("invalid tmux pane identifier")
    return pane_id


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
    return CaptureResult(result.stdout, target)


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
