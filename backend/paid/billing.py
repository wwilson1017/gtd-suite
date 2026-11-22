"""todo-gtd — Pro, the paid plan. Simple Sites sells it; it covers the whole account.

Stripe takes the payments as merchant of record (Managed Payments): Checkout sells the
subscription, the Customer Portal manages it, and a signed webhook says something
changed. Pro is never set by hand or by a single event: sync() reads the account's
subscriptions from Stripe and stores the best one (lists.plan_*), and plans.active
derives Pro from that. So event order, duplicate deliveries and an old subscription's
cancellation cannot leave the wrong answer.

Two switches, read at call time: syncing() (paid plans back on with FREE_MAX=false, and
the secret key and the webhook secret, on a hosted server) turns on the webhook and Manage billing; selling() (plus both prices)
turns on Upgrade. Removing a price stops new sales and nothing else.

Stripe's answers are never logged: they carry the customer's email.
"""

import asyncio
import datetime
import hashlib
import hmac
import json
import logging
import secrets
import threading

import httpx2 as httpx

from backend.paid import settings as paid_settings
from backend.paid import caps as paid_caps
from backend.paid import plans
from backend import apps, common, db, settings

API = "https://api.stripe.com/v1"
VERSION = "2026-04-22.dahlia"  # the version that added managed_payments to Checkout
TOLERANCE_SECONDS = 300  # how far a webhook's signed timestamp may be from now
# simplification: the price is text here and in the web app's PlanCard; change both with
# the Stripe prices.
PRICE = "$5 a month or $36 a year"
HANDLED = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
}

logger = logging.getLogger(__name__)
# One sync, checkout or email push at a time, so the latest fetch is the last write and
# two tabs cannot both open a session. Exactly one worker (CLAUDE.md), so in-process is
# enough; re-entrant because a checkout pushes the email and syncs inside it.
_lock = threading.RLock()


class BillingError(Exception):
    """Stripe failed or could not be reached; the message never carries its answer."""


class BillingTimeout(BillingError):
    pass


class AlreadyPro(Exception):
    pass


class EmailChanged(Exception):
    """The confirmed email checkout was asked with is no longer the account's."""


class NeedsAttention(Exception):
    """The account has a subscription that can still be paid (unpaid, incomplete,
    paused): a second one would mean two charges, so it goes to Manage billing."""


class BadSignature(Exception):
    pass


def syncing() -> bool:
    return (
        not paid_settings.free_max()
        and settings.open_signup()
        and bool(paid_settings.stripe_secret_key())
        and bool(paid_settings.stripe_webhook_secret())
    )


def selling() -> bool:
    return syncing() and bool(paid_settings.stripe_price("month")) and bool(paid_settings.stripe_price("year"))


def upsell(eligible: bool, to: int | None = None) -> str:
    """The sentence a cap refusal adds about Pro: only while Pro is on sale and the
    account could buy it (hosted, not on Pro already)."""
    if not (eligible and selling()):
        return ""
    return f" Pro raises it{f' to {to}' if to else ''}, for {PRICE}: Upgrade in {apps.settings_page()}."


def _stripe(method: str, path: str, data: dict | None = None, key: str | None = None) -> dict:
    headers = {"Stripe-Version": VERSION}
    if key:
        headers["Idempotency-Key"] = key
    try:
        res = httpx.request(
            method,
            f"{API}/{path}",
            headers=headers,
            timeout=10,
            auth=(paid_settings.stripe_secret_key(), ""),
            params=data if method == "GET" else None,
            data=data if method != "GET" else None,
        )
    except httpx.TimeoutException as e:
        raise BillingTimeout("Stripe timed out") from e
    except httpx.HTTPError as e:
        raise BillingError("Stripe could not be reached") from e
    if res.status_code >= 300:
        raise BillingError(f"Stripe answered {res.status_code} to {method} {path.split('/')[0]}")
    return res.json()


# Subscriptions that can still take money: never sell a second one beside these.
RECOVERABLE = ("unpaid", "incomplete", "paused")


def _row(list_id: int):
    return (
        db.get_db()
        .execute(
            "SELECT email, email_verified_at, stripe_customer, stripe_email, plan_rev, disabled_at, "
            f"{paid_caps.PLAN_COLUMNS} FROM lists WHERE id = ?",
            (list_id,),
        )
        .fetchone()
    )


# ── Sync: Pro from Stripe's current state ─────────────────────────────────────


