"""Detached cockpit requests with private, session-scoped runtime results."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from pydantic import ValidationError

from kali_copilot.audit import AuditStore
from kali_copilot.config import AppConfig
from kali_copilot.models import AssistantResponse, BackgroundJob, ContextPacket
from kali_copilot.ollama import OllamaClient
from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths
from kali_copilot.policy import assess_proposal
from kali_copilot.sanitize import redact_secrets, strip_terminal_sequences
from kali_copilot.scope import ScopeConfig
from kali_copilot.tmux import validate_pane_id

MAX_PAYLOAD_BYTES = 2_500_000
MAX_JOB_BYTES = 2_000_000


class BackgroundJobError(RuntimeError):
    """A background request could not be started or recovered safely."""


def _job_path(paths: AppPaths, job_id: str) -> Path:
    if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
        raise BackgroundJobError("invalid background job identifier")
    return paths.jobs_dir / f"{job_id}.json"


def _safe_response(response: AssistantResponse) -> AssistantResponse:
    def clean(value: str) -> str:
        return redact_secrets(strip_terminal_sequences(value)).text

    command = clean(response.proposed_command or "") or None
    warnings = [clean(item) for item in response.warnings]
    if response.proposed_command is not None and command != response.proposed_command:
        command = None
        notice = "Proposed command omitted because it contained likely secret material."
        warnings = [*warnings[:49], notice] if len(warnings) >= 50 else [*warnings, notice]
    return response.model_copy(
        update={
            "answer": clean(response.answer)
            or "Model response contained only unsafe terminal control data.",
            "proposed_command": command,
            "command_explanation": clean(response.command_explanation or "") or None,
            "target_candidates": [clean(item) for item in response.target_candidates],
            "warnings": warnings,
            "findings": [clean(item) for item in response.findings],
            "assumptions": [clean(item) for item in response.assumptions],
        }
    )


def _write_job(job: BackgroundJob, paths: AppPaths) -> None:
    """Atomically replace one private job record without following a target symlink."""
    ensure_private_directory(paths.jobs_dir)
    path = _job_path(paths, job.job_id)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".job-", dir=paths.jobs_dir)
    temporary = Path(temporary_name)
    try:
        content = job.model_dump_json()
        if len(content.encode()) > MAX_JOB_BYTES:
            raise BackgroundJobError("background job result exceeds its local size limit")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and path.is_symlink():
            raise BackgroundJobError("background job path must not be a symlink")
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def load_job(job_id: str, paths: AppPaths | None = None) -> BackgroundJob:
    """Load one validated private job record."""
    resolved = paths or resolve_paths()
    path = _job_path(resolved, job_id)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise BackgroundJobError("background job must be a private regular file owned by you")
        if info.st_size > MAX_JOB_BYTES:
            raise BackgroundJobError("background job result exceeds its local size limit")
        return BackgroundJob.model_validate_json(path.read_text(encoding="utf-8"))
    except BackgroundJobError:
        raise
    except (OSError, UnicodeError, ValidationError) as exc:
        raise BackgroundJobError(f"cannot read background job: {exc}") from exc


def list_jobs(session_id: str, paths: AppPaths | None = None) -> list[BackgroundJob]:
    """Return valid jobs for a logical session, newest first."""
    resolved = paths or resolve_paths()
    if not resolved.jobs_dir.exists():
        return []
    jobs: list[BackgroundJob] = []
    for path in resolved.jobs_dir.glob("*.json"):
        try:
            job = load_job(path.stem, resolved)
        except BackgroundJobError:
            continue
        if job.session_id == session_id:
            jobs.append(job)
    return sorted(jobs, key=lambda item: item.created_at, reverse=True)


def mark_viewed(job: BackgroundJob, paths: AppPaths | None = None) -> BackgroundJob:
    resolved = paths or resolve_paths()
    viewed = job.model_copy(update={"viewed_at": datetime.now(UTC)})
    _write_job(viewed, resolved)
    return viewed


def _payload(config: AppConfig, packet: ContextPacket, scope: ScopeConfig | None) -> bytes:
    content = json.dumps(
        {
            "config": config.model_dump(mode="json"),
            "packet": packet.model_dump(mode="json"),
            "scope": scope.model_dump(mode="json") if scope else None,
        },
        separators=(",", ":"),
    ).encode()
    if len(content) > MAX_PAYLOAD_BYTES:
        raise BackgroundJobError("background request payload exceeds its local size limit")
    return content


def start_job(
    config: AppConfig,
    packet: ContextPacket,
    scope: ScopeConfig | None,
    *,
    pane_id: str,
    paths: AppPaths | None = None,
) -> BackgroundJob:
    """Start a detached worker; raw context crosses an anonymous pipe, never a job file."""
    resolved = paths or resolve_paths()
    job_id = uuid.uuid4().hex
    command = [sys.executable, "-m", "kali_copilot.background", "--run", job_id]
    worker_environment = dict(os.environ)
    package_root = str(Path(__file__).resolve().parents[1])
    existing_pythonpath = worker_environment.get("PYTHONPATH")
    worker_environment["PYTHONPATH"] = (
        package_root + os.pathsep + existing_pythonpath if existing_pythonpath else package_root
    )
    try:
        process = subprocess.Popen(  # noqa: S603 - static module invocation, no model data
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=worker_environment,
        )
    except OSError as exc:
        raise BackgroundJobError(f"cannot start background request: {exc}") from exc
    job = BackgroundJob(
        job_id=job_id,
        session_id=packet.session_id,
        pane_id=validate_pane_id(pane_id),
        mode=packet.mode,
        question=packet.question,
        model=config.ollama.model,
        status="running",
        pid=process.pid,
        created_at=datetime.now(UTC),
    )
    try:
        _write_job(job, resolved)
        payload = _payload(config, packet, scope)
        if process.stdin is None:
            raise BackgroundJobError("background request pipe was not created")
        process.stdin.write(payload)
        process.stdin.close()
    except Exception as exc:
        process.terminate()
        failed = job.model_copy(
            update={
                "status": "failed",
                "finished_at": datetime.now(UTC),
                "error": redact_secrets(strip_terminal_sequences(str(exc))).text[:2000],
            }
        )
        _write_job(failed, resolved)
        if isinstance(exc, BackgroundJobError):
            raise
        raise BackgroundJobError(f"cannot submit background request: {exc}") from exc
    return job


def run_job(job_id: str, raw_payload: bytes, paths: AppPaths | None = None) -> None:
    """Run one request and publish only sanitized model output and metadata."""
    resolved = paths or resolve_paths()
    job = load_job(job_id, resolved)
    started = monotonic()
    try:
        if len(raw_payload) > MAX_PAYLOAD_BYTES:
            raise BackgroundJobError("background request payload exceeds its local size limit")
        value = json.loads(raw_payload)
        config = AppConfig.model_validate(value["config"])
        packet = ContextPacket.model_validate_json(json.dumps(value["packet"]))
        scope_value = value.get("scope")
        scope = ScopeConfig.model_validate(scope_value) if scope_value is not None else None
        if packet.session_id != job.session_id or packet.question != job.question:
            raise BackgroundJobError("background request does not match its job record")
        response = _safe_response(OllamaClient(config).chat(packet))
        assessment = assess_proposal(response, scope, config.policy)
        interaction_id = None
        audit_warning = None
        if config.audit.enabled:
            try:
                with AuditStore(resolved.database_file) as store:
                    interaction_id = store.record(
                        packet,
                        response,
                        assessment,
                        endpoint_host=urlsplit(config.ollama.base_url).hostname or "unknown",
                        model=config.ollama.model,
                        duration_ms=round((monotonic() - started) * 1000),
                    )
            except Exception as exc:  # noqa: BLE001 - preserve answer if optional audit fails
                audit_warning = "Answer completed, but the local audit record failed: " + str(exc)
        completed = job.model_copy(
            update={
                "status": "completed",
                "finished_at": datetime.now(UTC),
                "response": response,
                "assessment": assessment,
                "interaction_id": interaction_id,
                "error": (
                    redact_secrets(strip_terminal_sequences(audit_warning)).text[:2000]
                    if audit_warning
                    else None
                ),
            }
        )
        _write_job(completed, resolved)
    except Exception as exc:  # noqa: BLE001 - detached worker must publish a bounded failure
        failed = job.model_copy(
            update={
                "status": "failed",
                "finished_at": datetime.now(UTC),
                "error": redact_secrets(strip_terminal_sequences(str(exc))).text[:2000],
            }
        )
        _write_job(failed, resolved)


def _main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--run":
        return 2
    payload = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
    run_job(sys.argv[2], payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
