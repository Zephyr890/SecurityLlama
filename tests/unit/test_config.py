from __future__ import annotations

from pathlib import Path

import pytest

from kali_copilot.config import ConfigError, load_config
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