def _subscriptions(customer: str) -> list[dict]:
    """Every subscription of the customer, following Stripe's pages."""
    found, after = [], None
    for _ in range(10):
        params = {"customer": customer, "status": "all", "limit": 100}
        if after:
            params["starting_after"] = after
        page = _stripe("GET", "subscriptions", params)
        found += page.get("data") or []
        if not page.get("has_more") or not page.get("data"):
            break
        after = page["data"][-1]["id"]
    return found


def _rank(sub: dict) -> tuple:
    status = sub.get("status")
    live = 0 if status in ("active", "trialing") else 1 if status == "past_due" else 2
    return live, -(sub.get("created") or 0)


def _paid_through(sub: dict) -> str | None:
    """How far the subscription is paid: its current period's end, except while a
    renewal is past due, when the unpaid period has begun and only its start is paid
    (plans.active's grace then counts from the failed renewal). The current period
    lives on the subscription's items since API version basil."""
    items = (sub.get("items") or {}).get("data") or [{}]
    edge = "current_period_start" if sub.get("status") == "past_due" else "current_period_end"
    at = items[0].get(edge) or sub.get(edge)
    return common.to_iso(datetime.datetime.fromtimestamp(at, datetime.timezone.utc)) if at else None


def _sync_locked(list_id: int) -> list[dict]:
    """Store the best subscription; returns them all. A write is compare-and-set on
    plan_rev, so a fetch that another process (admin.py billing-sync) overtook is
    fetched again rather than written over the newer answer."""
    for _ in range(3):
        row = _row(list_id)
        if row is None or not row["stripe_customer"]:
            return []
        # Every subscription counts: the customer exists only because this account bought
        # Pro. simplification: one product per customer; filter by product here if the suite
        # ever sells a second one.
        subs = _subscriptions(row["stripe_customer"])
        best = min(subs, key=_rank) if subs else None
        with db.transaction() as conn:
            wrote = conn.execute(
                "UPDATE lists SET stripe_subscription = ?, plan_status = ?, plan_until = ?, "
                "plan_cancels = ?, plan_rev = plan_rev + 1 WHERE id = ? AND plan_rev = ?",
                (
                    best["id"] if best else "",
                    best.get("status", "") if best else "",
                    _paid_through(best) if best else None,
                    int(bool(best and (best.get("cancel_at_period_end") or best.get("cancel_at")))),
                    list_id,
                    row["plan_rev"],
                ),
            ).rowcount
        if wrote:
            if row["email_verified_at"] and row["email"] != row["stripe_email"]:
                push_email(list_id)  # a change Stripe has not heard about yet, or a failed push
            live = [s for s in subs if s.get("status") in plans.PRO_STATUSES]
            if len(live) > 1:
                logger.warning("List %s has %d live Pro subscriptions: refund the extra in Stripe", list_id, len(live))
            return subs
    raise BillingError("the plan kept changing while it was read")


def sync(list_id: int) -> list[dict]:
    """Store the account's best subscription (live first, then the newest) from Stripe;
    returns every subscription read."""
    with _lock:
        return _sync_locked(list_id)


def catch_up(everyone: bool = False) -> int:
    """Sync the accounts Stripe may have news about that never reached us: hourly,
    every account still marked Pro whose period has ended (a missed renewal); with
    ``everyone`` (daily), every account with a Stripe customer, which also finds a
    purchase whose webhooks all failed. One account's failure is logged and the rest go
    on. Returns how many were tried.
    # simplification: the daily sweep is one Stripe call per customer; use the events
    # API once there are thousands."""
    now = common.to_iso(common.utcnow())
    if everyone:
        ids = [r["id"] for r in db.get_db().execute("SELECT id FROM lists WHERE stripe_customer != ''")]
    else:
        ids = [
            r["id"]
            for r in db.get_db().execute(
                "SELECT id FROM lists WHERE stripe_customer != '' AND plan_status IN "
                f"({', '.join('?' * len(plans.PRO_STATUSES))}) AND plan_until < ?",
                (*plans.PRO_STATUSES, now),
            )
        ]
    for list_id in ids:
        try:
            sync(list_id)
        except Exception:
            logger.warning("Billing catch-up could not sync list %s", list_id)
    return len(ids)


# ── Checkout and the portal ───────────────────────────────────────────────────


