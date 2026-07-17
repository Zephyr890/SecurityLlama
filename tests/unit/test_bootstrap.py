import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap-kali.sh"


def _write_command(directory: Path, name: str, body: str = "exit 0") -> Path:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_bootstrap_skips_apt_when_core_commands_are_present(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home_bin = home / ".local" / "bin"
    home_bin.mkdir(parents=True)
    _write_command(bin_dir, "python3")
    _write_command(home_bin, "pipx")
    _write_command(home_bin, "securityllama")
    apt_marker = tmp_path / "apt-was-called"
    _write_command(bin_dir, "apt-get", f"touch {apt_marker!s}\nexit 99")
    _write_command(bin_dir, "sudo", f"touch {apt_marker!s}\nexit 99")

    bash = shutil.which("bash")
    assert bash is not None
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }
    command = 'source "$1"; apt_supported() { return 0; }; main --non-interactive'
    completed = subprocess.run(  # noqa: S603
        [bash, "-c", command, "bootstrap-test", str(BOOTSTRAP)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "skipping apt repository access" in completed.stdout
    assert not apt_marker.exists()


def test_missing_core_packages_do_not_include_optional_tools(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_command(bin_dir, "python3")

    bash = shutil.which("bash")
    assert bash is not None
    command = 'source "$1"; PATH="$2"; missing_core_apt_packages'
    completed = subprocess.run(  # noqa: S603
        [bash, "-c", command, "bootstrap-test", str(BOOTSTRAP), str(bin_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.splitlines() == ["python3-venv", "pipx"]


def test_no_apt_reports_missing_core_command_without_repository_access(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_command(bin_dir, "python3")
    dirname = shutil.which("dirname")
    assert dirname is not None
    (bin_dir / "dirname").symlink_to(dirname)
    apt_marker = tmp_path / "apt-was-called"
    _write_command(bin_dir, "apt-get", f"touch {apt_marker!s}\nexit 99")
    _write_command(bin_dir, "sudo", f"touch {apt_marker!s}\nexit 99")

    bash = shutil.which("bash")
    assert bash is not None
    command = 'source "$1"; PATH="$2"; main --no-apt --non-interactive'
    completed = subprocess.run(  # noqa: S603
        [bash, "-c", command, "bootstrap-test", str(BOOTSTRAP), str(bin_dir)],
        check=False,
        capture_output=True,
        env={**os.environ, "HOME": str(tmp_path / "home")},
        text=True,
    )

    assert completed.returncode == 2
    assert "Missing required command(s): pipx." in completed.stderr
    assert not apt_marker.exists()
