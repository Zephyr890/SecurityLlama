import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from kali_copilot.install import BEGIN, install_shell, remove_shell_blocks
from kali_copilot.paths import AppPaths


def test_install_is_idempotent_and_uninstall_preserves_other_content(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("# user setting\n", encoding="utf-8")
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    install_shell(paths, home)
    install_shell(paths, home)
    zshrc = (home / ".zshrc").read_text()
    assert zshrc.count(BEGIN) == 1
    assert "# user setting" in zshrc
    remove_shell_blocks(home)
    assert BEGIN not in (home / ".zshrc").read_text()
    assert "# user setting" in (home / ".zshrc").read_text()


def test_install_renders_validated_custom_bindings_and_popup_size(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    paths.config_dir.mkdir()
    paths.config_file.write_text(
        """[ui]
popup_width_percent = 80
popup_height_percent = 70
shell_hotkey = "alt-r"
insert_hotkey = "alt-p"
ask_hotkey = "alt-v"
tmux_binding = "L"
""",
        encoding="utf-8",
    )
    install_shell(paths, home)
    zsh = (paths.config_dir / "shell" / "securityllama.zsh").read_text()
    bash = (paths.config_dir / "shell" / "securityllama.bash").read_text()
    tmux = (paths.config_dir / "shell" / "securityllama.tmux.conf").read_text()
    assert "bindkey '^[r' securityllama-widget" in zsh
    assert "bindkey '^[p' securityllama-insert-proposal" in zsh
    assert "bindkey '^[v' securityllama-open-cockpit" in zsh
    assert "bind -x '\"\\er\":_securityllama_widget'" in bash
    assert "bind-key L" in tmux
    assert "display-popup -EE" in tmux
    assert '"securityllama" cockpit' not in tmux
    assert "-w 80% -h 70%" in tmux
    assert 'local saved_buffer="$BUFFER" saved_cursor="$CURSOR"' in zsh
    assert 'BUFFER="$saved_buffer"' in zsh


def test_install_normalizes_relative_executable_for_every_shell_shortcut(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    launcher = tmp_path / "relative-bin" / "securityllama"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o700)
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "kali_copilot.install.shutil.which", lambda command: "relative-bin/securityllama"
    )

    install_shell(paths, home)

    zsh = (paths.config_dir / "shell" / "securityllama.zsh").read_text()
    bash = (paths.config_dir / "shell" / "securityllama.bash").read_text()
    tmux = (paths.config_dir / "shell" / "securityllama.tmux.conf").read_text()
    quoted_launcher = shlex.quote(str(launcher))
    assert f"local securityllama_fallback={quoted_launcher}" in zsh
    assert f"local securityllama_fallback={quoted_launcher}" in bash
    assert zsh.count("securityllama_bin=$(_securityllama_executable)") == 3
    assert bash.count("securityllama_bin=$(_securityllama_executable)") == 3
    assert f'-- "{launcher}" cockpit' in tmux
    assert "@SECURITYLLAMA_EXECUTABLE@" not in zsh + bash + tmux
    assert "bindkey '^[o' securityllama-open-cockpit" in zsh
    assert "bind -x '\"\\eo\":_securityllama_open_cockpit'" in bash


@pytest.mark.parametrize(
    ("shell_name", "shell_args"),
    (("bash", ("--noprofile", "--norc")), ("zsh", ("-f",))),
)
def test_installed_shell_opens_cockpit_from_unrelated_directory_without_path(
    tmp_path: Path, monkeypatch, shell_name: str, shell_args: tuple[str, ...]
) -> None:
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"{shell_name} is not installed")
    home = tmp_path / "home"
    home.mkdir()
    install_dir = tmp_path / "checkout"
    install_dir.mkdir()
    launcher = install_dir / "relative-bin" / "securityllama"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o700)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    monkeypatch.chdir(install_dir)
    monkeypatch.setattr(
        "kali_copilot.install.shutil.which", lambda command: "relative-bin/securityllama"
    )
    install_shell(paths, home)
    asset = paths.config_dir / "shell" / f"securityllama.{shell_name}"
    environment = os.environ.copy()
    environment["PATH"] = "/usr/bin:/bin"
    command = """
source "$1" >/dev/null 2>&1 || true
cd "$2" || exit 1
tmux() { printf 'tmux-arg=%s\n' "$@"; }
zle() { return 0; }
TMUX=fixture
TMUX_PANE=%9
BUFFER=preserved
CURSOR=4
READLINE_LINE=preserved
READLINE_POINT=4
printf 'resolved=%s\n' "$(_securityllama_executable)"
_securityllama_open_cockpit
printf 'buffer=%s:%s\n' "$BUFFER" "$CURSOR"
printf 'readline=%s:%s\n' "$READLINE_LINE" "$READLINE_POINT"
"""

    completed = subprocess.run(  # noqa: S603 - fixed shell with inert test script
        [shell, *shell_args, "-c", command, "securityllama-test", str(asset), str(unrelated)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.splitlines()
    assert f"resolved={launcher}" in output
    assert f"tmux-arg={unrelated}" in output
    assert f"tmux-arg={launcher}" in output
    assert "tmux-arg=%9" in output
    assert "buffer=preserved:4" in output
    assert "readline=preserved:4" in output


def test_install_migrates_shipped_alt_q_default_with_backup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    paths.config_dir.mkdir()
    paths.config_file.write_text('[ui]\nask_hotkey = "alt-q"\n', encoding="utf-8")

    install_shell(paths, home)

    assert 'ask_hotkey = "alt-o"' in paths.config_file.read_text()
    backups = list(paths.config_dir.glob("config.toml.securityllama-backup-*"))
    assert len(backups) == 1
    assert 'ask_hotkey = "alt-q"' in backups[0].read_text()
    zsh = (paths.config_dir / "shell" / "securityllama.zsh").read_text()
    assert "bindkey '^[o' securityllama-open-cockpit" in zsh
