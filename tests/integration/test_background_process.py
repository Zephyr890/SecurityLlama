from __future__ import annotations

import os
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from kali_copilot.background import load_job, start_job
from kali_copilot.config import AppConfig, AuditConfig, OllamaConfig
from kali_copilot.models import ContextPacket
from kali_copilot.paths import resolve_paths
from tests.fake_ollama import FIXTURE_MODEL, make_server


def test_detached_worker_finishes_after_submitter_returns(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("SECURITYLLAMA_DATA_HOME", str(tmp_path / "data"))
    server = make_server("127.0.0.1", 0, "success")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = AppConfig(
        ollama=OllamaConfig(base_url=f"http://127.0.0.1:{server.server_port}", model=FIXTURE_MODEL),
        audit=AuditConfig(enabled=False),
    )
    packet = ContextPacket(
        session_id="detached-session",
        timestamp=datetime.now(UTC),
        mode="ask",
        question="Explain the synthetic failure.",
        hostname="kali",
        username="operator",
        shell="zsh",
        cwd="/assessment",
        recent_output="bounded synthetic evidence",
        capture_truncated=False,
        redactions=[],
    )
    paths = resolve_paths()

    job = start_job(config, packet, None, paths=paths)
    assert job.status == "queued"

    deadline = time.monotonic() + 10
    result = load_job(job.job_id, paths)
    while result.status in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.05)
        result = load_job(job.job_id, paths)
    server.shutdown()
    thread.join(timeout=1)
    if job.pid is not None:
        with suppress(ChildProcessError):
            os.waitpid(job.pid, 0)
    result = load_job(job.job_id, paths)

    assert result.status == "completed", result.error
    assert result.response is not None
    assert "TCP connection" in result.response.answer
    assert "bounded synthetic evidence" not in (paths.jobs_dir / f"{job.job_id}.json").read_text()


def test_session_requests_are_serialized_and_refresh_conversation_memory(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("SECURITYLLAMA_DATA_HOME", str(tmp_path / "data"))
    server = make_server("127.0.0.1", 0, "timeout")
    server.RequestHandlerClass.requests_seen.clear()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = AppConfig(
        ollama=OllamaConfig(
            base_url=f"http://127.0.0.1:{server.server_port}",
            model=FIXTURE_MODEL,
            response_timeout_seconds=10,
        )
    )
    paths = resolve_paths()

    def packet(question: str) -> ContextPacket:
        return ContextPacket(
            session_id="ordered-session",
            timestamp=datetime.now(UTC),
            mode="ask",
            question=question,
            hostname="kali",
            username="operator",
            shell="zsh",
            cwd="/assessment",
            recent_output="bounded synthetic evidence",
            capture_truncated=False,
            redactions=[],
        )

    first = start_job(
        config,
        packet("FIRST_UNIQUE_QUESTION"),
        None,
        refresh_memory=True,
        paths=paths,
    )
    second = start_job(
        config,
        packet("SECOND_UNIQUE_QUESTION"),
        None,
        refresh_memory=True,
        paths=paths,
    )

    running_deadline = time.monotonic() + 2
    while load_job(first.job_id, paths).status == "queued" and time.monotonic() < running_deadline:
        time.sleep(0.05)
    assert load_job(first.job_id, paths).status == "running"
    assert load_job(second.job_id, paths).status == "queued"

    completion_deadline = time.monotonic() + 10
    results = [load_job(first.job_id, paths), load_job(second.job_id, paths)]
    while (
        any(result.status in {"queued", "running"} for result in results)
        and time.monotonic() < completion_deadline
    ):
        time.sleep(0.05)
        results = [load_job(first.job_id, paths), load_job(second.job_id, paths)]
    server.shutdown()
    thread.join(timeout=1)
    for job in (first, second):
        if job.pid is not None:
            with suppress(ChildProcessError):
                os.waitpid(job.pid, 0)

    assert [result.status for result in results] == ["completed", "completed"]
    requests = server.RequestHandlerClass.requests_seen
    assert len(requests) == 2
    first_context = requests[0]["messages"][1]["content"]
    second_context = requests[1]["messages"][1]["content"]
    assert "FIRST_UNIQUE_QUESTION" in first_context
    assert "SECOND_UNIQUE_QUESTION" in second_context
    assert "A TCP connection can fail" not in first_context
    assert "A TCP connection can fail" in second_context