def _customer_in(list_id: int, email: str) -> str:
    """The account's Stripe customer, made now if it has none."""
    digest = hashlib.sha256(email.encode()).hexdigest()[:12]
    made = _stripe(
        "POST", "customers", {"email": email, "metadata[list_id]": str(list_id)}, key=f"customer-{list_id}-{digest}"
    )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET stripe_customer = ?, stripe_email = ? "
            "WHERE id = ? AND stripe_customer = '' AND disabled_at IS NULL",
            (made["id"], email, list_id),
        )
        row = conn.execute("SELECT stripe_customer, disabled_at FROM lists WHERE id = ?", (list_id,)).fetchone()
    # admin.py disable and delete mark the account first: a customer made meanwhile is
    # never used (it has no way to pay, so it can charge nothing).
    if row is None or row["disabled_at"] or not row["stripe_customer"]:
        raise BillingError("the account was disabled or deleted")
    return row["stripe_customer"]


def push_email(list_id: int) -> bool:
    """Give the account's Stripe customer its confirmed email, so receipts and billing
    notices follow a changed address. A failure is logged (never the address) and left
    for the next sync, which pushes again while stripe_email differs."""
    with _lock:  # two overlapping changes push one after the other, newest last
        row = _row(list_id)
        if not (row and row["stripe_customer"] and row["email"] and row["email_verified_at"]):
            return True
        if row["email"] == row["stripe_email"]:
            return True
        try:
            _stripe("POST", f"customers/{row['stripe_customer']}", {"email": row["email"]})
        except BillingError:
            logger.warning("Could not update the Stripe customer's email for list %s", list_id)
            return False
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET stripe_email = ? WHERE id = ?", (row["email"], list_id))
        return True


def _price_of(session: dict) -> str:
    items = (session.get("line_items") or {}).get("data") or [{}]
    return (items[0].get("price") or {}).get("id") or ""


def _open_sessions(customer: str) -> list[dict]:
    """Every open Checkout session of the customer, as Stripe has them: one whose
    creation answer never reached us is found here too."""
    page = _stripe(
        "GET",
        "checkout/sessions",
        {"customer": customer, "status": "open", "limit": 100, "expand[]": "data.line_items"},
    )
    return page.get("data") or []


def _close(session_id: str) -> str | None:
    """Expire an open session and answer its status after: expired, or complete when it
    was paid in that instant. Still open is an error: never leave two payable."""
    path = f"checkout/sessions/{session_id}"
    try:
        status = _stripe("POST", f"{path}/expire").get("status")
    except BillingError:
        status = _stripe("GET", path).get("status")
    if status == "open":
        raise BillingError("a previous checkout could not be closed")
    return status


def _open_invoice(customer: str) -> bool:
    return bool(_stripe("GET", "invoices", {"customer": customer, "status": "open", "limit": 1}).get("data"))


def _refuse_if_bought(list_id: int, subs: list[dict]) -> None:
    row = _row(list_id)
    if row is None or row["disabled_at"]:
        raise BillingError("the account is disabled or gone")
    if plans.active(row):
        raise AlreadyPro()
    if any(s.get("status") in plans.PRO_STATUSES + RECOVERABLE for s in subs):
        raise NeedsAttention()
    # An invoice left open (say, by a cancelled subscription) can still be paid: a new
    # subscription beside it could mean two charges.
    if row["stripe_customer"] and _open_invoice(row["stripe_customer"]):
        raise NeedsAttention()


def checkout_url(list_id: int, interval: str, base: str, email: str) -> str:
    """A Stripe Checkout address for Pro, billed by ``interval``, for the confirmed
    ``email`` the caller checked (EmailChanged if another tab changed it since). Asks
    Stripe for the customer's open sessions every time: reuses one for the same price,
    expires the rest, and never leaves two payable."""
    price = paid_settings.stripe_price(interval)
    with _lock:
        _refuse_if_bought(list_id, _sync_locked(list_id))
        row = _row(list_id)
        if row["email"] != email or not row["email_verified_at"]:
            raise EmailChanged()
        # Checkout shows the customer's stored email and does not let it be edited: it must
        # be the one confirmed now, or there is no checkout.
        if row["stripe_customer"] and not push_email(list_id):
            raise BillingError("the customer's email could not be updated")
        customer = row["stripe_customer"] or _customer_in(list_id, email)
        reuse = None
        for held in _open_sessions(customer):
            if reuse is None and _price_of(held) == price:
                reuse = held
            elif _close(held["id"]) == "complete":
                _refuse_if_bought(list_id, _sync_locked(list_id))
        if reuse is not None:
            return _handed_out(list_id, email, reuse)
        params = {
            "mode": "subscription",
            "customer": customer,
            "line_items[0][price]": price,
            "line_items[0][quantity]": "1",
            "managed_payments[enabled]": "true",
            "client_reference_id": str(list_id),
            "success_url": f"{base}/app?pro=welcome",
            "cancel_url": f"{base}/app",
        }
        key = secrets.token_hex(16)
        try:
            session = _stripe("POST", "checkout/sessions", params, key=key)
        except BillingTimeout:
            session = _stripe("POST", "checkout/sessions", params, key=key)  # same key: no duplicate
        return _handed_out(list_id, email, session)


