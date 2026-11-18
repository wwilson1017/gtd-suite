"""Payment service settings, read at call time."""

import os


def stripe_secret_key() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def stripe_webhook_secret() -> str:
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()


def stripe_price(interval: str) -> str:
    """The Stripe price id for Pro billed by ``interval`` (month or year), or ''."""
    return os.environ.get(f"STRIPE_PRICE_{interval.upper()}", "").strip()
