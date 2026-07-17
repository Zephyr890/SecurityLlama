from __future__ import annotations

from types import SimpleNamespace

import pytest

import kali_copilot.clipboard as clipboard
from kali_copilot.clipboard import ClipboardError, ClipboardProvider


def test_clipboard_uses_fixed_command_and_stdin(monkeypatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        clipboard,
        "clipboard_provider",
        lambda: ClipboardProvider("xclip", ("/usr/bin/xclip", "-selection", "clipboard")),
    )

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        seen.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(clipboard.subprocess, "run", run)

    assert clipboard.copy_to_clipboard("printf safe") == "xclip"
    assert seen["command"] == ["/usr/bin/xclip", "-selection", "clipboard"]
    assert seen["input"] == "printf safe"
    assert "shell" not in seen


@pytest.mark.parametrize("value", ("", "first\nsecond", "bad\x00value", "bad\x1bvalue"))
def test_clipboard_rejects_empty_and_control_containing_text(value: str) -> None:
    with pytest.raises(ClipboardError, match="refusing to copy"):
        clipboard.copy_to_clipboard(value)


def test_clipboard_provider_prefers_wayland_then_x11(monkeypatch) -> None:
    available = {"wl-copy": "/usr/bin/wl-copy", "xclip": "/usr/bin/xclip"}
    monkeypatch.setattr(clipboard.shutil, "which", available.get)

    wayland = clipboard.clipboard_provider({"WAYLAND_DISPLAY": "wayland-0"}, platform_name="linux")
    x11 = clipboard.clipboard_provider({}, platform_name="linux")

    assert wayland == ClipboardProvider("wl-copy", ("/usr/bin/wl-copy",))
    assert x11 == ClipboardProvider("xclip", ("/usr/bin/xclip", "-selection", "clipboard"))


def test_clipboard_provider_uses_pbcopy_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(clipboard.shutil, "which", lambda command: f"/usr/bin/{command}")

    provider = clipboard.clipboard_provider({}, platform_name="darwin")

    assert provider == ClipboardProvider("pbcopy", ("/usr/bin/pbcopy",))
