from pathlib import Path

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
ask_hotkey = "alt-o"
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
    assert "bindkey '^[o' securityllama-open-cockpit" in zsh
    assert "bind -x '\"\\er\":_securityllama_widget'" in bash
    assert "bind-key L" in tmux
    assert "display-popup -EE" in tmux
    assert '"securityllama" cockpit' not in tmux
    assert "-w 80% -h 70%" in tmux
    assert 'local saved_buffer="$BUFFER" saved_cursor="$CURSOR"' in zsh
    assert 'BUFFER="$saved_buffer"' in zsh
