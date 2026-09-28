"""CLI output remains usable on Windows code pages."""

from src.cli import _console_safe


def test_report_text_prints_on_cp1252() -> None:
    assert _console_safe("shortage − 1", "cp1252") == "shortage \\u2212 1"
