from __future__ import annotations

from pathlib import Path

import pytest

from kali_copilot.install import (
    BEGIN,
    END,
    InstallError,
    desktop_launcher_path,
    install_desktop,
    install_shell,
    remove_desktop,
)
from kali_copilot.paths import AppPaths


def _paths(root: Path) -> AppPaths:
    return AppPaths(root / "config", root / "data", root / "cache", root / "run")


def _launcher(root: Path) -> Path:
    launcher = root / "bin" / "securityllama"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o700)
    return launcher


def test_desktop_install_is_idempotent_and_retires_old_shell_blocks(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    managed = f"{BEGIN}\nsource old-securityllama\n{END}\n"
    (home / ".zshrc").write_text("# user setting\n" + managed, encoding="utf-8")
    (home / ".bashrc").write_text(managed, encoding="utf-8")
    (home / ".tmux.conf").write_text(managed, encoding="utf-8")
    launcher = _launcher(tmp_path)
    monkeypatch.setattr("kali_copilot.install.shutil.which", lambda command: str(launcher))
    paths = _paths(tmp_path)

    first = install_desktop(paths, home)
    second = install_desktop(paths, home)

    assert first == second == home / ".local/share/applications/securityllama-console.desktop"
    content = first.read_text(encoding="utf-8")
    assert f'Exec="{launcher}" console' in content
    assert "Terminal=true" in content
    assert first.stat().st_mode & 0o077 == 0
    assert "# user setting" in (home / ".zshrc").read_text(encoding="utf-8")
    for name in (".zshrc", ".bashrc", ".tmux.conf"):
        assert BEGIN not in (home / name).read_text(encoding="utf-8")
        backups = list(home.glob(f"{name}.securityllama-backup-*"))
        assert len(backups) == 1
        assert BEGIN in backups[0].read_text(encoding="utf-8")


def test_desktop_install_uses_xdg_data_home_and_stable_pipx_shim(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "venv" / "bin" / "securityllama"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o700)
    shim = tmp_path / "local" / "bin" / "securityllama"
    shim.parent.mkdir(parents=True)
    shim.symlink_to(target)
    monkeypatch.setattr("kali_copilot.install.shutil.which", lambda command: str(shim))
    environment = {"HOME": str(home), "XDG_DATA_HOME": str(tmp_path / "xdg-data")}

    installed = install_desktop(_paths(tmp_path), home, environment)

    assert installed == tmp_path / "xdg-data/applications/securityllama-console.desktop"
    content = installed.read_text(encoding="utf-8")
    assert str(shim) in content
    assert str(target) not in content


def test_deprecated_install_shell_installs_console_launcher(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    launcher = _launcher(tmp_path)
    monkeypatch.setattr("kali_copilot.install.shutil.which", lambda command: str(launcher))

    installed = install_shell(_paths(tmp_path), home)

    assert installed == [desktop_launcher_path(home)]


def test_remove_desktop_rejects_symlink_and_removes_regular_launcher(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = desktop_launcher_path(home)
    target.parent.mkdir(parents=True)
    source = tmp_path / "source.desktop"
    source.write_text("source", encoding="utf-8")
    target.symlink_to(source)
    with pytest.raises(InstallError, match="symlinked"):
        remove_desktop(home)
    target.unlink()
    target.write_text("launcher", encoding="utf-8")

    remove_desktop(home)

    assert not target.exists()
