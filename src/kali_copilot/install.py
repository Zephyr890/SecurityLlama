"""Idempotent, backup-first shell integration installation."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths

BEGIN = "# >>> securityllama managed block >>>"
END = "# <<< securityllama managed block <<<"
LEGACY_BEGIN = "# >>> kali-copilot managed block >>>"
LEGACY_END = "# <<< kali-copilot managed block <<<"


def _asset_dir() -> Path:
    checkout = Path(__file__).resolve().parents[2] / "shell"
    if checkout.exists():
        return checkout
    return Path(sys.prefix) / "share" / "securityllama" / "shell"


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


def _render_asset(name: str, content: str, paths: AppPaths) -> str:
    """Apply validated UI bindings when shell assets are installed."""
    from kali_copilot.config import ConfigError, UIConfig, load_config

    try:
        ui = load_config(paths).ui
    except ConfigError:
        ui = UIConfig()
    executable = _installed_executable()
    shell_executable = shlex.quote(executable) if executable is not None else "''"
    if name == "securityllama.zsh":
        content = content.replace("'^[a'", f"'^[{ui.shell_hotkey[-1]}'")
        content = content.replace("@SECURITYLLAMA_EXECUTABLE@", shell_executable)
    elif name == "securityllama.bash":
        content = content.replace('"\\ea"', f'"\\e{ui.shell_hotkey[-1]}"')
        content = content.replace("@SECURITYLLAMA_EXECUTABLE@", shell_executable)
    elif name == "securityllama.tmux.conf":
        launcher = executable or "securityllama"
        base_command = shlex.join([launcher, "_open-chat", "--executable", launcher])
        chat_command = f"{base_command} --pane #{{q:pane_id}} --cwd #{{q:pane_current_path}}"
        escaped = (
            chat_command.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        content = content.replace("@SECURITYLLAMA_CHAT_COMMAND@", f'"{escaped}"')
        content = content.replace("bind-key A ", f"bind-key {ui.tmux_binding} ")
    return content


def _backup(path: Path) -> None:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(path, path.with_name(f"{path.name}.securityllama-backup-{timestamp}"))


def _replace_block(path: Path, body: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(BEGIN)
    end = existing.find(END, start + len(BEGIN)) if start >= 0 else -1
    block = f"{BEGIN}\n{body.rstrip()}\n{END}"
    if start >= 0 and end >= 0:
        updated = existing[:start] + block + existing[end + len(END) :]
    else:
        legacy_start = existing.find(LEGACY_BEGIN)
        legacy_end = existing.find(LEGACY_END, legacy_start + len(LEGACY_BEGIN))
        if legacy_start >= 0 and legacy_end >= 0:
            updated = existing[:legacy_start] + block + existing[legacy_end + len(LEGACY_END) :]
        else:
            separator = "" if not existing or existing.endswith("\n") else "\n"
            updated = existing + separator + block + "\n"
    if updated == existing:
        return False
    if path.exists():
        _backup(path)
    path.write_text(updated, encoding="utf-8")
    return True


def install_shell(paths: AppPaths | None = None, home: Path | None = None) -> list[Path]:
    """Install assets and one managed source block per supported config file."""
    resolved = paths or resolve_paths()
    user_home = home or Path.home()
    destination = resolved.config_dir / "shell"
    ensure_private_directory(resolved.config_dir)
    ensure_private_directory(destination)
    assets = _asset_dir()
    installed: list[Path] = []
    for name in ("securityllama.zsh", "securityllama.bash", "securityllama.tmux.conf"):
        target = destination / name
        content = (assets / name).read_text(encoding="utf-8")
        target.write_text(_render_asset(name, content, resolved), encoding="utf-8")
        target.chmod(0o600)
        installed.append(target)
    mappings = (
        (user_home / ".zshrc", f'source "{destination / "securityllama.zsh"}"'),
        (user_home / ".bashrc", f'source "{destination / "securityllama.bash"}"'),
        (user_home / ".tmux.conf", f'source-file "{destination / "securityllama.tmux.conf"}"'),
    )
    for path, source_line in mappings:
        _replace_block(path, source_line)
    return installed


def remove_shell_blocks(home: Path | None = None) -> None:
    user_home = home or Path.home()
    for path in (user_home / ".zshrc", user_home / ".bashrc", user_home / ".tmux.conf"):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        start = text.find(BEGIN)
        end = text.find(END, start + len(BEGIN)) if start >= 0 else -1
        if start < 0 or end < 0:
            start = text.find(LEGACY_BEGIN)
            end = text.find(LEGACY_END, start + len(LEGACY_BEGIN)) if start >= 0 else -1
        if start >= 0 and end >= 0:
            updated = text[:start] + text[end + len(END) :]
            path.write_text(updated.lstrip("\n") if not text[:start] else updated, encoding="utf-8")
