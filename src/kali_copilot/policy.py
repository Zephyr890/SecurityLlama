"""Conservative local assessment of inert model-proposed command text."""

from __future__ import annotations

import fnmatch
import ipaddress
import re
import shlex
from typing import Literal
from urllib.parse import urlsplit

from kali_copilot.config import PolicyConfig
from kali_copilot.models import AssistantResponse, PolicyAssessment
from kali_copilot.scope import ScopeConfig

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
UNRELIABLE_RE = re.compile(r"[|;&><`$(){}\[\]\n\r]")


def _targets(command: str) -> tuple[list[str], bool]:
    unreliable = bool(UNRELIABLE_RE.search(command))
    try:
        tokens = shlex.split(command)
    except ValueError:
        return [], True
    targets: list[str] = []
    interpreters = {"bash", "sh", "zsh", "python", "python3", "perl", "ruby", "node"}
    if tokens and tokens[0].rsplit("/", 1)[-1] in interpreters:
        unreliable = True
    for token in tokens[1:]:
        candidate = token.strip("',\"")
        parsed = urlsplit(candidate)
        if parsed.scheme and parsed.hostname:
            candidate = parsed.hostname
        else:
            candidate = candidate.split("/", 1)[0]
            if candidate.count(":") == 1:
                host, port = candidate.rsplit(":", 1)
                if port.isdigit():
                    candidate = host
        try:
            ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            if DOMAIN_RE.fullmatch(candidate):
                targets.append(candidate.lower())
        else:
            targets.append(candidate)
    return list(dict.fromkeys(targets)), unreliable


def _target_allowed(target: str, scope: ScopeConfig) -> bool:
    try:
        proposed = ipaddress.ip_network(target, strict=False)
    except ValueError:
        domain = target.lower().rstrip(".")
        return any(
            fnmatch.fnmatchcase(domain, pattern.lower()) for pattern in scope.allowed_domains
        )
    for allowed_text in scope.allowed_cidrs:
        try:
            allowed = ipaddress.ip_network(allowed_text, strict=False)
        except ValueError:
            continue
        if isinstance(proposed, ipaddress.IPv4Network) and isinstance(
            allowed, ipaddress.IPv4Network
        ):
            if proposed.subnet_of(allowed):
                return True
        elif (
            isinstance(proposed, ipaddress.IPv6Network)
            and isinstance(allowed, ipaddress.IPv6Network)
            and proposed.subnet_of(allowed)
        ):
            return True
    return False


def assess_proposal(
    response: AssistantResponse, scope: ScopeConfig | None, config: PolicyConfig
) -> PolicyAssessment:
    """Assess obvious local evidence without claiming enforcement completeness."""
    command = response.proposed_command
    blocked: list[str] = []
    targets: list[str] = []
    confirmation = response.risk in {"high", "critical"}
    if command is None:
        return PolicyAssessment(
            scope_status="not_applicable",
            risk_status=response.risk,
            explicit_targets=[],
            blocked_reasons=["no proposed command"],
            confirmation_required=False,
            insertion_allowed=False,
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in command) or len(command) > 16000:
        blocked.append("command contains controls or exceeds the insertion limit")
    targets, unreliable = _targets(command)
    network = response.network_effect in {"active", "passive", "unknown"}
    if not network:
        scope_status: Literal[
            "not_applicable", "in_scope", "out_of_scope", "unknown", "no_active_scope"
        ] = "not_applicable"
    elif scope is None:
        scope_status = "no_active_scope"
        confirmation = True
        if config.require_scope_for_network_insert:
            blocked.append("network proposal requires an active engagement scope")
    elif unreliable or (network and not targets):
        scope_status = "unknown"
        confirmation = True
    elif all(_target_allowed(target, scope) for target in targets) and scope.authorized:
        scope_status = "in_scope"
    else:
        scope_status = "out_of_scope"
        confirmation = True
        if not config.allow_out_of_scope_insert:
            blocked.append("an explicit target is outside the active scope")
    return PolicyAssessment(
        scope_status=scope_status,
        risk_status=response.risk,
        explicit_targets=targets,
        blocked_reasons=blocked,
        confirmation_required=confirmation,
        insertion_allowed=not blocked,
    )
