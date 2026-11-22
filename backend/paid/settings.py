"""Payment service settings, read at call time."""

import os


def stripe_secret_key() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def stripe_webhook_secret() -> str:
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()


def stripe_price(interval: str) -> str:
    """The Stripe price id for Pro billed by ``interval`` (month or year), or ''."""
    return os.environ.get(f"STRIPE_PRICE_{interval.upper()}", "").strip()


def free_max() -> bool:
    """The suite is free (the default): a hosted account with a confirmed email is on Max
    (plans.of) and nothing is sold (billing.syncing). FREE_MAX=false brings paid plans back
    exactly as they were."""
    return os.environ.get("FREE_MAX", "").strip().lower() not in ("0", "false", "no", "off")
