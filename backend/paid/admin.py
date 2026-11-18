"""Paid commands, reports and checks for the operator CLI.

python -m scripts.admin billing-sync <list_id>
python -m scripts.admin comp <list_id or email> [--plan pro|max] [--until YYYY-MM-DD] [--off]
"""

import collections
import datetime
from backend.paid import billing, plans
from backend.paid import caps as paid_caps
from backend import common, db


def _undo_on_failure(list_id: int, check) -> None:
    """Run ``check`` on a list this command just disabled; if it refuses or Stripe fails,
    enable the list again (its owner must keep reaching Manage billing) and stop."""
    from scripts.admin import _log

    try:
        check(list_id)
    except (SystemExit, billing.BillingError) as e:
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET disabled_at = NULL WHERE id = ?", (list_id,))
            _log(conn, "enable", list_id)
        if isinstance(e, SystemExit):
            raise
        raise SystemExit(
            f"List {list_id}: Stripe could not be checked ({e}); it was left enabled. Nothing changed."
        ) from e


def _refuse_while_subscribed(list_id: int) -> None:
    """A disabled list's browsers are signed out, so its owner can no longer reach
    Manage billing: never disable one whose subscription can still charge."""
    customer = (
        db.get_db().execute("SELECT stripe_customer FROM lists WHERE id = ?", (list_id,)).fetchone()["stripe_customer"]
    )
    if not customer:
        return
    if not billing.syncing():
        raise SystemExit(
            f"List {list_id} is a Stripe customer ({customer}); run this with the "
            "app's STRIPE_* variables set so Stripe can be checked. Nothing changed."
        )
    pending = billing.payment_paths(list_id)  # also closes any open checkout
    if pending:
        raise SystemExit(
            f"List {list_id} has {pending} (Stripe customer {customer}): settle it "
            "in Stripe (cancel, refund or void), then disable. Nothing changed."
        )


def _refuse_while_billable(list_id: int) -> None:
    """The list row is the only tie between Stripe and the account: deleting it while
    Stripe could still take money would charge someone nobody can find. So a Stripe
    customer's list is deleted only once that customer is deleted in Stripe (which
    cancels its subscriptions and stops any new checkout) and no invoice is left open."""
    customer = (
        db.get_db().execute("SELECT stripe_customer FROM lists WHERE id = ?", (list_id,)).fetchone()["stripe_customer"]
    )
    if not customer:
        return
    if not billing.syncing():
        raise SystemExit(
            f"List {list_id} is a Stripe customer ({customer}); run this with the "
            "app's STRIPE_* variables set so Stripe can be checked. Nothing was deleted."
        )
    if not billing.customer_gone(list_id):
        raise SystemExit(
            f"List {list_id} is Stripe customer {customer}. In Stripe, void or settle "
            "its open invoices and delete the customer (that cancels its "
            "subscriptions), then delete here. Nothing was deleted."
        )


def cmd_billing_sync(args) -> None:
    """Read the list's subscriptions from Stripe now and store the best one, as the
    webhook does (billing.sync). Needs the app's STRIPE_* variables. A second process:
    if Stripe also calls the app's webhook this second, whichever writes last wins,
    and both read the same Stripe state."""
    from scripts.admin import _require, _log

    _require(args.list_id)
    if not billing.syncing():
        raise SystemExit(
            "Billing is off here: STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are not both set (or OPEN_SIGNUP is off)."
        )
    billing.sync(args.list_id)
    with db.transaction() as tx:
        _log(tx, "billing-sync", args.list_id)
    row = db.get_db().execute(f"SELECT {paid_caps.PLAN_COLUMNS} FROM lists WHERE id = ?", (args.list_id,)).fetchone()
    print(
        f"List {args.list_id}: Stripe status {row['plan_status'] or '-'}, until "
        f"{row['plan_until'] or '-'}; Pro {'yes' if plans.active(row) else 'no'}"
    )


