"""Idempotent desktop-console installation and legacy shell cleanup."""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from kali_copilot.paths import AppPaths, resolve_paths

BEGIN = "# >>> securityllama managed block >>>"
END = "# <<< securityllama managed block <<<"
LEGACY_BEGIN = "# >>> kali-copilot managed block >>>"
LEGACY_END = "# <<< kali-copilot managed block <<<"
DESKTOP_FILENAME = "securityllama-console.desktop"


class InstallError(RuntimeError):
    """The console launcher could not be installed safely."""


def _installed_executable() -> str | None:
    """Return a stable absolute path to the invoking SecurityLlama entry point."""
    executable = shutil.which("securityllama")
    sibling = Path(sys.executable).with_name("securityllama")
    if executable is None and sibling.is_file():
        executable = str(sibling)
    if executable is None:
        return None
    # Preserve a stable pipx shim instead of following its symlink into a venv
    # that may be replaced during upgrades.
    return os.path.abspath(Path(executable).expanduser())


def desktop_launcher_path(home: Path | None = None, environ: dict[str, str] | None = None) -> Path:
    """Return the XDG application-launcher path without creating it."""
    env = os.environ if environ is None else environ
    user_home = home or Path(env.get("HOME", str(Path.home())))
    data_home = Path(env.get("XDG_DATA_HOME", user_home / ".local/share"))
    return data_home / "applications" / DESKTOP_FILENAME


def _desktop_exec_argument(value: str) -> str:
    if not value or any(char in value for char in ("\n", "\r", "\x00")):
        raise InstallError("SecurityLlama executable path is invalid")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`")
    escaped = escaped.replace("$", "\\$")
    escaped = escaped.replace("%", "%%")
    return f'"{escaped}"'


def _desktop_content(executable: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Version=1.0
Name=SecurityLlama Console
Comment=Human-in-the-loop Ollama terminal console
Exec={_desktop_exec_argument(executable)} console
Icon=utilities-terminal
Terminal=true
Categories=System;Security;
StartupNotify=true
"""


def _remove_managed_block(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    leading_block = text.startswith(BEGIN) or text.startswith(LEGACY_BEGIN)
    updated = text
    for begin_marker, end_marker in ((BEGIN, END), (LEGACY_BEGIN, LEGACY_END)):
        while True:
            start = updated.find(begin_marker)
            end = updated.find(end_marker, start + len(begin_marker)) if start >= 0 else -1
            if start < 0 or end < 0:
                break
            updated = updated[:start] + updated[end + len(end_marker) :]
    if updated == text:
        return
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.securityllama-backup-{timestamp}")
    shutil.copy2(path, backup)
    path.write_text(updated.lstrip("\n") if leading_block else updated, encoding="utf-8")


def remove_shell_blocks(home: Path | None = None) -> None:
    """Remove obsolete SecurityLlama shell and tmux source blocks."""
    user_home = home or Path.home()
    for path in (user_home / ".zshrc", user_home / ".bashrc", user_home / ".tmux.conf"):
        _remove_managed_block(path)


def _remove_generated_shell_assets(paths: AppPaths) -> None:
    directory = paths.config_dir / "shell"
    for name in ("securityllama.zsh", "securityllama.bash", "securityllama.tmux.conf"):
        target = directory / name
        if target.is_file() or target.is_symlink():
            target.unlink()
    with suppress(OSError):
        directory.rmdir()


def install_desktop(
    paths: AppPaths | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    """Install one terminal-enabled desktop launcher and retire old shell hooks."""
    resolved = paths or resolve_paths(environ)
    executable = _installed_executable()
    if executable is None:
        raise InstallError("securityllama executable is unavailable; reinstall with pipx")
    target = desktop_launcher_path(home, environ)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = _desktop_content(executable)
    if target.exists() and (not target.is_file() or target.is_symlink()):
        raise InstallError(f"desktop launcher must be a regular file: {target}")
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)
    remove_shell_blocks(home)
    _remove_generated_shell_assets(resolved)
    return target


def remove_desktop(home: Path | None = None, environ: dict[str, str] | None = None) -> None:
    """Remove only the generated desktop launcher."""
    target = desktop_launcher_path(home, environ)
    if target.is_symlink():
        raise InstallError(f"refusing to remove symlinked desktop launcher: {target}")
    target.unlink(missing_ok=True)


def install_shell(paths: AppPaths | None = None, home: Path | None = None) -> list[Path]:
    """Deprecated compatibility alias that installs the standalone console launcher."""
    return [install_desktop(paths, home)]
