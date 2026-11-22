"""The session plan block and the email guard (billing routes come from the billing package)."""

from fastapi import HTTPException
from backend.plans import billing, plans
from backend.plans import settings as paid_settings


_NO_STORE = {"Cache-Control": "no-store"}


def session_plan(row) -> dict:
    pro = plans.active(row)
    return {
        "pro": pro,
        "tier": plans.of(row),
        "status": row["plan_status"],
        "until": row["plan_until"],
        "cancels": bool(row["plan_cancels"]),
        "comp_until": row["pro_comp_until"],  # a free plan from the operator (admin comp)
        "source": plans.pro_source(row),  # "stripe", "comp" or None
        "manageable": billing.syncing() and bool(row["stripe_customer"]),
        "free": paid_settings.free_max(),  # nothing is sold: the app shows no plan
    }


def require_email_in(conn, owner) -> None:
    customer = conn.execute("SELECT stripe_customer FROM lists WHERE id = ?", (owner,)).fetchone()["stripe_customer"]
    if customer:
        raise HTTPException(
            status_code=409,
            headers=_NO_STORE,
            detail=(
                "This account has Pro billing, which needs an email to sign back in "
                "with: change it to another address instead."
            ),
        )
