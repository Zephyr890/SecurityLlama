from kali_copilot.app import should_include_recent_turns


def test_explain_with_tool_output_excludes_stale_memory() -> None:
    assert not should_include_recent_turns("explain", "Nikto finding: CORS wildcard")
    assert should_include_recent_turns("explain", "  \n")
    assert should_include_recent_turns("ask", "current evidence")
