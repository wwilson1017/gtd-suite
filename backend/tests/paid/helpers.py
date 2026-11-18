"""Shared test setup for payment service settings."""


def clear_settings(monkeypatch):
    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_MONTH", "STRIPE_PRICE_YEAR"):
        monkeypatch.delenv(name, raising=False)
