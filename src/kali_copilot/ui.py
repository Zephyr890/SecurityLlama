"""Safe response rendering."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from kali_copilot.models import AssistantResponse
from kali_copilot.sanitize import sanitize_for_display


def render_response(response: AssistantResponse, *, console: Console | None = None) -> None:
    """Render validated response fields without interpreting command markup."""
    output = console or Console()
    output.print(sanitize_for_display(response.answer), markup=False)
    if response.findings:
        output.print("\nRanked findings", style="bold")
        for index, finding in enumerate(response.findings, start=1):
            output.print(f"  {index}. {sanitize_for_display(finding)}", markup=False)
    if response.assumptions:
        output.print("\nAssumptions", style="bold")
        for assumption in response.assumptions:
            output.print(f"  - {sanitize_for_display(assumption)}", markup=False)
    if response.warnings:
        output.print("\nWarnings", style="bold yellow")
        for warning in response.warnings:
            output.print(f"  - {sanitize_for_display(warning)}", style="yellow", markup=False)
    if response.proposed_command is not None:
        command = Text(
            sanitize_for_display(response.proposed_command), overflow="fold", no_wrap=False
        )
        output.print(Panel(command, title="PROPOSED COMMAND — NOT EXECUTED", border_style="cyan"))
        if response.command_explanation:
            output.print(sanitize_for_display(response.command_explanation), markup=False)
    output.print(
        f"Risk: {response.risk} | Network effect: {response.network_effect} | "
        f"Requires root: {response.requires_root}"
    )