def _handed_out(list_id: int, email: str, session: dict) -> str:
    """The session's address, unless the email changed in another tab while Stripe
    answered (the person confirms the new address first) or the operator disabled the
    account meanwhile: either way the session is closed unseen."""
    row = _row(list_id)
    if row is None or row["disabled_at"] or row["email"] != email:
        _close(session["id"])
        if row is None or row["disabled_at"]:
            raise BillingError("the account was disabled or deleted")
        raise EmailChanged()
    return session["url"]


def payment_paths(list_id: int) -> str:
    """What could still take this account's money, or '': closes its open checkouts
    first, then reads its subscriptions and open invoices from Stripe. admin.py disable
    asks this, since a disabled account's owner can no longer reach Manage billing."""
    with _lock:
        row = _row(list_id)
        if row is None or not row["stripe_customer"]:
            return ""
        for held in _open_sessions(row["stripe_customer"]):
            _close(held["id"])
        live = [s for s in _sync_locked(list_id) if s.get("status") in plans.PRO_STATUSES + RECOVERABLE]
        if live:
            return f"a {live[0]['status']} Pro subscription"
        if _open_invoice(row["stripe_customer"]):
            return "an open invoice"
        return ""


def customer_gone(list_id: int) -> bool:
    """Whether nothing in Stripe can take this account's money any more: its customer
    is deleted in Stripe (which cancels its subscriptions, and no checkout can be made
    for it) and it has no open invoice. admin.py delete asks this before the row, the
    only tie between Stripe and the account, goes."""
    customer = _row(list_id)["stripe_customer"]
    if not customer:
        return True
    if not _stripe("GET", f"customers/{customer}").get("deleted"):
        return False
    return not _open_invoice(customer)


def portal_url(list_id: int, base: str) -> str | None:
    """A Customer Portal address for the account, or None when it has no customer."""
    customer = _row(list_id)["stripe_customer"]
    if not customer:
        return None
    return _stripe("POST", "billing_portal/sessions", {"customer": customer, "return_url": f"{base}/app"})["url"]


# ── The webhook ────────────────────────────────────────────────────────────────


def verify(payload: bytes, header: str, now: float) -> dict:
    """The event in ``payload`` if ``header`` (Stripe-Signature) signs it with the
    webhook secret within the tolerance; else BadSignature."""
    pairs = [part.split("=", 1) for part in header.split(",") if "=" in part]
    stamp = next((v for k, v in pairs if k.strip() == "t"), "")
    signatures = [v.strip() for k, v in pairs if k.strip() == "v1"]
    if not stamp.isdigit() or not signatures or abs(now - int(stamp)) > TOLERANCE_SECONDS:
        raise BadSignature()
    want = hmac.new(
        paid_settings.stripe_webhook_secret().encode(), stamp.encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(want, s) for s in signatures):
        raise BadSignature()
    try:
        event = json.loads(payload)
    except ValueError as e:
        raise BadSignature() from e
    if not isinstance(event, dict):
        raise BadSignature()
    return event


def handle(event: dict) -> None:
    """Sync the account an event is about. Only the type and the customer id are
    read; anything else, or a customer no account owns, changes nothing."""
    if event.get("type") not in HANDLED:
        return
    customer = ((event.get("data") or {}).get("object") or {}).get("customer")
    if not isinstance(customer, str) or not customer:
        return
    row = db.get_db().execute("SELECT id FROM lists WHERE stripe_customer = ?", (customer,)).fetchone()
    if row is not None:
        sync(row["id"])


async def maintain() -> None:
    """When Pro syncs from Stripe: every hour catch up the accounts whose Pro period has
    passed, and every Stripe customer five minutes after start and then once a day
    (catch_up), so a restart never postpones the full sweep. Its own task, so a
    slow Stripe sweep never delays the minute's jobs."""
    await asyncio.sleep(300)
    runs = 0
    while True:
        if syncing():
            try:
                n = await asyncio.to_thread(catch_up, runs % 24 == 0)
                if n:
                    logger.info("Billing caught up %d account(s)", n)
            except Exception:
                logger.exception("The billing catch-up failed")
        runs += 1
        await asyncio.sleep(3600)


NO_CUSTOMER_SQL = "stripe_customer = ''"
