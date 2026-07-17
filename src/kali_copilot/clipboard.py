"""Safe system-clipboard transfer for validated single-line proposals."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from kali_copilot.sanitize import sanitize_for_display


class ClipboardError(RuntimeError):
    """A proposal could not be copied without invoking a shell."""


@dataclass(frozen=True)
class ClipboardProvider:
    name: str
    command: tuple[str, ...]


def clipboard_provider(
    environ: dict[str, str] | None = None, *, platform_name: str | None = None
) -> ClipboardProvider | None:
    """Return the first supported clipboard provider available to this process."""
    env = os.environ if environ is None else environ
    platform = sys.platform if platform_name is None else platform_name
    if platform == "darwin":
        executable = shutil.which("pbcopy")
        return ClipboardProvider("pbcopy", (executable,)) if executable else None
    if env.get("WAYLAND_DISPLAY"):
        executable = shutil.which("wl-copy")
        if executable:
            return ClipboardProvider("wl-copy", (executable,))
    executable = shutil.which("xclip")
    if executable:
        return ClipboardProvider("xclip", (executable, "-selection", "clipboard"))
    executable = shutil.which("xsel")
    if executable:
        return ClipboardProvider("xsel", (executable, "--clipboard", "--input"))
    return None


def copy_to_clipboard(text: str) -> str:
    """Copy inert single-line text through stdin and return the provider name."""
    if not text or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ClipboardError("refusing to copy an empty or control-containing command")
    provider = clipboard_provider()
    if provider is None:
        raise ClipboardError(
            "no supported clipboard tool found; install xclip on Kali or use pbcopy on macOS"
        )
    try:
        result = subprocess.run(  # noqa: S603 - fixed local executable; text is stdin data
            list(provider.command),
            input=text,
            text=True,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClipboardError(
            f"{provider.name} could not access the system clipboard: "
            f"{sanitize_for_display(str(exc))}"
        ) from exc
    if result.returncode != 0:
        detail = sanitize_for_display(result.stderr.strip()) or "clipboard tool failed"
        raise ClipboardError(f"{provider.name} could not access the system clipboard: {detail}")
    return provider.name
