from pathlib import Path


def test_production_has_no_autonomous_execution_patterns() -> None:
    roots = [Path("src"), Path("shell"), Path("scripts")]
    forbidden = ("shell" + "=True", "ev" + "al ", "send-" + "keys")
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".sh", ".zsh", ".bash", ".conf"}:
                text = path.read_text(encoding="utf-8")
                for pattern in forbidden:
                    assert pattern not in text, f"forbidden execution pattern {pattern!r} in {path}"
