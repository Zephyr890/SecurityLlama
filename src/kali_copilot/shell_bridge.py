"""Secure file bridge between line editors and the interactive assistant."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from pydantic import ValidationError

from kali_copilot.models import ShellWidgetRequest, ShellWidgetResponse


class ShellBridgeError(RuntimeError):
    pass


def _check_private_regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ShellBridgeError(f"cannot inspect bridge file {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ShellBridgeError("bridge file must be a regular file owned by the invoking user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ShellBridgeError("bridge file permissions must be 0600 or stricter")


def read_request(path: Path) -> ShellWidgetRequest:
    """Read and validate a small, private widget request."""
    _check_private_regular_file(path)
    if path.stat().st_size > 65536:
        raise ShellBridgeError("widget request is too large")
    try:
        return ShellWidgetRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ShellBridgeError(f"invalid widget request: {exc}") from exc


def write_response(path: Path, response: ShellWidgetResponse) -> None:
    """Write a response without following symlinks and enforce mode 0600."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(response.model_dump_json())
    except OSError as exc:
        raise ShellBridgeError(f"cannot write widget response: {exc}") from exc


def create_request(
    buffer_file: Path,
    request_file: Path,
    *,
    shell: str,
    cwd: str,
    cursor: int,
    pane: str | None,
    last_status: int | None,
) -> None:
    """Build JSON from a private raw buffer file, keeping buffer text out of argv."""
    _check_private_regular_file(buffer_file)
    buffer = buffer_file.read_text(encoding="utf-8")
    request = ShellWidgetRequest(
        shell=shell,
        cwd=cwd,
        buffer=buffer,
        cursor_position=cursor,
        tmux_pane=pane,
        last_exit_status=last_status,
        mode_hint="review",
    )
    write_private_json(request_file, request.model_dump_json())


def write_private_json(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def extract_response(response_file: Path, command_file: Path) -> str:
    """Validate a response and write an insert command as inert file data."""
    _check_private_regular_file(response_file)
    try:
        response = ShellWidgetResponse.model_validate_json(
            response_file.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ShellBridgeError(f"invalid widget response: {exc}") from exc
    if response.action == "insert" and response.command is not None:
        write_private_json(command_file, response.command)
    return response.action
