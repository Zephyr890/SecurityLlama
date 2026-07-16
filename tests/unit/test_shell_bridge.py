from __future__ import annotations

import json
from pathlib import Path

import pytest

from kali_copilot.models import ShellWidgetResponse
from kali_copilot.shell_bridge import (
    ShellBridgeError,
    create_request,
    extract_response,
    read_request,
    write_response,
)


def private_file(path: Path, content: str = "") -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_exact_buffer_round_trip_without_execution(tmp_path: Path) -> None:
    buffer = 'curl -kI "https://10.10.10.25/a b"; printf harmless'
    buffer_file = private_file(tmp_path / "buffer", buffer)
    request_file = tmp_path / "request"
    create_request(
        buffer_file,
        request_file,
        shell="zsh",
        cwd="/work",
        cursor=len(buffer),
        pane="%1",
        last_status=0,
    )
    assert read_request(request_file).buffer == buffer

    response_file = tmp_path / "response"
    write_response(
        response_file,
        ShellWidgetResponse(action="insert", command="curl -I https://10.10.10.25/"),
    )
    command_file = tmp_path / "command"
    assert extract_response(response_file, command_file) == "insert"
    assert command_file.read_text() == "curl -I https://10.10.10.25/"
    assert command_file.stat().st_mode & 0o777 == 0o600


def test_cancellation_has_no_command_file(tmp_path: Path) -> None:
    response_file = private_file(
        tmp_path / "response", ShellWidgetResponse(action="none").model_dump_json()
    )
    command_file = tmp_path / "command"
    assert extract_response(response_file, command_file) == "none"
    assert not command_file.exists()


def test_world_readable_request_rejected(tmp_path: Path) -> None:
    request_file = private_file(tmp_path / "request", json.dumps({}))
    request_file.chmod(0o644)
    with pytest.raises(ShellBridgeError, match="permissions"):
        read_request(request_file)
