"""Private, expiring proposal handoff between the cockpit and shell editors."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from kali_copilot.models import AssistantResponse, PendingProposal, PolicyAssessment
from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths
from kali_copilot.shell_bridge import ShellBridgeError, write_private_json
from kali_copilot.tmux import validate_pane_id


def _proposal_path(paths: AppPaths, session_id: str, pane_id: str) -> Path:
    pane = validate_pane_id(pane_id)
    key = hashlib.sha256(f"{session_id}\0{pane}".encode()).hexdigest()[:32]
    return paths.proposals_dir / f"{key}.json"


def stage_proposal(
    response: AssistantResponse,
    assessment: PolicyAssessment,
    *,
    session_id: str,
    pane_id: str,
    ttl_seconds: int,
    interaction_id: str | None = None,
    paths: AppPaths | None = None,
) -> PendingProposal:
    """Stage validated inert text for later explicit consumption by one shell."""
    if response.proposed_command is None or not assessment.insertion_allowed:
        raise ShellBridgeError("proposal is not eligible for shell insertion")
    resolved = paths or resolve_paths()
    ensure_private_directory(resolved.proposals_dir)
    now = datetime.now(UTC)
    pending = PendingProposal(
        proposal_id=uuid.uuid4().hex,
        interaction_id=interaction_id,
        session_id=session_id,
        pane_id=validate_pane_id(pane_id),
        command=response.proposed_command,
        explanation=response.command_explanation,
        risk=response.risk,
        scope_status=assessment.scope_status,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    path = _proposal_path(resolved, session_id, pane_id)
    write_private_json(path, pending.model_dump_json())
    return pending


def consume_proposal(
    *, session_id: str, pane_id: str, paths: AppPaths | None = None
) -> PendingProposal | None:
    """Read and remove a proposal; expired or malformed handoffs are discarded."""
    resolved = paths or resolve_paths()
    path = _proposal_path(resolved, session_id, pane_id)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ShellBridgeError(f"cannot inspect pending proposal: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ShellBridgeError("pending proposal must be a private regular file owned by the user")
    try:
        pending = PendingProposal.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        path.unlink(missing_ok=True)
        raise ShellBridgeError(f"invalid pending proposal: {exc}") from exc
    path.unlink(missing_ok=True)
    if pending.session_id != session_id or pending.pane_id != validate_pane_id(pane_id):
        raise ShellBridgeError("pending proposal does not match this shell session and pane")
    if pending.expires_at <= datetime.now(UTC):
        return None
    return pending
