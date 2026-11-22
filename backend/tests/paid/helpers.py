"""Shared test setup for payment service settings."""


def clear_settings(monkeypatch):
    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_MONTH", "STRIPE_PRICE_YEAR"):
        monkeypatch.delenv(name, raising=False)
    # The suite's tests were written against paid plans; test_free_max.py turns the free default back on.
    monkeypatch.setenv("FREE_MAX", "false")
    monkeypatch.delenv("SIGNUP_CLOSED", raising=False)
