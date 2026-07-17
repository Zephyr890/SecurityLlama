from __future__ import annotations

import io

from rich.console import Console

from kali_copilot.models import AssistantResponse
from kali_copilot.ui import render_command_diff, render_response


def test_response_lists_are_rendered_on_separate_lines() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=120)
    response = AssistantResponse(
        answer="No confirmed high-severity issue was identified.",
        findings=[
            "MEDIUM — BREACH lead: possible response compression side channel; validate",
            "INFO — Vercel headers: limited infrastructure disclosure; confirmed header",
        ],
        assumptions=["The supplied output is complete."],
        warnings=["Scanner findings require manual validation."],
    )

    render_response(response, console=console)
    rendered = stream.getvalue()

    assert "Ranked findings\n  1. MEDIUM — BREACH lead" in rendered
    assert "\n  2. INFO — Vercel headers" in rendered
    assert "Assumptions\n  - The supplied output is complete." in rendered
    assert "Warnings\n  - Scanner findings require manual validation." in rendered


def test_command_diff_is_inert_and_clear() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=120)
    render_command_diff("curl old", "curl new", console=console)
    rendered = stream.getvalue()
    assert "Editable-buffer change" in rendered
    assert "- curl old" in rendered
    assert "+ curl new" in rendered
