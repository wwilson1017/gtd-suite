"""Paid limits and schema; no app imports."""

PLAN_COLUMNS = "plan_status, plan_until, pro_comp_until, comp_plan"
ACCOUNT_COLUMNS = "stripe_customer, plan_cancels, " + PLAN_COLUMNS
# Current subscriptions are synced by billing.sync; grants are written by admin.comp.
# Customer/email fields retain billing identity and the last confirmed receipts address.
# The period end and cancellation flag are the last subscription state; rev refuses
# stale sync writes. Grant expiry is nullable and its kind keeps the original default.
COLUMNS = {
    "stripe_customer": "TEXT NOT NULL DEFAULT ''",
    "stripe_email": "TEXT NOT NULL DEFAULT ''",
    "stripe_subscription": "TEXT NOT NULL DEFAULT ''",
    "plan_status": "TEXT NOT NULL DEFAULT ''",
    "plan_until": "TEXT",
    "plan_cancels": "INTEGER NOT NULL DEFAULT 0",
    "plan_rev": "INTEGER NOT NULL DEFAULT 0",
    "pro_comp_until": "TEXT",
    "comp_plan": "TEXT NOT NULL DEFAULT 'pro'",
    # Who gave the current grant: '' the operator (admin.comp), 'springform' a Springform connect.
    "comp_source": "TEXT NOT NULL DEFAULT ''",
    # When a Springform connect first granted Max; never cleared, so it is granted once.
    "springform_at": "TEXT",
}
LISTS_DDL = ",\n".join(f"{name} {ddl}" for name, ddl in COLUMNS.items())

SITE_PRO_CAPS = (2_500, 2_500)
# simplification: the highest plan uses the self-host ceiling; split it if that ceiling bites.
SITE_MAX_CAPS = (10_000, 10_000)
BRAIN_PRO_CAPS = (None, 10_000, 25_000)
BRAIN_MAX_CAPS = (None, 1_000_000, 1_000_000)
FILE_PRO_QUOTA = 10_000_000_000
FILE_MAX_QUOTA = 100_000_000_000

TODO = {"pro": (20_000, 1_000, 100), "max": (20_000, 1_000, 100)}
BOARD = {"pro": (1_000, 20_000), "max": (1_000, 20_000)}
NOTE = {"pro": 20_000, "max": 20_000}
RECORDING = {"pro": 200_000, "max": 200_000}
SITE = {"pro": SITE_PRO_CAPS, "max": SITE_MAX_CAPS}
BRAIN = {"pro": BRAIN_PRO_CAPS, "max": BRAIN_MAX_CAPS}
SHORT_NAMES = {"pro": 10, "max": 100}
SITE_BYTES = {"pro": 250_000_000, "max": 1_000_000_000}
PAGE_BYTES = {"pro": 2_000_000, "max": 10_000_000}
DATA = {"pro": (500_000_000, 20_000), "max": (2_000_000_000, 100_000)}
BRAINS = {"pro": 10, "max": 100}
LINKS = {"pro": 100, "max": 1000}
FILES = {"pro": FILE_PRO_QUOTA, "max": FILE_MAX_QUOTA}
