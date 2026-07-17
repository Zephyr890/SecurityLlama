"""Independent diagnostics with actionable remediation."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from kali_copilot.audit import AuditStore
from kali_copilot.clipboard import clipboard_provider
from kali_copilot.config import ConfigError, load_config
from kali_copilot.install import desktop_launcher_path
from kali_copilot.ollama import OllamaClient, OllamaError
from kali_copilot.paths import resolve_paths
from kali_copilot.scope import ScopeError, active_scope


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    passed: bool
    message: str
    required: bool = True


def _private(path: Path) -> bool:
    if not path.exists():
        return True
    info = path.stat()
    return info.st_uid == os.getuid() and not (stat.S_IMODE(info.st_mode) & 0o077)


def run_doctor() -> list[DoctorCheck]:
    paths = resolve_paths()
    checks: list[DoctorCheck] = []
    if not paths.config_file.is_file():
        checks.append(
            DoctorCheck(
                "configuration",
                False,
                f"missing {paths.config_file}; run `securityllama config init`",
            )
        )
        return checks
    try:
        config = load_config(paths)
        checks.append(DoctorCheck("configuration", True, f"valid: {paths.config_file}"))
    except ConfigError as exc:
        checks.append(
            DoctorCheck("configuration", False, f"run `securityllama config init`: {exc}")
        )
        return checks
    private = all(_private(path) for path in (paths.config_dir, paths.data_dir, paths.runtime_dir))
    checks.append(
        DoctorCheck(
            "permissions",
            private,
            "private directories are owner-only"
            if private
            else "run chmod 700 on securityllama private directories",
        )
    )
    launcher = desktop_launcher_path()
    launcher_ok = launcher.is_file() and not launcher.is_symlink()
    checks.append(
        DoctorCheck(
            "console launcher",
            launcher_ok,
            f"installed: {launcher}"
            if launcher_ok
            else "run `securityllama install-desktop` or `securityllama console` directly",
            required=False,
        )
    )
    provider = clipboard_provider()
    checks.append(
        DoctorCheck(
            "clipboard",
            provider is not None,
            f"proposal copy available through {provider.name}"
            if provider
            else "install xclip on Kali; chat remains usable but /copy is unavailable",
            required=False,
        )
    )
    client = OllamaClient(config)
    try:
        models = client.list_models()
        checks.append(DoctorCheck("endpoint", True, "Ollama endpoint reachable"))
        model_ok = config.ollama.model in models
        checks.append(
            DoctorCheck(
                "model",
                model_ok,
                "configured model available"
                if model_ok
                else f"install model {config.ollama.model}",
            )
        )
    except OllamaError as exc:
        checks.append(DoctorCheck("endpoint", False, str(exc)))
    try:
        scope = active_scope(paths)
        checks.append(
            DoctorCheck(
                "scope",
                True,
                scope.name if scope else "none (network insertion will be restricted)",
                required=False,
            )
        )
    except ScopeError as exc:
        checks.append(DoctorCheck("scope", False, str(exc), required=False))
    try:
        with AuditStore(paths.database_file):
            pass
        checks.append(DoctorCheck("audit", True, f"writable: {paths.database_file}"))
    except (OSError, RuntimeError) as exc:
        checks.append(DoctorCheck("audit", False, f"cannot initialize audit database: {exc}"))
    return checks
