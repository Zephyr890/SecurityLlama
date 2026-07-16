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
