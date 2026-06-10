"""Tests for the retry helper."""

import pytest

from bond_futures_monitor.retry import retry_call


def test_retry_call_returns_first_success():
    calls = {"n": 0}

    def succeed():
        calls["n"] += 1
        return "ok"

    assert retry_call(succeed) == "ok"
    assert calls["n"] == 1


def test_retry_call_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("bond_futures_monitor.retry.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    assert retry_call(flaky, attempts=3) == "ok"
    assert calls["n"] == 3


def test_retry_call_reraises_last_error_after_exhaustion(monkeypatch):
    monkeypatch.setattr("bond_futures_monitor.retry.time.sleep", lambda _: None)
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        retry_call(always_fail, attempts=3)
    assert calls["n"] == 3
