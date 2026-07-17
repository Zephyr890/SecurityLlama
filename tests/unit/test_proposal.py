from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kali_copilot.models import AssistantResponse, PendingProposal, PolicyAssessment
from kali_copilot.paths import AppPaths
from kali_copilot.proposal import consume_proposal, stage_proposal
from kali_copilot.shell_bridge import ShellBridgeError


def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "runtime"
    )


def response() -> AssistantResponse:
    return AssistantResponse(
        answer="Review this inert proposal.",
        proposed_command="printf safe",
        risk="low",
        network_effect="none",
    )


def assessment() -> PolicyAssessment:
    return PolicyAssessment(
        scope_status="not_applicable",
        risk_status="low",
        explicit_targets=[],
        blocked_reasons=[],
        confirmation_required=False,
        insertion_allowed=True,
    )


def test_private_proposal_is_scoped_consumed_once_and_not_executed(tmp_path: Path) -> None:
    app_paths = paths(tmp_path)
    staged = stage_proposal(
        response(),
        assessment(),
        session_id="session",
        pane_id="%2",
        ttl_seconds=60,
        paths=app_paths,
    )
    files = list(app_paths.proposals_dir.iterdir())
    assert len(files) == 1
    assert files[0].stat().st_mode & 0o777 == 0o600
    assert consume_proposal(session_id="session", pane_id="%2", paths=app_paths) == staged
    assert consume_proposal(session_id="session", pane_id="%2", paths=app_paths) is None


def test_expired_proposal_is_discarded(tmp_path: Path) -> None:
    app_paths = paths(tmp_path)
    stage_proposal(
        response(),
        assessment(),
        session_id="session",
        pane_id="%3",
        ttl_seconds=60,
        paths=app_paths,
    )
    proposal_file = next(app_paths.proposals_dir.iterdir())
    expired = PendingProposal.model_validate_json(proposal_file.read_text()).model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    proposal_file.write_text(expired.model_dump_json())
    proposal_file.chmod(0o600)
    assert consume_proposal(session_id="session", pane_id="%3", paths=app_paths) is None
    assert not proposal_file.exists()


def test_blocked_proposal_cannot_be_staged(tmp_path: Path) -> None:
    blocked = assessment().model_copy(
        update={"insertion_allowed": False, "blocked_reasons": ["outside scope"]}
    )
    with pytest.raises(ShellBridgeError, match="not eligible"):
        stage_proposal(
            response(),
            blocked,
            session_id="session",
            pane_id="%1",
            ttl_seconds=60,
            paths=paths(tmp_path),
        )
