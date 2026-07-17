"""Redacted, human-readable session reporting."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from kali_copilot.audit import AuditStore
from kali_copilot.models import AssistantResponse, PolicyAssessment
from kali_copilot.sanitize import sanitize_for_display


def markdown_report(store: AuditStore, session_id: str) -> str:
    """Render persisted redacted meaning; raw terminal captures are never available here."""
    name = store.session_name(session_id) or session_id
    lines = [
        f"# SecurityLlama session: {sanitize_for_display(name)}",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "> Scope checks are advisory. This report contains model analysis and operator notes, "
        "not proof of authorization or confirmed findings.",
        "",
        "## Interactions",
        "",
    ]
    for item in store.session_history(session_id):
        response = AssistantResponse.model_validate_json(str(item["response_json"]))
        lines.extend(
            [
                f"### {sanitize_for_display(str(item['created_at']))} — "
                f"{sanitize_for_display(str(item['mode']))}",
                "",
                f"**Question:** {sanitize_for_display(str(item['question']))}",
                "",
                sanitize_for_display(response.answer),
                "",
            ]
        )
        if response.findings:
            lines.append("**Findings:**")
            lines.extend(
                f"{index}. {sanitize_for_display(value)}"
                for index, value in enumerate(response.findings, 1)
            )
            lines.append("")
        if response.proposed_command:
            lines.extend(
                [
                    "**Proposed command (not automatically executed):**",
                    "",
                    f"`{sanitize_for_display(response.proposed_command)}`",
                    "",
                    f"Disposition: {sanitize_for_display(str(item['disposition']))}",
                    "",
                ]
            )
        if item["policy_json"]:
            policy = PolicyAssessment.model_validate_json(str(item["policy_json"]))
            lines.extend(
                [
                    f"Risk: {policy.risk_status}; advisory scope: {policy.scope_status}",
                    "",
                ]
            )
    lines.extend(["## Operator notes", ""])
    for note in store.notes(session_id):
        marker = " ★" if bool(note["bookmarked"]) else ""
        lines.extend(
            [
                f"- {sanitize_for_display(str(note['created_at']))}{marker}: "
                f"{sanitize_for_display(str(note['body']))}"
            ]
        )
    if not store.notes(session_id):
        lines.append("No notes recorded.")
    lines.extend(["", "<!-- Raw terminal context is not stored or exported. -->", ""])
    return "\n".join(lines)


def json_report(store: AuditStore, session_id: str) -> str:
    """Render machine-readable redacted session records."""
    return json.dumps(
        {
            "session_id": session_id,
            "name": store.session_name(session_id),
            "interactions": store.session_history(session_id),
            "notes": store.notes(session_id),
            "raw_context_included": False,
        },
        indent=2,
        sort_keys=True,
    )
