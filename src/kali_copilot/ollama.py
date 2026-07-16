"""Ollama-compatible HTTP client with strict structured-response repair."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from kali_copilot.config import AppConfig
from kali_copilot.models import AssistantResponse, ContextPacket, ConversationTurn
from kali_copilot.prompting import SYSTEM_PROMPT, chat_messages


class OllamaError(RuntimeError):
    exit_code = 3


class ModelUnavailableError(OllamaError):
    exit_code = 4


class InvalidModelResponseError(OllamaError):
    exit_code = 5


@dataclass(frozen=True)
class HealthResult:
    reachable: bool
    message: str


class OllamaClient:
    def __init__(self, config: AppConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=config.ollama.base_url,
            timeout=httpx.Timeout(
                config.ollama.response_timeout_seconds,
                connect=config.ollama.connect_timeout_seconds,
            ),
            verify=not config.privacy.allow_insecure_tls,
            transport=transport,
        )

    def check_health(self) -> HealthResult:
        try:
            self.list_models()
        except OllamaError as exc:
            return HealthResult(False, str(exc))
        return HealthResult(True, "Ollama endpoint is reachable")

    def list_models(self) -> list[str]:
        try:
            response = self._client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
            return [
                item["name"]
                for item in payload.get("models", [])
                if isinstance(item.get("name"), str)
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise OllamaError(f"Ollama endpoint unavailable: {exc}") from exc

    def _post_chat(self, messages: list[dict[str, str]]) -> str:
        body: dict[str, Any] = {
            "model": self.config.ollama.model,
            "stream": False,
            "format": AssistantResponse.model_json_schema(),
            "messages": messages,
            "options": {
                "num_ctx": self.config.ollama.num_ctx,
                "num_predict": self.config.ollama.num_predict,
                "temperature": self.config.ollama.temperature,
            },
        }
        try:
            response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            return str(response.json()["message"]["content"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise OllamaError(f"Ollama chat request failed: {exc}") from exc

    def chat(self, packet: ContextPacket) -> AssistantResponse:
        if self.config.ollama.model not in self.list_models():
            raise ModelUnavailableError(
                f"configured model is unavailable: {self.config.ollama.model}"
            )
        messages = chat_messages(packet)
        content = self._post_chat(messages)
        try:
            return AssistantResponse.model_validate_json(content)
        except ValidationError as first_error:
            repair = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Repair the previous JSON using only these validation errors: "
                    + json.dumps(first_error.errors(), default=str),
                },
                {"role": "assistant", "content": content},
            ]
            repaired = self._post_chat(repair)
            try:
                return AssistantResponse.model_validate_json(repaired)
            except ValidationError as exc:
                raise InvalidModelResponseError(
                    "model returned invalid structured JSON after one repair"
                ) from exc

    def summarize(self, previous_summary: str, turns: list[ConversationTurn]) -> str:
        """Produce a bounded factual summary; full memory support arrives in Milestone 4."""
        data = json.dumps(
            {"previous_summary": previous_summary, "turns": [turn.model_dump() for turn in turns]}
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Summarize facts, hypotheses, unresolved questions, targets, and evidence. "
                    "Do not propose commands."
                ),
            },
            {"role": "user", "content": f"UNTRUSTED_CONTEXT_DATA\n{data}"},
        ]
        return self._post_chat(messages)[: self.config.context.summary_max_chars]
