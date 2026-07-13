"""Regression tests for the OpenCode Zen balance parser."""

from pathlib import Path
import runpy


_ZEN = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "plugins" / "zen")
)
_extract_balance = _ZEN["_extract_balance"]


def test_extract_balance_preserves_zero_balance():
    """A depleted Zen account ($0.00) is valid data, not a scrape failure."""
    assert _extract_balance('{"balance":0}') == 0.0
    assert _extract_balance('Current balance: $0.00') == 0.0


def test_extract_balance_keeps_fractional_balance():
    assert _extract_balance('{"balance":9.21}') == 9.21


def test_extract_balance_does_not_take_an_unrelated_number_after_balance_word():
    assert _extract_balance("balance unavailable; transaction 249183") is None
