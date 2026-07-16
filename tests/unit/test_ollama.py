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
    response_format = requests[0]["format"]
    assert response_format["type"] == "object"
    assert response_format["additionalProperties"] is False
    assert "active_scope" not in response_format["properties"]
    assert "answer" in response_format["required"]
    messages = requests[0]["messages"]
    assert isinstance(messages, list)
    assert "untrusted output" not in messages[0]["content"]
    assert "RESPONSE_SCHEMA_JSON=" in messages[0]["content"]
    assert "INPUT_ONLY_UNTRUSTED_CONTEXT_JSON_BEGIN" in messages[1]["content"]
    assert "Do not echo or summarize the context object" in messages[1]["content"]
    assert "proposed_command" in messages[1]["content"]


def test_schema_rejection_falls_back_to_json_mode() -> None:
    formats: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        body = json.loads(request.content)
        formats.append(body["format"])
        if len(formats) == 1:
            return httpx.Response(400, json={"error": "schema unsupported"})
        return httpx.Response(200, json={"message": {"content": valid_content()}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    result = OllamaClient(config, httpx.MockTransport(handler)).chat(packet())

    assert result.answer.startswith("Because")
    assert isinstance(formats[0], dict)
    assert formats[1] == "json"


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


def test_wrapped_json_is_validated_without_repair() -> None:
    chat_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_calls
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        chat_calls += 1
        wrapped = "Here is the JSON:\n```json\n" + valid_content() + "\n```"
        return httpx.Response(200, json={"message": {"content": wrapped}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    result = OllamaClient(config, httpx.MockTransport(handler)).chat(packet())

    assert result.answer.startswith("Because")
    assert chat_calls == 1


def test_missing_answer_uses_valid_command_explanation_without_repair() -> None:
    chat_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_calls
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        chat_calls += 1
        content = json.dumps(
            {
                "schema_version": "1",
                "proposed_command": "nikto -h <target_url> -o /tmp/nikto.txt -Format txt",
                "command_explanation": "Runs Nikto and writes text output to the requested file.",
                "risk": "medium",
                "requires_root": False,
                "network_effect": "active",
            }
        )
        return httpx.Response(200, json={"message": {"content": content}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    result = OllamaClient(config, httpx.MockTransport(handler)).chat(packet())

    assert result.answer == "Runs Nikto and writes text output to the requested file."
    assert result.proposed_command.startswith("nikto ")
    assert result.command_explanation is None
    assert chat_calls == 1


def test_context_echo_uses_fresh_compact_repair() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            content = (
                '{"active_scope":null,"capture_truncated":false,'
                '"conversation_summary":"","recent_turns":[],"session_id":"test"'
            )
        else:
            content = valid_content()
        return httpx.Response(200, json={"message": {"content": content}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    result = OllamaClient(config, httpx.MockTransport(handler)).chat(packet())

    assert result.answer.startswith("Because")
    repair_messages = requests[1]["messages"]
    assert [message["role"] for message in repair_messages] == ["system", "user"]
    repair_input = repair_messages[1]["content"]
    assert "CONTEXT_ECHO_DETECTED" in repair_input
    assert 'OPERATOR_QUESTION_JSON="why?"' in repair_input
    assert '"active_scope":' not in repair_input
    assert '"session_id":' not in repair_input


def test_invalid_json_gets_exactly_one_repair() -> None:
    chat_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_calls
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        chat_calls += 1
        return httpx.Response(
            200,
            json={
                "message": {"content": "api_key=abcdefghijklmnop {bad"},
                "done": True,
                "done_reason": "length",
                "prompt_eval_count": 400,
                "eval_count": 256,
            },
        )

    config = AppConfig(ollama=OllamaConfig(model="fixture-model"))
    with pytest.raises(InvalidModelResponseError) as captured:
        OllamaClient(config, httpx.MockTransport(handler)).chat(packet())
    assert chat_calls == 2
    report = captured.value.debug_report()
    assert "done_reason='length'" in report
    assert "eval_count=256" in report
    assert "abcdefghijklmnop" not in report
    assert "[REDACTED:token_assignment]" in report


def test_missing_answer_repair_retains_request_and_ends_with_instruction() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fixture-model"}]})
        body = json.loads(request.content)
        requests.append(body)
        content = json.dumps({"schema_version": "1"}) if len(requests) == 1 else valid_content()
        return httpx.Response(200, json={"message": {"content": content}})

    config = AppConfig(ollama=OllamaConfig(model="fixture-model", num_predict=256))
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
    assert requests[0]["options"]["num_predict"] == 256
    assert requests[1]["options"]["num_predict"] == 512
