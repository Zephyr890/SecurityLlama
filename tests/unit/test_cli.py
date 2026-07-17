from __future__ import annotations

import io
import sys

from kali_copilot import cli
from kali_copilot.config import AppConfig
from kali_copilot.ollama import ChatResult, InvalidModelResponseError


def test_empty_cli_is_safe() -> None:
    assert cli.main([]) == 0


def test_console_does_not_require_tmux(monkeypatch) -> None:
    import kali_copilot.console as console_module

    seen: dict[str, object] = {}

    class FakeConsole:
        def __init__(self, config: AppConfig) -> None:
            seen.update(config=config)

        def run(self) -> int:
            return 0

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(cli, "load_config", AppConfig)
    monkeypatch.setattr(console_module, "SecurityLlamaConsole", FakeConsole)

    assert cli.main(["console"]) == 0
    assert isinstance(seen["config"], AppConfig)


def test_debug_prints_redacted_model_response_diagnostics(monkeypatch, capsys) -> None:
    result = ChatResult(
        content="api_key=abcdefghijklmnop {bad",
        done=True,
        done_reason="length",
        prompt_eval_count=300,
        eval_count=256,
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise InvalidModelResponseError("invalid response", result, result)

    monkeypatch.setattr(cli, "load_config", lambda: AppConfig())
    monkeypatch.setattr(cli, "ask_model", fail)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    assert cli.main(["--debug", "ask", "test"]) == 5
    stderr = capsys.readouterr().err
    assert "done_reason='length'" in stderr
    assert "[REDACTED:token_assignment]" in stderr
    assert "abcdefghijklmnop" not in stderr
