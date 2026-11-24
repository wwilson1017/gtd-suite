"""Account levels: derivation, feature gates and their wording."""

import datetime
from backend import common, settings
from backend.plans import settings as plan_settings

# plan_status and plan_until are a level the extension (extension.py) last stored: live
# in one of these states until three days after plan_until, so a missed update can never
# leave an account raised for good. Without the extension they never change.
LIVE_STATUSES = ("active", "trialing", "past_due")
GRACE = datetime.timedelta(days=3)


def source(row) -> str | None:
    """Where the list's level comes from now (a row with PLAN_COLUMNS), the highest that
    applies: "grant" for the operator's grant of max (admin.py comp), which outranks a
    stored level; "status" for a live stored level within its period and grace; "grant"
    for a grant of pro; else None."""
    now = common.utcnow()
    comp = bool(row["pro_comp_until"]) and now < datetime.datetime.fromisoformat(row["pro_comp_until"])
    if comp and row["comp_plan"] == "max":
        return "grant"
    if (
        row["plan_status"] in LIVE_STATUSES
        and row["plan_until"]
        and now <= datetime.datetime.fromisoformat(row["plan_until"]) + GRACE
    ):
        return "status"
    return "grant" if comp else None


def of(row) -> str | None:
    """The list's level now (a row with PLAN_COLUMNS): "max", "pro" (the stored tier keys)
    or None. While the suite is free (settings.free_max), a hosted account with a confirmed
    email is on max, derived here like every level and never stored."""
    if plan_settings.free_max() and settings.open_signup() and row["email_verified_at"]:
        return "max"
    found = source(row)
    if found is None:
        return None
    return "max" if found == "grant" and row["comp_plan"] == "max" else "pro"


def active(row) -> bool:
    return of(row) is not None


def features(hosted: bool, plan: str | None) -> bool:
    return not hosted or plan is not None


def unlimited(hosted: bool, plan: str | None) -> bool:
    return not hosted or plan == "max"


NOT_INCLUDED = "{} are not part of this account's limits."


def _needs_email(what: str) -> str:
    from backend import apps

    return f"{what} come with a confirmed email: confirm one in {apps.settings_page()}. Nothing was changed."


def short_name_refusal() -> str:
    return _needs_email("Short names") if plan_settings.free_max() else NOT_INCLUDED.format("Short names")


def password_refusal() -> str:
    from backend.plans import extension

    if plan_settings.free_max():
        return _needs_email("Password-protected pages")
    return f"{NOT_INCLUDED.format('Password-protected pages')}{extension.cap_note(True)} Nothing was changed."


def site_note(eligible: bool, kind: str) -> str:
    from backend.plans import caps, extension

    return extension.cap_note(eligible, caps.SITE_PRO_CAPS[0 if kind == "page" else 1])
