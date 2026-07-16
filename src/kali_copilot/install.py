"""Idempotent, backup-first shell integration installation."""

from __future__ import annotations

import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from kali_copilot.paths import AppPaths, ensure_private_directory, resolve_paths

BEGIN = "# >>> kali-copilot managed block >>>"
END = "# <<< kali-copilot managed block <<<"


def _asset_dir() -> Path:
    checkout = Path(__file__).resolve().parents[2] / "shell"
    if checkout.exists():
        return checkout
    return Path(sys.prefix) / "share" / "kali-copilot" / "shell"


def _replace_block(path: Path, body: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    start = existing.find(BEGIN)
    end = existing.find(END, start + len(BEGIN)) if start >= 0 else -1
    block = f"{BEGIN}\n{body.rstrip()}\n{END}"
    if start >= 0 and end >= 0:
        updated = existing[:start] + block + existing[end + len(END) :]
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        updated = existing + separator + block + "\n"
    if updated == existing:
        return False
    if path.exists():
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, path.with_name(f"{path.name}.kali-copilot-backup-{timestamp}"))
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
    for name in ("kali-copilot.zsh", "kali-copilot.bash", "kali-copilot.tmux.conf"):
        target = destination / name
        shutil.copyfile(assets / name, target)
        target.chmod(0o600)
        installed.append(target)
    mappings = (
        (user_home / ".zshrc", f'source "{destination / "kali-copilot.zsh"}"'),
        (user_home / ".bashrc", f'source "{destination / "kali-copilot.bash"}"'),
        (user_home / ".tmux.conf", f'source-file "{destination / "kali-copilot.tmux.conf"}"'),
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
        if start >= 0 and end >= 0:
            updated = text[:start] + text[end + len(END) :]
            path.write_text(updated.lstrip("\n") if not text[:start] else updated, encoding="utf-8")
