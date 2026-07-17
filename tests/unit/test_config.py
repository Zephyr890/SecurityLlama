from __future__ import annotations

from pathlib import Path

import pytest

from kali_copilot.config import ConfigError, UIConfig, load_config
from kali_copilot.paths import AppPaths


def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "cache", tmp_path / "run")


def test_environment_overrides_toml(tmp_path: Path) -> None:
    app_paths = paths(tmp_path)
    app_paths.config_dir.mkdir()
    app_paths.config_file.write_text(
        '[ollama]\nbase_url="http://127.0.0.1:1"\nmodel="file-model"\n', encoding="utf-8"
    )
    config = load_config(
        app_paths,
        {"SECURITYLLAMA_MODEL": "env-model", "SECURITYLLAMA_OLLAMA_URL": "http://localhost:2"},
    )
    assert config.ollama.model == "env-model"
    assert config.ollama.base_url == "http://localhost:2"


def test_public_endpoint_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="public Ollama endpoint rejected"):
        load_config(paths(tmp_path), {"SECURITYLLAMA_OLLAMA_URL": "https://models.example.com"})


def test_ui_shell_hotkey_is_validated() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="must use the form"):
        UIConfig(shell_hotkey="control-a")


def test_legacy_popup_hotkeys_load_but_are_excluded_from_public_config() -> None:
    ui = UIConfig(insert_hotkey="alt-i", ask_hotkey="alt-o")
    assert ui.insert_hotkey == "alt-i"
    assert ui.ask_hotkey == "alt-o"
    assert "insert_hotkey" not in ui.model_dump()
    assert "ask_hotkey" not in ui.model_dump()
