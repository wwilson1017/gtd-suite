"""Plan commands, reports and checks for the operator CLI.

python -m scripts.admin comp <list_id or email> [--plan pro|max] [--until YYYY-MM-DD] [--off]
"""

import collections
import datetime
from backend.plans import billing, plans
from backend.plans import caps as paid_caps
from backend.plans import settings as paid_settings
from backend import common, db


def _undo_on_failure(list_id: int, check) -> None:
    """Run ``check`` on a list this command just disabled; if it refuses or billing fails,
    enable the list again (its owner must keep reaching their billing) and stop."""
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
            f"List {list_id}: billing could not be checked ({e}); it was left enabled. Nothing changed."
        ) from e


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
        tx.execute(
            "UPDATE lists SET pro_comp_until = ?, comp_plan = ?, comp_source = '' WHERE id = ?",
            (until, args.plan, list_id),
        )
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


def springform_comp_in(conn, list_id: int) -> None:
    """Max for good for an account a Springform install connected (connect.approve, hosted
    only), inside the caller's transaction. At most once per account (springform_at, never
    cleared, so neither a later hand grant nor comp --off makes it grantable again); a live
    Max grant is left as is."""
    row = conn.execute(f"SELECT {paid_caps.PLAN_COLUMNS}, springform_at FROM lists WHERE id = ?", (list_id,)).fetchone()
    if row["springform_at"] or (plans.pro_source(row) == "comp" and row["comp_plan"] == "max"):
        return
    conn.execute(
        "UPDATE lists SET pro_comp_until = ?, comp_plan = 'max', comp_source = 'springform', springform_at = ? "
        "WHERE id = ?",
        (FOREVER, common.now_iso(), list_id),
    )
    conn.execute("UPDATE sites SET expires_at = NULL WHERE list_id = ?", (list_id,))


def register(command, day) -> None:
    billing.admin_commands(command)
    p = command("comp", cmd_comp, "give a list Pro or Max for free (or take it back with --off)", list_id=False)
    p.add_argument("who", help="the list's id or account number, or the email on it")
    p.add_argument("--plan", choices=("pro", "max"), default="pro", help="what to grant (pro)")
    p.add_argument("--until", type=day, metavar="YYYY-MM-DD", help="end the grant on this day")
    p.add_argument("--off", action="store_true", help="take the grant back")


def stats(conn) -> dict:
    # While the suite is free a confirmed email is Max too (plans.of), so those rows count.
    free = " OR email_verified_at IS NOT NULL" if paid_settings.free_max() else ""
    rows = conn.execute(
        f"SELECT {paid_caps.PLAN_COLUMNS}, comp_source FROM lists "
        f"WHERE plan_status != '' OR pro_comp_until IS NOT NULL{free}"
    ).fetchall()
    return {
        # Accounts entitled to Pro or better right now (plans.active), those on Max, and
        # every stored Stripe status.
        "pro_now": sum(plans.active(r) for r in rows),
        "pro_comp": sum(plans.pro_source(r) == "comp" for r in rows),
        "max_now": sum(plans.of(r) == "max" for r in rows),
        # Max given by a Springform connect, live now (springform_comp_in).
        "max_springform": sum(plans.of(r) == "max" and r["comp_source"] == "springform" for r in rows),
        "plan_statuses": dict(collections.Counter(r["plan_status"] for r in rows if r["plan_status"])),
    }


def print_stats(data) -> None:
    print(
        f"Pro now: {data['pro_now']} ({data['pro_comp']} free, {data['max_now']} on Max)"
        f"   Max from Springform: {data['max_springform']}"
        "   Stripe statuses: " + ("  ".join(f"{s} {n}" for s, n in data["plan_statuses"].items()) or "-")
    )


def details(conn, list_id: int) -> dict:
    plan = conn.execute(
        f"SELECT {paid_caps.PLAN_COLUMNS}, comp_source, plan_cancels, stripe_customer, stripe_subscription "
        "FROM lists WHERE id = ?",
        (list_id,),
    ).fetchone()
    return {
        # The plan; the payment service's ids are for finding the account there.
        "pro": plans.active(plan),
        "tier": plans.of(plan),
        "plan": dict(plan),
    }


def print_details(data) -> None:
    p = data["plan"]
    if p["pro_comp_until"]:
        by = "Springform connect" if p["comp_source"] == "springform" else "comp"
        print(f"Free {p['comp_plan'].title()} granted until {p['pro_comp_until']} ({by})")
    print(
        f"Plan: {data['tier'] or 'free'}  (Stripe status {p['plan_status'] or '-'}, "
        f"until {p['plan_until'] or '-'}{', cancelled' if p['plan_cancels'] else ''}; "
        f"customer {p['stripe_customer'] or '-'}, subscription {p['stripe_subscription'] or '-'})"
    )
