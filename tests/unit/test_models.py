import pytest
from pydantic import ValidationError

from kali_copilot.models import AssistantResponse


def response_data() -> dict[str, object]:
    return {
        "schema_version": "1",
        "answer": "Review complete.",
        "proposed_command": None,
        "command_explanation": None,
        "risk": "none",
        "requires_root": False,
        "network_effect": "none",
        "target_candidates": [],
        "warnings": [],
        "assumptions": [],
    }


def test_multiline_command_rejected() -> None:
    data = response_data()
    data["proposed_command"] = "id\nuname"
    with pytest.raises(ValidationError, match="single line"):
        AssistantResponse.model_validate(data)


def test_unknown_field_rejected() -> None:
    data = response_data()
    data["execute"] = True
    with pytest.raises(ValidationError):
        AssistantResponse.model_validate(data)


def test_missing_metadata_defaults_safely() -> None:
    response = AssistantResponse(answer="Review complete.")
    assert response.risk == "unknown"
    assert response.network_effect == "unknown"
    assert response.proposed_command is None
