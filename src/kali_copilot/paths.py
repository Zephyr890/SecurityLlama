"""XDG path resolution and private-directory creation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    runtime_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def scopes_dir(self) -> Path:
        return self.config_dir / "scopes"

    @property
    def active_scope_file(self) -> Path:
        return self.config_dir / "active-scope"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "sessions.db"

    @property
    def proposals_dir(self) -> Path:
        return self.runtime_dir / "proposals"

    @property
    def attachments_dir(self) -> Path:
        return self.runtime_dir / "attachments"


def resolve_paths(environ: dict[str, str] | None = None) -> AppPaths:
    """Resolve paths using only the documented environment variables."""
    env = os.environ if environ is None else environ
    home = Path(env.get("HOME", str(Path.home())))
    config_base = Path(
        env.get("SECURITYLLAMA_CONFIG_HOME", env.get("XDG_CONFIG_HOME", home / ".config"))
    )
    data_base = Path(
        env.get("SECURITYLLAMA_DATA_HOME", env.get("XDG_DATA_HOME", home / ".local/share"))
    )
    cache_base = Path(env.get("XDG_CACHE_HOME", home / ".cache"))
    runtime_default = Path("/tmp") / f"securityllama-{os.getuid()}"  # noqa: S108
    runtime_base = Path(env.get("XDG_RUNTIME_DIR", runtime_default))
    config_dir = (
        config_base if "SECURITYLLAMA_CONFIG_HOME" in env else config_base / "securityllama"
    )
    data_dir = data_base if "SECURITYLLAMA_DATA_HOME" in env else data_base / "securityllama"
    return AppPaths(config_dir, data_dir, cache_base / "securityllama", runtime_base)


def ensure_private_directory(path: Path) -> None:
    """Create a directory and conservatively enforce owner-only permissions."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
