from kali_copilot.config import AppConfig
from kali_copilot.context import ContextCollector
from kali_copilot.tmux import CaptureResult


def test_tmux_context_uses_originating_pane_working_directory(monkeypatch) -> None:
    monkeypatch.setattr(
        "kali_copilot.context.capture_pane",
        lambda pane_id, max_lines: CaptureResult("bounded output", pane_id, "/target/two"),
    )

    packet = ContextCollector(AppConfig()).collect_tmux("%9", "ask", "What changed?")

    assert packet.pane_id == "%9"
    assert packet.cwd == "/target/two"
    assert packet.recent_output == "bounded output"
