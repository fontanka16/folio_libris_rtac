"""Tests for environment-driven config parsing (_positive_float_env)."""

import pytest

from application import _positive_float_env


def test_default_when_unset(monkeypatch):
    monkeypatch.delenv("FOLIO_TIMEOUT", raising=False)
    assert _positive_float_env("FOLIO_TIMEOUT", 15.0) == 15.0


def test_valid_value_is_used(monkeypatch):
    monkeypatch.setenv("FOLIO_TIMEOUT", "30")
    assert _positive_float_env("FOLIO_TIMEOUT", 15.0) == 30.0


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_value_uses_default_silently(monkeypatch, blank, caplog):
    # An empty / whitespace var means "unset": default, no warning.
    monkeypatch.setenv("FOLIO_TIMEOUT", blank)
    assert _positive_float_env("FOLIO_TIMEOUT", 15.0) == 15.0
    assert caplog.text == ""


@pytest.mark.parametrize(
    "bad",
    [
        "0",        # 0 would put every socket into non-blocking mode
        "-5",       # negative is meaningless
        "abc",      # non-numeric would crash float() at import
        "nan",      # non-finite
        "inf",      # non-finite
        "15s",      # trailing unit
    ],
)
def test_bad_values_fall_back_to_default_with_warning(monkeypatch, bad, caplog):
    monkeypatch.setenv("FOLIO_TIMEOUT", bad)
    assert _positive_float_env("FOLIO_TIMEOUT", 15.0) == 15.0
    assert "FOLIO_TIMEOUT" in caplog.text
