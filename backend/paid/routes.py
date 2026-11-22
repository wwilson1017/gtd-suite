"""Billing HTTP routes and the session plan block."""

import asyncio
from typing import Literal

from pydantic import BaseModel
from fastapi import Depends, HTTPException, Request, Response
from backend.paid import billing, plans
from backend.paid import settings as paid_settings
from backend import common, lists


class BillingCheckout(BaseModel):
    interval: Literal["month", "year"]


_NO_STORE = {"Cache-Control": "no-store"}


def mount(router, account_router, session_owner, _base_url):
    # ── Pro (billing.py): Upgrade, Manage billing, and Stripe's webhook ───────────

    def _no_billing() -> HTTPException:
        return HTTPException(status_code=404, detail="Not found", headers=_NO_STORE)

    def _billing_failed() -> HTTPException:
        return HTTPException(
            status_code=502, detail="Could not reach the payment service. Try again.", headers=_NO_STORE
        )

    @account_router.post("/billing/checkout")
    def billing_checkout(
        body: BillingCheckout, request: Request, response: Response, owner: int = Depends(session_owner)
    ):
        """Upgrade: a Stripe Checkout address for Pro, which the browser goes to. Pro's
        receipts go to the account's email, so it must be confirmed first."""
        if not billing.selling():
            raise _no_billing()
        account = lists.get_list(owner)
        assert account is not None  # The session owner has already been resolved.
        if account["email_verified_at"] is None:
            raise HTTPException(
                status_code=409, detail="Confirm your email first: Pro's receipts go there.", headers=_NO_STORE
            )
        try:
            url = billing.checkout_url(owner, body.interval, _base_url(request), account["email"])
        except billing.EmailChanged:
            raise HTTPException(
                status_code=409,
                detail="Your email just changed: confirm it first, since Pro's receipts go there.",
                headers=_NO_STORE,
            )
        except billing.AlreadyPro:
            raise HTTPException(status_code=409, detail="This account is on Pro already.", headers=_NO_STORE)
        except billing.NeedsAttention:
            raise HTTPException(
                status_code=409,
                detail="Your Pro subscription needs attention: open Manage billing to pay or cancel it.",
                headers=_NO_STORE,
            )
        except billing.BillingError:
            raise _billing_failed()
        response.headers.update(_NO_STORE)
        return {"url": url}

    @account_router.post("/billing/sync")
    def billing_sync(response: Response, owner: int = Depends(session_owner)):
        """Back from Checkout: re-read the account's subscriptions from Stripe now, so Pro
        arrives even when the webhook is slow or failed. Answers the plan."""
        if not billing.syncing():
            raise _no_billing()
        try:
            billing.sync(owner)
        except billing.BillingError:
            raise _billing_failed()
        row = lists.get_list(owner)
        assert row is not None  # The session owner has already been resolved.
        response.headers.update(_NO_STORE)
        return {"pro": plans.active(row), "status": row["plan_status"]}

    @account_router.post("/billing/manage")
    def billing_manage(request: Request, response: Response, owner: int = Depends(session_owner)):
        """Manage billing: a Stripe Customer Portal address (change, cancel, receipts)."""
        if not billing.syncing():
            raise _no_billing()
        try:
            url = billing.portal_url(owner, _base_url(request))
        except billing.BillingError:
            raise _billing_failed()
        if url is None:
            raise HTTPException(status_code=409, detail="This account has never bought Pro.", headers=_NO_STORE)
        response.headers.update(_NO_STORE)
        return {"url": url}

    _MAX_WEBHOOK_BYTES = 256 * 1024

    @router.post("/stripe/webhook")
    async def stripe_webhook(request: Request):
        """Stripe says a subscription or payment changed: verify the signature, then sync
        the account it is about (billing.handle). Stripe's servers call it, so there is no
        session and no same-origin check. The body is never logged: it carries an email."""
        if not billing.syncing():
            raise _no_billing()
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > _MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Too large")
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > _MAX_WEBHOOK_BYTES:
                raise HTTPException(status_code=413, detail="Too large")
        try:
            event = billing.verify(body, request.headers.get("stripe-signature", ""), common.utcnow().timestamp())
        except billing.BadSignature:
            raise HTTPException(status_code=400, detail="Bad signature")
        try:
            await asyncio.to_thread(billing.handle, event)
        except billing.BillingError:
            # Stripe retries a failed delivery, and the hourly catch-up is the backstop.
            raise HTTPException(status_code=502, detail="Could not sync")
        return {"ok": True}


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
