"""Plan derivation and feature gates."""

import datetime
from backend import common

# Pro (billing.py) is derived from the subscription's Stripe status as last synced,
# and lapses this long after the period it last heard about, so a missed renewal
# event can never leave an account on Pro for good (billing.catch_up re-syncs first).
PRO_STATUSES = ("active", "trialing", "past_due")
PRO_GRACE = datetime.timedelta(days=3)


def pro_source(row) -> str | None:
    """Where the list's plan comes from now (a row with PLAN_COLUMNS), the highest that
    applies: "comp" for the operator's grant of Max (admin.py comp), which outranks the
    Pro that Stripe sells; "stripe" for a live subscription within its period and grace;
    "comp" for a grant of Pro; else None."""
    now = common.utcnow()
    comp = bool(row["pro_comp_until"]) and now < datetime.datetime.fromisoformat(row["pro_comp_until"])
    if comp and row["comp_plan"] == "max":
        return "comp"
    if (
        row["plan_status"] in PRO_STATUSES
        and row["plan_until"]
        and now <= datetime.datetime.fromisoformat(row["plan_until"]) + PRO_GRACE
    ):
        return "stripe"
    return "comp" if comp else None


def of(row) -> str | None:
    """The list's plan now (a row with PLAN_COLUMNS): "max", "pro" or None."""
    source = pro_source(row)
    if source is None:
        return None
    return "max" if source == "comp" and row["comp_plan"] == "max" else "pro"


def active(row) -> bool:
    return of(row) is not None


def features(hosted: bool, plan: str | None) -> bool:
    return not hosted or plan is not None


def unlimited(hosted: bool, plan: str | None) -> bool:
    return not hosted or plan == "max"


SHORT_NAME_REFUSAL = "Short names need Pro or Max"


def password_refusal() -> str:
    from backend.paid import billing

    return f"Password-protected pages come with Pro.{billing.upsell(True)} Nothing was changed."


def guide_upsell() -> str:
    from backend import apps
    from backend.paid import billing

    return (
        f"Pro raises them, for {billing.PRICE}: the person upgrades in {apps.settings_page()}"
        if billing.selling()
        else ""
    )


def short_name_guide() -> list[str]:
    from backend.paid import billing

    return (
        ["Short names: Pro 10, Max 100; a lapsed plan has 30 days of grace before names are freed."]
        if billing.selling()
        else []
    )


def site_upsell(eligible: bool, kind: str) -> str:
    from backend.paid import billing, caps

    return billing.upsell(eligible, caps.SITE_PRO_CAPS[0 if kind == "page" else 1])
