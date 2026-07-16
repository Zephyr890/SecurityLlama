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
    messages = requests[0]["messages"]
    assert isinstance(messages, list)
    assert "untrusted output" not in messages[0]["content"]
    assert "UNTRUSTED_CONTEXT_DATA" in messages[1]["content"]


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
