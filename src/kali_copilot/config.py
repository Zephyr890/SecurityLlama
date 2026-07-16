"""Validated application configuration with TOML and environment overrides."""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OllamaConfig(StrictModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5-coder:3b"
    think: bool = False
    connect_timeout_seconds: float = Field(3.0, gt=0, le=60)
    response_timeout_seconds: float = Field(120.0, gt=0, le=600)
    num_ctx: int = Field(4096, ge=512, le=131072)
    num_predict: int = Field(768, ge=1, le=8192)
    temperature: float = Field(0.2, ge=0, le=2)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("must be an http(s) URL with a hostname")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("credentials, query strings, and fragments are not allowed")
        return value.rstrip("/")


class TunnelConfig(StrictModel):
    ssh_user: str = ""
    ssh_host: str = ""
    local_port: int = Field(11434, ge=1024, le=65535)
    remote_host: str = "127.0.0.1"
    remote_port: int = Field(11434, ge=1, le=65535)


class ContextConfig(StrictModel):
    max_capture_lines: int = Field(200, ge=1, le=5000)
    max_capture_bytes: int = Field(65536, ge=1024, le=1_048_576)
    max_question_chars: int = Field(4000, ge=1, le=20000)
    recent_turns: int = Field(4, ge=0, le=20)
    summary_trigger_turns: int = Field(8, ge=2, le=100)
    summary_max_chars: int = Field(1200, ge=100, le=10000)


class PrivacyConfig(StrictModel):
    redact_secrets: bool = True
    store_raw_context: bool = False
    allow_public_endpoint: bool = False
    allow_insecure_tls: bool = False


class PolicyConfig(StrictModel):
    require_scope_for_network_insert: bool = True
    allow_out_of_scope_insert: bool = False
    require_second_confirmation_for_high_risk: bool = True


class UIConfig(StrictModel):
    popup_width_percent: int = Field(92, ge=30, le=100)
    popup_height_percent: int = Field(85, ge=30, le=100)
    shell_hotkey: str = "alt-a"
    tmux_binding: str = "A"


class AuditConfig(StrictModel):
    enabled: bool = True
    retention_days: int = Field(90, ge=1, le=3650)


class AppConfig(StrictModel):
    ollama: OllamaConfig = OllamaConfig()
    tunnel: TunnelConfig = TunnelConfig()
    context: ContextConfig = ContextConfig()
    privacy: PrivacyConfig = PrivacyConfig()
    policy: PolicyConfig = PolicyConfig()
    ui: UIConfig = UIConfig()
    audit: AuditConfig = AuditConfig()


class ConfigError(ValueError):
    """Configuration cannot be loaded safely."""


def _is_public_host(hostname: str) -> bool:
    if hostname in {"localhost", "localhost.localdomain"}:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (address.is_loopback or address.is_private)


def load_config(paths: AppPaths | None = None, environ: dict[str, str] | None = None) -> AppConfig:
    """Load configuration, then apply the documented environment overrides."""
    resolved = paths or resolve_paths(environ)
    env = os.environ if environ is None else environ
    data: dict[str, Any] = {}
    if resolved.config_file.exists():
        try:
            data = tomllib.loads(resolved.config_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read {resolved.config_file}: {exc}") from exc
    ollama = data.setdefault("ollama", {})
    if "SECURITYLLAMA_OLLAMA_URL" in env:
        ollama["base_url"] = env["SECURITYLLAMA_OLLAMA_URL"]
    if "SECURITYLLAMA_MODEL" in env:
        ollama["model"] = env["SECURITYLLAMA_MODEL"]
    try:
        config = AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
    host = urlsplit(config.ollama.base_url).hostname or ""
    if _is_public_host(host) and not config.privacy.allow_public_endpoint:
        raise ConfigError(
            "public Ollama endpoint rejected; use a loopback/private URL or explicitly allow it"
        )
    if config.ollama.base_url.startswith("https://") and config.privacy.allow_insecure_tls:
        return config
    return config


def initialize_config(paths: AppPaths | None = None) -> Path:
    """Copy the packaged example when no configuration exists."""
    resolved = paths or resolve_paths()
    ensure_private_directory(resolved.config_dir)
    if not resolved.config_file.exists():
        example = Path(__file__).resolve().parents[2] / "config" / "config.example.toml"
        if not example.exists():
            example = (
                Path(sys.prefix) / "share" / "securityllama" / "config" / "config.example.toml"
            )
        shutil.copyfile(example, resolved.config_file)
        resolved.config_file.chmod(0o600)
    return resolved.config_file


def update_ollama_fields(
    *,
    base_url: str | None = None,
    model: str | None = None,
    think: bool | None = None,
    paths: AppPaths | None = None,
) -> Path:
    """Update only explicitly supplied Ollama fields while preserving the TOML file."""
    resolved = paths or resolve_paths()
    path = initialize_config(resolved)
    if base_url is not None:
        OllamaConfig(base_url=base_url)
    if model is not None and not model.strip():
        raise ConfigError("model name cannot be empty")
    lines = path.read_text(encoding="utf-8").splitlines()
    section = ""
    replacements = {
        key: value
        for key, value in {"base_url": base_url, "model": model, "think": think}.items()
        if value is not None
    }
    found: set[str] = set()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
        if section == "ollama" and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in replacements:
                lines[index] = f"{key} = {json.dumps(replacements[key])}"
                found.add(key)
    if found != replacements.keys():
        raise ConfigError("configuration is missing the expected [ollama] fields")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    load_config(resolved)
    return path


def update_tunnel_fields(
    *,
    ssh_user: str,
    ssh_host: str,
    local_port: int = 11434,
    remote_host: str = "127.0.0.1",
    remote_port: int = 11434,
    paths: AppPaths | None = None,
) -> Path:
    """Update the operator-managed SSH tunnel settings."""
    resolved = paths or resolve_paths()
    path = initialize_config(resolved)
    tunnel = TunnelConfig(
        ssh_user=ssh_user.strip(),
        ssh_host=ssh_host.strip(),
        local_port=local_port,
        remote_host=remote_host.strip(),
        remote_port=remote_port,
    )
    if not tunnel.ssh_user or not tunnel.ssh_host:
        raise ConfigError("SSH username and host cannot be empty")
    lines = path.read_text(encoding="utf-8").splitlines()
    section = ""
    tunnel_section_seen = False
    replacements = {
        "ssh_user": tunnel.ssh_user,
        "ssh_host": tunnel.ssh_host,
        "local_port": tunnel.local_port,
        "remote_host": tunnel.remote_host,
        "remote_port": tunnel.remote_port,
    }
    found: set[str] = set()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            tunnel_section_seen = tunnel_section_seen or section == "tunnel"
        if section == "tunnel" and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in replacements:
                lines[index] = f"{key} = {json.dumps(replacements[key])}"
                found.add(key)
    if not tunnel_section_seen:
        lines.extend(
            [
                "",
                "[tunnel]",
                f"ssh_user = {json.dumps(tunnel.ssh_user)}",
                f"ssh_host = {json.dumps(tunnel.ssh_host)}",
                f"local_port = {tunnel.local_port}",
                f"remote_host = {json.dumps(tunnel.remote_host)}",
                f"remote_port = {tunnel.remote_port}",
            ]
        )
    elif found != replacements.keys():
        raise ConfigError("configuration is missing the expected [tunnel] fields")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    load_config(resolved)
    return path
