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
        pane_id="%7",
        recent_output="bounded synthetic evidence",
        capture_truncated=False,
        redactions=[],
    )
    paths = resolve_paths()

    job = start_job(config, packet, None, pane_id="%7", paths=paths)
    assert job.status == "running"

    deadline = time.monotonic() + 10
    result = load_job(job.job_id, paths)
    while result.status == "running" and time.monotonic() < deadline:
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
