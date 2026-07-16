"""Operator-maintained engagement scope files and active-scope selection."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kali_copilot.models import ScopeSummary
from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class ScopeError(ValueError):
    pass


class ScopeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=64)
    authorized: bool = False
    allowed_cidrs: list[str] = Field(default_factory=list, max_length=100)
    allowed_domains: list[str] = Field(default_factory=list, max_length=100)
    permissions: list[str] = Field(default_factory=list, max_length=50)
    denied_categories: list[str] = Field(default_factory=list, max_length=50)

    def summary(self) -> ScopeSummary:
        return ScopeSummary(**self.model_dump())


def validate_name(name: str) -> str:
    if not NAME_PATTERN.fullmatch(name):
        raise ScopeError("scope name may contain only letters, numbers, dot, underscore, and dash")
    return name


def scope_path(name: str, paths: AppPaths | None = None) -> Path:
    resolved = paths or resolve_paths()
    return resolved.scopes_dir / f"{validate_name(name)}.toml"


def initialize_scope(name: str, authorized: bool = False, paths: AppPaths | None = None) -> Path:
    resolved = paths or resolve_paths()
    path = scope_path(name, resolved)
    ensure_private_directory(resolved.config_dir)
    ensure_private_directory(resolved.scopes_dir)
    if not path.exists():
        content = (
            f'name = "{name}"\n'
            f"authorized = {'true' if authorized else 'false'}\n"
            "allowed_cidrs = []\nallowed_domains = []\npermissions = []\n"
            'denied_categories = ["destructive_action", "persistence", "credential_attack"]\n'
        )
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    return path


def load_scope(name: str, paths: AppPaths | None = None) -> ScopeConfig:
    path = scope_path(name, paths)
    try:
        return ScopeConfig.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ScopeError(f"cannot load scope {name}: {exc}") from exc


def use_scope(name: str, paths: AppPaths | None = None) -> ScopeConfig:
    resolved = paths or resolve_paths()
    scope = load_scope(name, resolved)
    ensure_private_directory(resolved.config_dir)
    resolved.active_scope_file.write_text(name + "\n", encoding="utf-8")
    resolved.active_scope_file.chmod(0o600)
    return scope


def active_scope(
    paths: AppPaths | None = None, environ: dict[str, str] | None = None
) -> ScopeConfig | None:
    env = os.environ if environ is None else environ
    resolved = paths or resolve_paths(dict(env))
    if env.get("SECURITYLLAMA_SCOPE"):
        return load_scope(env["SECURITYLLAMA_SCOPE"], resolved)
    if not resolved.active_scope_file.exists():
        return None
    name = resolved.active_scope_file.read_text(encoding="utf-8").strip()
    return load_scope(name, resolved) if name else None
