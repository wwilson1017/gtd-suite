"""Shared test setup for plan settings."""


def clear_settings(monkeypatch):
    # The suite's tests were written against paid plans; test_free_max.py turns the free default back on.
    monkeypatch.setenv("FREE_MAX", "false")
    monkeypatch.delenv("SIGNUP_CLOSED", raising=False)
