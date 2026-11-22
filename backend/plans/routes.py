"""The session's level block and the email guard."""

from fastapi import HTTPException
from backend.plans import extension, plans
from backend.plans import settings as plan_settings


_NO_STORE = {"Cache-Control": "no-store"}


def session_plan(row) -> dict:
    return {
        "raised": plans.active(row),
        "tier": plans.of(row),
        "free": plan_settings.free_max(),  # a confirmed email unlocks everything: no level is shown
        **extension.session(row),
    }


def require_email_in(conn, owner) -> None:
    customer = conn.execute("SELECT stripe_customer FROM lists WHERE id = ?", (owner,)).fetchone()["stripe_customer"]
    if customer:
        raise HTTPException(
            status_code=409,
            headers=_NO_STORE,
            detail=(
                "This account is tied to an outside account that needs an email to sign back in "
                "with: change it to another address instead."
            ),
        )
