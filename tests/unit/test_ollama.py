from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from kali_copilot.config import AppConfig, OllamaConfig
from kali_copilot.models import ContextPacket
from kali_copilot.ollama import InvalidModelResponseError, OllamaClient


def packet() -> ContextPacket:
    return ContextPacket(
        session_id="test",
        timestamp=datetime.now(UTC),
        mode="ask",
        question="why?",
        hostname="host",
        username="user",
        shell="zsh",
        cwd="/tmp",
        recent_output="untrusted output",
        capture_truncated=False,
        redactions=[],
    )


def valid_content() -> str:
    return json.dumps(
        {
            "schema_version": "1",
            "answer": "Because the handshake failed.",
            "proposed_command": None,
            "command_explanation": None,
            "risk": "none",
            "requires_root": False,
            "network_effect": "none",
            "target_candidates": [],
            "warnings": [],
            "assumptions": [],
        }
    )


def test_chat_keeps_context_out_of_system_prompt() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"message": {"content": valid_content()}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    result = OllamaClient(config, httpx.MockTransport(handler)).chat(packet())
    assert result.answer.startswith("Because")
    assert requests[0]["think"] is False
    assert requests[0]["format"] == "json"
    messages = requests[0]["messages"]
    assert isinstance(messages, list)
    assert "untrusted output" not in messages[0]["content"]
    assert "RESPONSE_SCHEMA_JSON=" in messages[0]["content"]
    assert "UNTRUSTED_CONTEXT_DATA" in messages[1]["content"]


def test_how_to_prompt_requires_actionable_command_details() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": valid_content()}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    question_packet = packet().model_copy(
        update={
            "question": (
                "Advise how to begin a Nikto scan for my web app and write results to "
                "/Desktop/test_assesment/recon"
            )
        }
    )
    OllamaClient(config, httpx.MockTransport(handler)).chat(question_packet)
    system_prompt = requests[0]["messages"][0]["content"]
    assert "Preserve explicit paths and filenames exactly" in system_prompt
    assert "proposed_command should be non-null" in system_prompt
    assert "must include requested output options" in system_prompt
    assert "network_effect=active" in system_prompt


def test_invalid_json_gets_exactly_one_repair() -> None:
    chat_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_calls
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        chat_calls += 1
        return httpx.Response(200, json={"message": {"content": "{bad"}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    with pytest.raises(InvalidModelResponseError):
        OllamaClient(config, httpx.MockTransport(handler)).chat(packet())
    assert chat_calls == 2


def test_missing_answer_repair_retains_request_and_ends_with_instruction() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        body = json.loads(request.content)
        requests.append(body)
        content = json.dumps({"schema_version": "1"}) if len(requests) == 1 else valid_content()
        return httpx.Response(200, json={"message": {"content": content}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    result = OllamaClient(config, httpx.MockTransport(handler)).chat(packet())

    assert result.answer.startswith("Because")
    repair_messages = requests[1]["messages"]
    assert [message["role"] for message in repair_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert "untrusted output" in repair_messages[1]["content"]
    assert "answer (missing)" in repair_messages[-1]["content"]
