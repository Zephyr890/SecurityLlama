"""Session-scoped, runtime-only references to explicitly attached text files."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from kali_copilot.models import AttachmentRef, AttachmentState, RedactionRecord
from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths
from kali_copilot.sanitize import normalize_text, redact_secrets, strip_terminal_sequences


class AttachmentError(RuntimeError):
    """An attachment cannot be safely registered or read."""


@dataclass(frozen=True)
class AttachmentBundle:
    text: str
    attachments: list[AttachmentRef]
    redactions: list[RedactionRecord]
    truncated: bool
    original_bytes: int


def _state_path(paths: AppPaths, session_id: str) -> Path:
    key = hashlib.sha256(session_id.encode()).hexdigest()[:32]
    return paths.attachments_dir / f"{key}.json"


def _absolute_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return Path(os.path.abspath(path))


def _open_regular(path: Path) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AttachmentError(f"cannot open attachment {path}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
    except OSError as exc:
        os.close(descriptor)
        raise AttachmentError(f"cannot inspect attachment {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        raise AttachmentError(f"attachment must be a regular file: {path}")
    return descriptor, info


def load_attachment_state(session_id: str, paths: AppPaths | None = None) -> AttachmentState:
    resolved = paths or resolve_paths()
    path = _state_path(resolved, session_id)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return AttachmentState(session_id=session_id)
    except OSError as exc:
        raise AttachmentError(f"cannot inspect attachment state: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise AttachmentError("attachment state must be a private regular file owned by the user")
    try:
        state = AttachmentState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise AttachmentError(f"invalid attachment state: {exc}") from exc
    if state.session_id != session_id:
        raise AttachmentError("attachment state does not match the current session")
    return state


def _write_state(state: AttachmentState, paths: AppPaths) -> None:
    ensure_private_directory(paths.attachments_dir)
    path = _state_path(paths, state.session_id)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(state.model_dump_json())
    except OSError as exc:
        raise AttachmentError(f"cannot write attachment state: {exc}") from exc


def attach_file(
    session_id: str,
    file_path: str | Path,
    *,
    max_files: int,
    max_file_bytes: int,
    paths: AppPaths | None = None,
) -> AttachmentRef:
    """Register one stable regular-file identity without storing its contents."""
    resolved = paths or resolve_paths()
    path = _absolute_path(file_path)
    descriptor, info = _open_regular(path)
    os.close(descriptor)
    if info.st_size > max_file_bytes:
        raise AttachmentError(
            f"attachment is {info.st_size} bytes; context.max_attachment_file_bytes "
            f"allows {max_file_bytes}"
        )
    state = load_attachment_state(session_id, resolved)
    path_text = str(path)
    for existing in state.attachments:
        if existing.path == path_text:
            return existing
    if len(state.attachments) >= max_files:
        raise AttachmentError(f"session already has the maximum of {max_files} attachments")
    reference = AttachmentRef(
        path=path_text,
        device=info.st_dev,
        inode=info.st_ino,
        added_at=datetime.now(UTC),
    )
    _write_state(
        state.model_copy(update={"attachments": [*state.attachments, reference]}), resolved
    )
    return reference


def detach_file(session_id: str, file_path: str | Path, paths: AppPaths | None = None) -> bool:
    resolved = paths or resolve_paths()
    state = load_attachment_state(session_id, resolved)
    path_text = str(_absolute_path(file_path))
    retained = [item for item in state.attachments if item.path != path_text]
    if len(retained) == len(state.attachments):
        return False
    _write_state(state.model_copy(update={"attachments": retained}), resolved)
    return True


def clear_attachments(session_id: str, paths: AppPaths | None = None) -> int:
    resolved = paths or resolve_paths()
    state = load_attachment_state(session_id, resolved)
    _state_path(resolved, session_id).unlink(missing_ok=True)
    return len(state.attachments)


def merge_redactions(records: list[RedactionRecord]) -> list[RedactionRecord]:
    totals: dict[str, int] = {}
    for record in records:
        totals[record.category] = totals.get(record.category, 0) + record.count
    return [
        RedactionRecord(category=category, count=min(count, 10000))
        for category, count in sorted(totals.items())
    ]


def read_attachments(
    session_id: str,
    *,
    max_file_bytes: int,
    paths: AppPaths | None = None,
) -> AttachmentBundle:
    """Re-read attached text, rejecting replaced files and binary NUL content."""
    resolved = paths or resolve_paths()
    state = load_attachment_state(session_id, resolved)
    sections: list[str] = []
    records: list[RedactionRecord] = []
    truncated = False
    original_bytes = 0
    for reference in state.attachments:
        path = Path(reference.path)
        descriptor, info = _open_regular(path)
        try:
            if info.st_dev != reference.device or info.st_ino != reference.inode:
                raise AttachmentError(
                    f"attachment was replaced; detach and reattach it before use: {path}"
                )
            with os.fdopen(descriptor, "rb") as handle:
                raw = handle.read(max_file_bytes + 1)
                descriptor = -1
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        original_bytes += info.st_size
        if len(raw) > max_file_bytes:
            raw = raw[:max_file_bytes]
            truncated = True
        if b"\x00" in raw:
            raise AttachmentError(
                f"binary attachment containing NUL bytes is not supported: {path}"
            )
        decoded = raw.decode("utf-8", errors="replace")
        cleaned = normalize_text(strip_terminal_sequences(decoded))
        redacted = redact_secrets(cleaned)
        records.extend(redacted.records)
        safe_path = redact_secrets(strip_terminal_sequences(str(path))).text
        sections.append(
            "ATTACHMENT_BEGIN "
            + json.dumps(safe_path, ensure_ascii=True)
            + "\n"
            + redacted.text
            + "\nATTACHMENT_END "
            + json.dumps(safe_path, ensure_ascii=True)
        )
    return AttachmentBundle(
        text="\n\n".join(sections),
        attachments=state.attachments,
        redactions=merge_redactions(records),
        truncated=truncated,
        original_bytes=original_bytes,
    )
