import fcntl
import os
import pty
import shlex
import shutil
import subprocess
import termios
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


def test_install_renders_widget_and_persistent_chat_binding(tmp_path: Path) -> None:
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
    assert "bind -x '\"\\er\":_securityllama_widget'" in bash
    assert "</dev/tty >/dev/tty 2>&1" in zsh
    assert "</dev/tty >/dev/tty 2>&1" in bash
    assert "zle -I" in zsh
    assert "securityllama-insert-proposal" not in zsh + bash
    assert "securityllama-open-cockpit" not in zsh + bash
    assert "bind-key L" in tmux
    assert "run-shell" in tmux
    assert "_open-chat" in tmux
    assert "#{q:pane_id}" in tmux
    assert "#{q:pane_current_path}" in tmux
    assert "display-popup" not in tmux


def test_install_normalizes_relative_executable_for_widget_and_tmux_chat(
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
    assert zsh.count("securityllama_bin=$(_securityllama_executable)") == 1
    assert bash.count("securityllama_bin=$(_securityllama_executable)") == 1
    assert tmux.count(str(launcher)) == 2
    assert "@SECURITYLLAMA_EXECUTABLE@" not in zsh + bash
    assert "@SECURITYLLAMA_CHAT_COMMAND@" not in tmux
    assert "_open-chat" in tmux
    assert "^[i" not in zsh and "\\ei" not in bash
    assert "^[o" not in zsh and "\\eo" not in bash


def test_install_records_stable_launcher_symlink_instead_of_venv_target(
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
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    monkeypatch.setattr("kali_copilot.install.shutil.which", lambda command: str(shim))

    install_shell(paths, home)

    installed = "\n".join(
        (paths.config_dir / "shell" / name).read_text()
        for name in ("securityllama.zsh", "securityllama.bash", "securityllama.tmux.conf")
    )
    assert str(shim) in installed
    assert str(target) not in installed


@pytest.mark.parametrize(
    ("shell_name", "shell_args"),
    (("bash", ("--noprofile", "--norc")), ("zsh", ("-f",))),
)
def test_installed_shell_resolves_widget_from_unrelated_directory_without_path(
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
    command = 'source "$1" >/dev/null 2>&1 || true; cd "$2" || exit 1; _securityllama_executable'

    completed = subprocess.run(  # noqa: S603 - fixed shell with inert test script
        [shell, *shell_args, "-c", command, "securityllama-test", str(asset), str(unrelated)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(launcher)


@pytest.mark.parametrize(
    ("shell_name", "shell_args"),
    (("bash", ("--noprofile", "--norc")), ("zsh", ("-f",))),
)
def test_direct_widget_reconnects_all_streams_to_controlling_terminal(
    tmp_path: Path, monkeypatch, shell_name: str, shell_args: tuple[str, ...]
) -> None:
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"{shell_name} is not installed")
    home = tmp_path / "home"
    home.mkdir()
    launcher = tmp_path / "securityllama"
    result = tmp_path / "tty-result"
    launcher.write_text(
        """#!/bin/sh
case "$1" in
  _make-widget-request) exit 0 ;;
  shell-widget)
    if [ -t 0 ] && [ -t 1 ] && [ -t 2 ]; then
      printf '%s' tty >"$SECURITYLLAMA_TTY_RESULT"
      exit 0
    fi
    exit 9
    ;;
  _extract-widget-response) printf '%s\\n' none ;;
esac
""",
        encoding="utf-8",
    )
    launcher.chmod(0o700)
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    monkeypatch.setattr("kali_copilot.install.shutil.which", lambda command: str(launcher))
    install_shell(paths, home)
    asset = paths.config_dir / "shell" / f"securityllama.{shell_name}"
    environment = os.environ.copy()
    environment["SECURITYLLAMA_TTY_RESULT"] = str(result)
    environment["XDG_RUNTIME_DIR"] = str(paths.runtime_dir)
    command = (
        'source "$1" >/dev/null 2>&1 || true; '
        "zle() { return 0; }; "
        "unset TMUX TMUX_PANE; "
        "BUFFER=review; CURSOR=6; READLINE_LINE=review; READLINE_POINT=6; "
        "_securityllama_widget"
    )
    master_fd, slave_fd = pty.openpty()

    def attach_controlling_terminal() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    try:
        completed = subprocess.run(  # noqa: S603 - fixed shell with inert test script
            [shell, *shell_args, "-c", command, "securityllama-test", str(asset)],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=slave_fd,
            stderr=slave_fd,
            env=environment,
            pass_fds=(slave_fd,),
            preexec_fn=attach_controlling_terminal,
        )
    finally:
        os.close(slave_fd)
        os.close(master_fd)

    assert completed.returncode == 0
    assert result.read_text(encoding="utf-8") == "tty"


def test_install_preserves_legacy_hotkey_fields_without_binding_them(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    paths = AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")
    paths.config_dir.mkdir()
    paths.config_file.write_text('[ui]\nask_hotkey = "alt-q"\n', encoding="utf-8")

    install_shell(paths, home)

    assert 'ask_hotkey = "alt-q"' in paths.config_file.read_text()
    assert not list(paths.config_dir.glob("config.toml.securityllama-backup-*"))
    zsh = (paths.config_dir / "shell" / "securityllama.zsh").read_text()
    assert "securityllama-open-cockpit" not in zsh