def cmd_comp(args) -> int:
    """Grant a list Pro or Max for free (the operator's gift to testers or friends), until
    a date or for good, or take the grant back with --off. Stripe is not involved; a paid
    subscription the list also has is left alone, and Max outranks it. Logged in admin_log."""
    from scripts.admin import _log, _list_ref

    who = args.who.strip()
    if "@" not in who:
        rows = db.get_db().execute("SELECT id, email FROM lists WHERE id = ?", (_list_ref(who),)).fetchall()
    else:
        rows = db.get_db().execute("SELECT id, email FROM lists WHERE lower(email) = lower(?)", (who,)).fetchall()
    if len(rows) != 1:
        found = ", ".join(str(r["id"]) for r in rows) or "none"
        print(f"{len(rows)} lists match {who!r} (ids: {found}); give the list id instead.")
        return 1
    list_id = rows[0]["id"]
    if args.off:
        until = None
    elif args.until:
        until = common.to_iso(datetime.datetime.combine(args.until, datetime.time(), datetime.timezone.utc))
    else:
        until = FOREVER
    with db.transaction() as tx:
        tx.execute("UPDATE lists SET pro_comp_until = ?, comp_plan = ? WHERE id = ?", (until, args.plan, list_id))
        if until is not None:  # a tier outranks "unconfirmed": a trial page no longer comes down
            tx.execute("UPDATE sites SET expires_at = NULL WHERE list_id = ?", (list_id,))
        _log(tx, "comp off" if args.off else "comp", list_id)
    if until is None:
        print(f"List {list_id}: the free grant is gone (a paid subscription, if any, stays).")
    else:
        print(
            f"List {list_id}: on {args.plan.title()} for free "
            f"{'for good' if until == FOREVER else 'until ' + until[:10]}."
        )
    return 0


FOREVER = "9999-12-31T00:00:00.000Z"


def register(command, day) -> None:
    command("billing-sync", cmd_billing_sync, "re-read the list's Pro subscription from Stripe")
    p = command("comp", cmd_comp, "give a list Pro or Max for free (or take it back with --off)", list_id=False)
    p.add_argument("who", help="the list's id or account number, or the email on it")
    p.add_argument("--plan", choices=("pro", "max"), default="pro", help="what to grant (pro)")
    p.add_argument("--until", type=day, metavar="YYYY-MM-DD", help="end the grant on this day")
    p.add_argument("--off", action="store_true", help="take the grant back")


def stats(conn) -> dict:
    rows = conn.execute(
        f"SELECT {paid_caps.PLAN_COLUMNS} FROM lists WHERE plan_status != '' OR pro_comp_until IS NOT NULL"
    ).fetchall()
    return {
        # Accounts entitled to Pro or better right now (plans.active), those on Max, and
        # every stored Stripe status.
        "pro_now": sum(plans.active(r) for r in rows),
        "pro_comp": sum(plans.pro_source(r) == "comp" for r in rows),
        "max_now": sum(plans.of(r) == "max" for r in rows),
        "plan_statuses": dict(collections.Counter(r["plan_status"] for r in rows if r["plan_status"])),
    }


def print_stats(data) -> None:
    print(
        f"Pro now: {data['pro_now']} ({data['pro_comp']} free, {data['max_now']} on Max)"
        "   Stripe statuses: " + ("  ".join(f"{s} {n}" for s, n in data["plan_statuses"].items()) or "-")
    )


def details(conn, list_id: int) -> dict:
    plan = conn.execute(
        f"SELECT {paid_caps.PLAN_COLUMNS}, plan_cancels, stripe_customer, stripe_subscription FROM lists WHERE id = ?",
        (list_id,),
    ).fetchone()
    return {
        # Pro (billing.py); the Stripe ids are for finding the account in Stripe (refunds).
        "pro": plans.active(plan),
        "tier": plans.of(plan),
        "plan": dict(plan),
    }


def print_details(data) -> None:
    p = data["plan"]
    if p["pro_comp_until"]:
        print(f"Free {p['comp_plan'].title()} granted until {p['pro_comp_until']} (comp)")
    print(
        f"Plan: {data['tier'] or 'free'}  (Stripe status {p['plan_status'] or '-'}, "
        f"until {p['plan_until'] or '-'}{', cancelled' if p['plan_cancels'] else ''}; "
        f"customer {p['stripe_customer'] or '-'}, subscription {p['stripe_subscription'] or '-'})"
    )
