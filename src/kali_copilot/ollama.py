"""Ollama-compatible HTTP client with strict structured-response repair."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from kali_copilot.config import AppConfig
from kali_copilot.models import AssistantResponse, ContextPacket, ConversationTurn
from kali_copilot.prompting import (
    RESPONSE_FORMAT_SCHEMA,
    chat_messages,
    context_echo_repair_messages,
    enforce_request_contract,
)
from kali_copilot.sanitize import redact_secrets, sanitize_for_display


class OllamaError(RuntimeError):
    exit_code = 3


class ModelUnavailableError(OllamaError):
    exit_code = 4


class InvalidModelResponseError(OllamaError):
    exit_code = 5

    def __init__(self, message: str, initial: ChatResult, repaired: ChatResult) -> None:
        super().__init__(message)
        self.initial = initial
        self.repaired = repaired

    def debug_report(self) -> str:
        """Return bounded, escaped, redacted diagnostics for explicit debug mode."""
        return "\n".join(
            [
                "Ollama structured-response diagnostics (model output redacted):",
                _chat_result_diagnostic("initial", self.initial),
                _chat_result_diagnostic("repair", self.repaired),
            ]
        )


@dataclass(frozen=True)
class HealthResult:
    reachable: bool
    message: str


@dataclass(frozen=True)
class ChatResult:
    content: str
    done: bool | None
    done_reason: str | None
    prompt_eval_count: int | None
    eval_count: int | None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _chat_result_diagnostic(label: str, result: ChatResult, max_chars: int = 4000) -> str:
    cleaned = redact_secrets(sanitize_for_display(result.content)).text
    truncated = len(cleaned) > max_chars
    if truncated:
        half = max_chars // 2
        cleaned = cleaned[:half] + "\n...[debug preview truncated]...\n" + cleaned[-half:]
    preview = json.dumps(cleaned, ensure_ascii=True)
    return (
        f"{label}: chars={len(result.content)} done={result.done!r} "
        f"done_reason={result.done_reason!r} prompt_eval_count={result.prompt_eval_count!r} "
        f"eval_count={result.eval_count!r} preview={preview}"
    )


def _response_error_summary(error: ValidationError | ValueError) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            ".".join(str(part) for part in item["loc"]) + " (" + item["type"] + ")"
            for item in error.errors()
        )
    return "response (json_invalid)"


def _response_object(content: str) -> dict[str, Any]:
    """Decode one JSON object, tolerating prose or Markdown around it."""
    start = content.find("{")
    if start < 0:
        raise ValueError("response contains no JSON object")
    try:
        value, _end = json.JSONDecoder().raw_decode(content[start:])
    except json.JSONDecodeError as exc:
        raise ValueError("response JSON is malformed or truncated") from exc
    if not isinstance(value, dict):
        raise ValueError("response JSON must be an object")
    return value


def _validated_response(content: str) -> AssistantResponse:
    """Validate model output and recover only safe, otherwise-complete omissions."""
    value = _response_object(content)
    if not value.get("answer"):
        explanation = value.get("command_explanation")
        command = value.get("proposed_command")
        if isinstance(explanation, str) and explanation.strip():
            value["answer"] = explanation
            value["command_explanation"] = None
        elif isinstance(command, str) and command.strip():
            value["answer"] = "Use the proposed command below as a starting point."
    return AssistantResponse.model_validate(value)


def _looks_like_context_echo(content: str) -> bool:
    markers = (
        '"active_scope"',
        '"capture_truncated"',
        '"conversation_summary"',
        '"recent_turns"',
        '"session_id"',
    )
    return sum(marker in content for marker in markers) >= 3


class OllamaClient:
    def __init__(self, config: AppConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._schema_supported: bool | None = None
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

    def _post_chat(
        self, messages: list[dict[str, str]], *, minimum_num_predict: int = 0
    ) -> ChatResult:
        use_schema = self._schema_supported is not False
        body: dict[str, Any] = {
            "model": self.config.ollama.model,
            "think": self.config.ollama.think,
            "stream": False,
            # This intentionally flat schema avoids the nested Pydantic schema
            # rejected by some Ollama releases. A 400 response falls back to
            # JSON mode for endpoint compatibility; local validation remains.
            "format": RESPONSE_FORMAT_SCHEMA if use_schema else "json",
            "messages": messages,
            "options": {
                "num_ctx": self.config.ollama.num_ctx,
                "num_predict": max(self.config.ollama.num_predict, minimum_num_predict),
                "temperature": self.config.ollama.temperature,
            },
        }
        try:
            response = self._client.post("/api/chat", json=body)
            if response.status_code == 400 and use_schema:
                self._schema_supported = False
                body["format"] = "json"
                response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            if use_schema and self._schema_supported is None:
                self._schema_supported = True
            payload = response.json()
            return ChatResult(
                content=str(payload["message"]["content"]),
                done=payload.get("done") if isinstance(payload.get("done"), bool) else None,
                done_reason=(
                    payload.get("done_reason")
                    if isinstance(payload.get("done_reason"), str)
                    else None
                ),
                prompt_eval_count=_optional_int(payload.get("prompt_eval_count")),
                eval_count=_optional_int(payload.get("eval_count")),
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise OllamaError(f"Ollama chat request failed: {exc}") from exc

    def chat(self, packet: ContextPacket) -> AssistantResponse:
        if self.config.ollama.model not in self.list_models():
            raise ModelUnavailableError(
                f"configured model is unavailable: {self.config.ollama.model}"
            )
        messages = chat_messages(packet)
        initial = self._post_chat(messages)
        try:
            return enforce_request_contract(_validated_response(initial.content), packet)
        except (ValidationError, ValueError) as first_error:
            validation_summary = _response_error_summary(first_error)
            if _looks_like_context_echo(initial.content):
                repair = context_echo_repair_messages(packet, validation_summary)
            else:
                repair = [
                    *messages,
                    {"role": "assistant", "content": initial.content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response failed schema validation. Re-answer the "
                            "original request as one complete replacement JSON object. Include a "
                            "non-empty answer field, preserve any other valid values, fix every "
                            "listed error, and return JSON only with no Markdown. Validation "
                            "errors: " + validation_summary
                        ),
                    },
                ]
            repaired = self._post_chat(repair, minimum_num_predict=512)
            try:
                return enforce_request_contract(_validated_response(repaired.content), packet)
            except (ValidationError, ValueError) as exc:
                raise InvalidModelResponseError(
                    "model returned invalid structured JSON after one repair: "
                    + _response_error_summary(exc),
                    initial,
                    repaired,
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
        return self._post_chat(messages).content[: self.config.context.summary_max_chars]
