from kali_copilot.config import PolicyConfig
from kali_copilot.models import AssistantResponse
from kali_copilot.policy import assess_proposal
from kali_copilot.scope import ScopeConfig


def response(command: str, network: str = "active") -> AssistantResponse:
    return AssistantResponse(
        answer="Review",
        proposed_command=command,
        command_explanation="Test",
        risk="low",
        requires_root=False,
        network_effect=network,  # type: ignore[arg-type]
        target_candidates=[],
        warnings=[],
        assumptions=[],
    )


def lab_scope() -> ScopeConfig:
    return ScopeConfig(
        name="lab",
        authorized=True,
        allowed_cidrs=["10.10.10.0/24"],
        allowed_domains=["*.lab.test"],
    )


def test_in_scope_and_out_of_scope_targets() -> None:
    inside = assess_proposal(response("curl https://10.10.10.25/"), lab_scope(), PolicyConfig())
    assert inside.scope_status == "in_scope"
    assert inside.insertion_allowed
    outside = assess_proposal(response("curl https://192.0.2.10/"), lab_scope(), PolicyConfig())
    assert outside.scope_status == "out_of_scope"
    assert not outside.insertion_allowed


def test_wildcard_domain_and_unknown_substitution() -> None:
    domain = assess_proposal(response("curl https://app.lab.test/"), lab_scope(), PolicyConfig())
    assert domain.scope_status == "in_scope"
    unknown = assess_proposal(response("curl https://$(target)/"), lab_scope(), PolicyConfig())
    assert unknown.scope_status == "unknown"
    assert unknown.confirmation_required


def test_local_command_does_not_require_scope() -> None:
    result = assess_proposal(response("printf hello", "none"), None, PolicyConfig())
    assert result.scope_status == "not_applicable"
    assert result.insertion_allowed


def test_network_command_without_scope_is_blocked() -> None:
    result = assess_proposal(response("curl https://example.test/"), None, PolicyConfig())
    assert result.scope_status == "no_active_scope"
    assert not result.insertion_allowed
