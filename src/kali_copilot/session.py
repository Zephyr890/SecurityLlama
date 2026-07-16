"""Logical session identifiers stored in private runtime state."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths


@dataclass(frozen=True)
class SessionState:
    session_id: str


def _state_path(paths: AppPaths) -> Path:
    tmux_key = os.environ.get("TMUX", "outside-tmux").split(",", 1)[0]
    suffix = (
        hashlib.sha256(tmux_key.encode()).hexdigest()[:16]
        if tmux_key != "outside-tmux"
        else str(os.getppid())
    )
    return paths.runtime_dir / f"session-{suffix}.json"


def new_session(paths: AppPaths | None = None) -> SessionState:
    resolved = paths or resolve_paths()
    ensure_private_directory(resolved.runtime_dir)
    state = SessionState(uuid.uuid4().hex)
    path = _state_path(resolved)
    path.write_text(json.dumps({"session_id": state.session_id}), encoding="utf-8")
    path.chmod(0o600)
    return state


def current_session(paths: AppPaths | None = None) -> SessionState:
    resolved = paths or resolve_paths()
    explicit = os.environ.get("KALI_COPILOT_SESSION")
    if explicit:
        return SessionState(explicit)
    path = _state_path(resolved)
    if not path.exists():
        return new_session(resolved)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["session_id"]
    except (OSError, ValueError, KeyError, TypeError):
        return new_session(resolved)
    return SessionState(str(value))


def clear_session(paths: AppPaths | None = None) -> SessionState:
    return new_session(paths)
