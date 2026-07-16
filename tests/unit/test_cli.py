from kali_copilot.cli import main


def test_empty_cli_is_safe() -> None:
    assert main([]) == 0
