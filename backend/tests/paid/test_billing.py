"""Pro (billing.py): derived from Stripe's state by a sync, sold through Checkout,
managed in the portal, told about changes by a signed webhook. Stripe is never
called: billing._stripe is replaced by a small fake that keeps subscriptions and
sessions and records every call."""

import datetime
import json
import logging
import threading

import pytest

from backend.paid import caps as paid_caps
from backend.paid import plans
from backend.paid import billing
from backend import boards, common, db, notes, recordings, service, sites
from backend.common import ValidationError
from backend.tests.test_admin import run  # noqa: F401 (fixture)

SECRET = "whsec_test"
# Computed outside the code under test: HMAC-SHA256(SECRET, b"1700000000." + BODY).
BODY = b'{"type":"customer.subscription.updated","data":{"object":{"customer":"cus_1"}}}'
SIGNATURE = "821e4e072412b30f1313f3c8959f50dad4c84d1483b587d9edc9e664e7216816"


class FakeStripe:
    """Enough of Stripe for billing.py: customers (idempotent by key), subscriptions,
    Checkout sessions (open → expired/complete) and portal sessions."""

    def __init__(self):
        self.calls, self.subs, self.sessions, self.customers = [], [], {}, {}
        self.expire_fails = False  # the session completes in the instant we expire it
        self.expire_errors = False  # expiring fails and the session stays open
        self.on_list = None  # called while subscriptions are being read
        self.lose_create = False  # Stripe makes the session, but its answer is lost
        self.deleted, self.invoices = set(), []  # customers deleted in Stripe; open invoices

    def __call__(self, method, path, data=None, key=None):
        self.calls.append((method, path, dict(data or {}), key))
        if path == "customers":
            return {"id": self.customers.setdefault(key, f"cus_{len(self.customers) + 1}")}
        if path.startswith("customers/") and method == "GET":
            cid = path.split("/")[1]
            return {"id": cid, "deleted": True} if cid in self.deleted else {"id": cid}
        if path.startswith("customers/"):
            return {"id": path.split("/")[1], "email": data["email"]}
        if path == "invoices":
            return {"data": [i for i in self.invoices if i["customer"] == data["customer"]]}
        if path == "subscriptions":
            found = [dict(s) for s in self.subs if s["customer"] == data["customer"]]
            if self.on_list:  # after the answer is read, before it reaches the caller
                self.on_list()
            return {"data": found, "has_more": False}
        if path == "checkout/sessions" and method == "GET":
            return {
                "data": [
                    self._session(s)
                    for s in self.sessions.values()
                    if s["customer"] == data["customer"] and s["status"] == data["status"]
                ]
            }
        if path == "checkout/sessions":
            sid = f"cs_{len(self.sessions) + 1}"
            self.sessions[sid] = {
                "id": sid,
                "status": "open",
                "url": f"https://pay.example/{sid}",
                "price": data["line_items[0][price]"],
                "customer": data["customer"],
            }
            if self.lose_create:
                raise billing.BillingError("the connection dropped")
            return self._session(self.sessions[sid])
        if path.startswith("checkout/sessions/"):
            sid = path.split("/")[2]
            held = self.sessions[sid]
            if path.endswith("/expire"):
                if self.expire_fails:
                    held["status"] = "complete"
                    raise billing.BillingError("Stripe answered 400")
                if self.expire_errors:
                    raise billing.BillingTimeout("Stripe timed out")
                held["status"] = "expired"
            return self._session(held)
        if path == "billing_portal/sessions":
            return {"url": f"https://portal.example/{data['customer']}"}
        raise AssertionError(f"unexpected Stripe call {method} {path}")

    @staticmethod
    def _session(held):
        return {**held, "line_items": {"data": [{"price": {"id": held["price"]}}]}}

    def sub(self, customer, status, created, days=30, cancels=False, started=-1):
        at = lambda d: int((common.utcnow() + datetime.timedelta(days=d)).timestamp())  # noqa: E731
        self.subs.append(
            {
                "id": f"sub_{len(self.subs) + 1}",
                "customer": customer,
                "status": status,
                "created": created,
                "cancel_at_period_end": cancels,
                "items": {"data": [{"current_period_start": at(started), "current_period_end": at(days)}]},
            }
        )

    def posts(self, path):
        return [c for c in self.calls if c[0] == "POST" and c[1] == path]


@pytest.fixture()
def stripe(todo_db, monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(billing, "_stripe", fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("STRIPE_PRICE_MONTH", "price_month")
    monkeypatch.setenv("STRIPE_PRICE_YEAR", "price_year")
    return fake


def _confirm(list_id, email="pat@example.com"):
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET email = ?, email_verified_at = ? WHERE id = ?",
            (email, common.to_iso(common.utcnow()), list_id),
        )


def _plan(list_id, status, days=30, customer=""):
    until = common.to_iso(common.utcnow() + datetime.timedelta(days=days))
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET plan_status = ?, plan_until = ?, stripe_customer = ? WHERE id = ?",
            (status, until, customer, list_id),
        )


def _row(list_id):
    return db.get_db().execute("SELECT * FROM lists WHERE id = ?", (list_id,)).fetchone()


# ── Deriving Pro and the caps ─────────────────────────────────────────────────


def test_pro_is_a_live_status_within_its_period_and_three_days_of_grace(L):
    _plan(L, "active")
    assert plans.active(_row(L))
    _plan(L, "past_due", days=-2)  # Stripe is retrying the card: still Pro
    assert plans.active(_row(L))
    _plan(L, "active", days=-4)  # a renewal we never heard about: lapsed
    assert not plans.active(_row(L))
    for status in ("canceled", "unpaid", "incomplete", ""):
        _plan(L, status)
        assert not plans.active(_row(L))


@pytest.mark.parametrize(
    "module,name,call",
    [
        (service, "caps_for", lambda L: service._check_cap(db.get_db(), L, "todos")),
        (notes, "note_cap_for", lambda L: notes._check_cap(db.get_db(), L)),
        (boards, "board_caps_for", lambda L: boards._check_cap(db.get_db(), L, "boards")),
        (recordings, "recording_cap_for", lambda L: recordings._check_cap(db.get_db(), L)),
    ],
)
def test_every_apps_cap_check_asks_with_pro(L, monkeypatch, module, name, call):
    seen = []
    real = getattr(common, name)
    monkeypatch.setattr(
        common, name, lambda verified, hosted, plan=None: seen.append(plan) or real(verified, hosted, plan)
    )
    call(L)
    _plan(L, "active")
    call(L)
    assert seen == [None, "pro"]


def test_the_sites_cap_check_asks_with_the_tier(L, monkeypatch):
    seen = []
    real = common.site_caps_for
    monkeypatch.setattr(
        common, "site_caps_for", lambda verified, hosted, tier=None: seen.append(tier) or real(verified, hosted, tier)
    )
    sites._check_cap(db.get_db(), L, "page")
    _plan(L, "active")
    sites._check_cap(db.get_db(), L, "page")
    assert seen == [None, "pro"]


def _comp(list_id, plan, days=30):
    until = common.to_iso(common.utcnow() + datetime.timedelta(days=days))
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET pro_comp_until = ?, comp_plan = ? WHERE id = ?", (until, plan, list_id))


def test_the_tier_is_the_highest_that_applies(L):
    assert plans.of(_row(L)) is None
    _comp(L, "pro")
    assert plans.of(_row(L)) == "pro" and plans.pro_source(_row(L)) == "comp"
    _plan(L, "active")
    assert plans.of(_row(L)) == "pro" and plans.pro_source(_row(L)) == "stripe"
    _comp(L, "max")  # a Pro subscription plus a Max grant is Max, from the grant
    assert plans.of(_row(L)) == "max" and plans.pro_source(_row(L)) == "comp"
    assert plans.active(_row(L))
    _comp(L, "max", days=-1)  # the grant ended: the subscription still holds
    assert plans.of(_row(L)) == "pro" and plans.pro_source(_row(L)) == "stripe"
    _plan(L, "canceled")
    assert plans.of(_row(L)) is None


def test_pro_caps_and_the_session(stripe, new_list):
    made = new_list()
    L, c = made["list_id"], made["client"]
    assert common.site_caps_for(True, True, "pro") == paid_caps.SITE_PRO_CAPS == (2_500, 2_500)
    assert common.site_caps_for(True, True, "max") == paid_caps.SITE_MAX_CAPS == common.SITE_SELF_HOST_CAPS
    assert [
        common.file_quota_for(*a)
        for a in ((False, True), (True, True), (True, True, "pro"), (True, True, "max"), (False, False))
    ] == [0, 500_000_000, 10_000_000_000, 100_000_000_000, 100_000_000_000]
    assert common.caps_for(True, True, "pro") == common.SELF_HOST_CAPS
    _confirm(L)
    _plan(L, "active", customer="cus_9")
    session = c.get("/api/app/session").json()
    assert session["caps"]["todos"] == common.SELF_HOST_CAPS[0]
    assert session["plan"]["pro"] and session["plan"]["manageable"] and not session["plan"]["cancels"]
    assert sites.caps(L) == {
        "pages": 2500,
        "links": 2500,
        "page_bytes": 2_000_000,
        "site_bytes": 250_000_000,
        "storage": 10_000_000_000,
        "storage_used": 0,
        "files_per_site": 1000,
        "short_names": 10,
    }
    assert c.get("/api/config").json()["billing"] is True


def test_a_lapsed_account_keeps_its_pages_and_hears_about_pro_at_the_cap(stripe, L):
    _confirm(L)
    _plan(L, "active")
    made = [sites.publish(L, f"# Page {i}") for i in range(common.SITE_VERIFIED_CAPS[0] + 1)]
    _plan(L, "canceled")
    last = made[-1]
    sites.update(L, last["id"], content="# Still mine")  # updating is never capped
    assert sites.get_site(L, last["id"])["content"] == "# Still mine"
    assert sites.lookup(last["address"].rsplit("/", 1)[1]) is not None  # still served
    with pytest.raises(ValidationError) as refused:
        sites.publish(L, "# One more")
    assert "Pro raises it to 2500" in str(refused.value) and "Nothing was changed." in str(refused.value)


def test_no_upsell_where_pro_is_not_on_sale(L):
    _confirm(L)
    for i in range(common.SITE_VERIFIED_CAPS[0]):
        sites.publish(L, f"# Page {i}")
    with pytest.raises(ValidationError) as refused:
        sites.publish(L, "# One more")
    assert "Pro" not in str(refused.value)


# ── The webhook signature ─────────────────────────────────────────────────────


def test_the_signature_matches_an_independently_computed_one(stripe):
    header = f"t=1700000000,v1={SIGNATURE}"
    assert billing.verify(BODY, header, 1700000010)["type"] == "customer.subscription.updated"
    # A second v1 (Stripe rolls secrets) is fine as long as one matches.
    assert billing.verify(BODY, f"t=1700000000,v1={'0' * 64},v1={SIGNATURE}", 1700000010)
    for body, head, now in (
        (BODY + b" ", header, 1700000010),
        (BODY, f"t=1700000000,v1={'0' * 64}", 1700000010),
        (BODY, header, 1700000301),  # older than the tolerance
        (BODY, "v1=" + SIGNATURE, 1700000010),
    ):
        with pytest.raises(billing.BadSignature):
            billing.verify(body, head, now)


def test_the_webhook_route(stripe, client, new_list, monkeypatch):
    made = new_list()
    L = made["list_id"]
    _plan(L, "", customer="cus_1")
    stripe.sub("cus_1", "active", created=100)
    monkeypatch.setattr(common, "utcnow", lambda: datetime.datetime.fromtimestamp(1700000005, datetime.timezone.utc))
    headers = {"Stripe-Signature": f"t=1700000000,v1={SIGNATURE}", "Content-Type": "application/json"}
    assert client.post("/api/stripe/webhook", content=BODY, headers=headers).json() == {"ok": True}
    assert _row(L)["plan_status"] == "active" and _row(L)["stripe_subscription"] == "sub_1"
    bad = {**headers, "Stripe-Signature": f"t=1700000000,v1={'1' * 64}"}
    assert client.post("/api/stripe/webhook", content=BODY, headers=bad).status_code == 400
    big = b"{" + b" " * (256 * 1024) + b"}"
    assert client.post("/api/stripe/webhook", content=big, headers=headers).status_code == 413
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
    assert client.post("/api/stripe/webhook", content=BODY, headers=headers).status_code == 404


# ── Sync ──────────────────────────────────────────────────────────────────────


def _event(kind, customer="cus_1"):
    return {"type": kind, "data": {"object": {"customer": customer}}}


def test_sync_picks_the_live_subscription_whatever_order_events_come_in(stripe, L):
    _plan(L, "", customer="cus_1")
    stripe.sub("cus_1", "canceled", created=50)
    stripe.sub("cus_1", "active", created=100, cancels=True)
    for order in (
        ("checkout.session.completed", "customer.subscription.created"),
        ("customer.subscription.created", "checkout.session.completed"),
    ):
        _plan(L, "", customer="cus_1")
        for kind in order:
            billing.handle(_event(kind))
        row = _row(L)
        assert (row["plan_status"], row["stripe_subscription"], row["plan_cancels"]) == ("active", "sub_2", 1)
    # A late `deleted` for the OLD subscription changes nothing: the sync reads Stripe.
    billing.handle(_event("customer.subscription.deleted"))
    assert plans.active(_row(L))


def test_sync_ignores_strangers_and_warns_about_two_live_subscriptions(stripe, L, caplog):
    _plan(L, "", customer="cus_1")
    billing.handle(_event("customer.subscription.updated", customer="cus_unknown"))
    billing.handle({"type": "charge.refunded", "data": {"object": {"customer": "cus_1"}}})
    assert stripe.calls == []
    stripe.sub("cus_1", "active", created=100)
    stripe.sub("cus_1", "active", created=200)
    with caplog.at_level(logging.WARNING, logger="backend.billing"):
        billing.sync(L)
    assert _row(L)["stripe_subscription"] == "sub_2"
    assert "2 live Pro subscriptions" in caplog.text


def test_catch_up_syncs_only_accounts_whose_pro_period_has_passed(stripe, todo_db):
    from backend import lists

    ids = [lists.create_list("UTC")["list_id"] for _ in range(4)]
    _plan(ids[0], "active", days=-1, customer="cus_a")  # passed: sync it
    _plan(ids[1], "active", days=10, customer="cus_b")  # current: leave it
    _plan(ids[2], "canceled", days=-1, customer="cus_c")  # not Pro-like: leave it
    _plan(ids[3], "past_due", days=-1, customer="cus_d")  # passed: sync it
    stripe.sub("cus_a", "active", created=1)
    assert billing.catch_up() == 2
    synced = [c[2]["customer"] for c in stripe.calls if c[1] == "subscriptions"]
    assert synced == ["cus_a", "cus_d"]
    assert plans.active(_row(ids[0])) and _row(ids[3])["plan_status"] == ""


# ── Checkout and Manage billing ───────────────────────────────────────────────


def test_checkout_refusals(stripe, new_list, monkeypatch):
    made = new_list()
    c, L = made["client"], made["list_id"]
    res = c.post("/api/app/billing/checkout", json={"interval": "year"})
    assert res.status_code == 409 and "Confirm your email" in res.json()["detail"]
    _confirm(L)
    assert c.post("/api/app/billing/checkout", json={"interval": "week"}).status_code == 422
    monkeypatch.delenv("STRIPE_PRICE_YEAR")
    assert c.post("/api/app/billing/checkout", json={"interval": "year"}).status_code == 404
    assert c.get("/api/config").json()["billing"] is False
    monkeypatch.setenv("STRIPE_PRICE_YEAR", "price_year")
    _plan(L, "active", customer="cus_1")
    stripe.sub("cus_1", "active", created=1)
    res = c.post("/api/app/billing/checkout", json={"interval": "year"})
    assert res.status_code == 409 and "on Pro already" in res.json()["detail"]
    assert res.headers["cache-control"] == "no-store"


def test_checkout_makes_one_customer_and_reuses_or_replaces_its_session(stripe, new_list):
    made = new_list()
    c, L = made["client"], made["list_id"]
    _confirm(L)
    first = c.post("/api/app/billing/checkout", json={"interval": "year"})
    assert first.status_code == 200 and first.json()["url"] == "https://pay.example/cs_1"
    ((_, _, sent, key),) = stripe.posts("checkout/sessions")
    assert sent["managed_payments[enabled]"] == "true" and sent["mode"] == "subscription"
    assert sent["line_items[0][price]"] == "price_year" and sent["customer"] == "cus_1"
    assert sent["client_reference_id"] == str(L) and sent["success_url"].endswith("/app?pro=welcome")
    assert not {"automatic_tax[enabled]", "payment_method_types[0]", "customer_email"} & sent.keys()
    assert key  # an idempotency key on every creation
    # The same price again: the open session comes back, nothing new is made.
    assert c.post("/api/app/billing/checkout", json={"interval": "year"}).json()["url"].endswith("cs_1")
    assert len(stripe.posts("checkout/sessions")) == 1 and len(stripe.posts("customers")) == 1
    # The other price: the first is expired before the second is made.
    assert c.post("/api/app/billing/checkout", json={"interval": "month"}).json()["url"].endswith("cs_2")
    assert stripe.sessions["cs_1"]["status"] == "expired"


def test_a_returning_customer_with_a_cancelled_subscription_gets_the_same_open_session(stripe, L):
    _confirm(L)
    _plan(L, "canceled", customer="cus_1")
    stripe.sub("cus_1", "canceled", created=1)
    one = billing.checkout_url(L, "month", "https://sites.example", _row(L)["email"])
    two = billing.checkout_url(L, "month", "https://sites.example", _row(L)["email"])
    assert one == two and len(stripe.posts("checkout/sessions")) == 1


def test_a_session_paid_while_being_replaced_is_not_doubled(stripe, L):
    _confirm(L)
    billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"])
    stripe.expire_fails = True  # paid in the instant we expire it
    stripe.sub("cus_1", "active", created=1)
    with pytest.raises(billing.AlreadyPro):
        billing.checkout_url(L, "month", "https://sites.example", _row(L)["email"])
    assert len(stripe.posts("checkout/sessions")) == 1


def test_two_checkouts_at_once_open_one_session(stripe, L):
    _confirm(L)
    urls = []
    threads = [
        threading.Thread(
            target=lambda: urls.append(billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"]))
        )
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert urls[0] == urls[1] and len(stripe.posts("checkout/sessions")) == 1


def test_manage_billing_needs_a_customer(stripe, new_list, monkeypatch):
    made = new_list()
    c, L = made["client"], made["list_id"]
    assert c.post("/api/app/billing/manage").status_code == 409
    _plan(L, "canceled", customer="cus_7")
    assert c.post("/api/app/billing/manage").json() == {"url": "https://portal.example/cus_7"}
    # Selling stopped, managing goes on.
    monkeypatch.delenv("STRIPE_PRICE_MONTH")
    assert c.post("/api/app/billing/manage").status_code == 200
    assert c.get("/api/app/session").json()["plan"]["manageable"] is True
    monkeypatch.delenv("STRIPE_SECRET_KEY")
    assert c.post("/api/app/billing/manage").status_code == 404


def test_webhook_bodies_reach_no_log(stripe, client, new_list, monkeypatch, caplog):
    made = new_list()
    _plan(made["list_id"], "", customer="cus_1")
    body = json.dumps(
        {
            "type": "customer.subscription.updated",
            "data": {"object": {"customer": "cus_1", "email": "secret@example.com"}},
        }
    ).encode()
    monkeypatch.setattr(billing, "verify", lambda payload, header, now: json.loads(payload))
    with caplog.at_level(logging.DEBUG):
        assert client.post("/api/stripe/webhook", content=body).status_code == 200
    assert "secret@example.com" not in caplog.text


# ── The operator's command line ───────────────────────────────────────────────


def test_admin_counts_shows_and_syncs_pro(stripe, L, run, monkeypatch):
    _plan(L, "active", customer="cus_1")
    code, out = run("stats", "--json")
    assert code == 0 and json.loads(out)["pro_now"] == 1 and json.loads(out)["plan_statuses"] == {"active": 1}
    code, out = run("show", L, "--json")
    shown = json.loads(out)
    assert shown["pro"] is True and shown["plan"]["stripe_customer"] == "cus_1"
    stripe.sub("cus_1", "canceled", created=1)
    code, out = run("billing-sync", L)
    assert code == 0 and "Pro no" in out and _row(L)["plan_status"] == "canceled"
    monkeypatch.delenv("STRIPE_SECRET_KEY")
    with pytest.raises(SystemExit) as off:
        run("billing-sync", L)
    assert "Billing is off" in str(off.value)


# ── Review round: never two payable things at once, and no paid account left behind ──


def test_a_session_that_will_not_close_is_not_replaced(stripe, L):
    _confirm(L)
    billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"])
    stripe.expire_errors = True
    with pytest.raises(billing.BillingError):
        billing.checkout_url(L, "month", "https://sites.example", _row(L)["email"])
    assert len(stripe.posts("checkout/sessions")) == 1 and stripe.sessions["cs_1"]["status"] == "open"


@pytest.mark.parametrize("status", ["unpaid", "incomplete", "paused"])
def test_a_subscription_that_can_still_be_paid_goes_to_manage_billing(stripe, new_list, status):
    made = new_list()
    c, L = made["client"], made["list_id"]
    _confirm(L)
    _plan(L, "", customer="cus_1")
    stripe.sub("cus_1", status, created=1)
    res = c.post("/api/app/billing/checkout", json={"interval": "month"})
    assert res.status_code == 409 and "Manage billing" in res.json()["detail"]
    assert stripe.posts("checkout/sessions") == []


def test_the_daily_sweep_finds_a_purchase_whose_webhooks_all_failed(stripe, todo_db):
    from backend import lists

    paid, pro = (lists.create_list("UTC")["list_id"] for _ in range(2))
    _plan(paid, "", customer="cus_p")  # bought, but no event ever arrived
    _plan(pro, "active", days=10, customer="cus_q")
    stripe.sub("cus_p", "active", created=1)
    stripe.sub("cus_q", "active", created=1)
    assert billing.catch_up() == 0  # the hourly sweep: nothing has passed its period
    assert billing.catch_up(everyone=True) == 2
    assert plans.active(_row(paid))


def test_back_from_checkout_syncs_now(stripe, new_list):
    made = new_list()
    c, L = made["client"], made["list_id"]
    _plan(L, "", customer="cus_1")
    stripe.sub("cus_1", "active", created=1)
    assert c.post("/api/app/billing/sync").json() == {"pro": True, "status": "active"}


def test_a_sync_overtaken_by_another_process_reads_again(stripe, L):
    _plan(L, "", customer="cus_1")
    stripe.sub("cus_1", "active", created=1)
    overtaken = []

    def meanwhile():
        # The first read: another process (admin.py billing-sync) writes a newer answer.
        if not overtaken:
            overtaken.append(True)
            stripe.subs[0]["status"] = "canceled"
            with db.transaction() as conn:
                conn.execute("UPDATE lists SET plan_status = 'canceled', plan_rev = plan_rev + 1 WHERE id = ?", (L,))

    stripe.on_list = meanwhile
    billing.sync(L)
    assert _row(L)["plan_status"] == "canceled"  # read again, not the stale "active"
    assert len([c for c in stripe.calls if c[1] == "subscriptions"]) == 2


def test_a_failed_renewal_keeps_pro_three_days_from_the_renewal_not_a_whole_period(stripe, L, freeze):
    freeze("2026-10-14T12:00:00")
    _plan(L, "", customer="cus_1")
    # A yearly renewal failed four days ago: the new (unpaid) period runs a year.
    stripe.sub("cus_1", "past_due", created=1, days=361, started=-4)
    billing.sync(L)
    assert _row(L)["plan_until"] == "2026-10-10T12:00:00.000Z"  # paid through the failed renewal
    assert not plans.active(_row(L))
    freeze("2026-10-12T12:00:00")  # two days after the failure: still in the grace
    assert plans.active(_row(L))


def test_receipts_follow_a_confirmed_email(stripe, L):
    _confirm(L, "old@example.com")
    _plan(L, "canceled", customer="cus_1")
    stripe.sub("cus_1", "canceled", created=1)
    _confirm(L, "new@example.com")
    billing.checkout_url(L, "month", "https://sites.example", _row(L)["email"])
    assert ("POST", "customers/cus_1", {"email": "new@example.com"}, None) in stripe.calls


def test_a_failed_email_push_is_retried_by_the_next_sync(stripe, L):
    _confirm(L, "old@example.com")
    _plan(L, "active", customer="cus_1")
    stripe.sub("cus_1", "active", created=1)
    _confirm(L, "new@example.com")
    real = stripe.__call__

    def down(method, path, data=None, key=None):
        if path == "customers/cus_1":
            raise billing.BillingError("Stripe answered 503")
        return real(method, path, data, key)

    billing._stripe = down
    billing.push_email(L)  # the confirmation's push fails
    assert _row(L)["stripe_email"] == ""
    billing._stripe = stripe
    billing.sync(L)
    assert ("POST", "customers/cus_1", {"email": "new@example.com"}, None) in stripe.calls
    assert _row(L)["stripe_email"] == "new@example.com"
    stripe.calls.clear()
    billing.sync(L)  # pushed once, not on every sync
    assert not any(c[1] == "customers/cus_1" for c in stripe.calls)


def test_a_session_whose_answer_was_lost_is_found_and_reused(stripe, L):
    _confirm(L)
    stripe.lose_create = True
    with pytest.raises(billing.BillingError):
        billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"])
    stripe.lose_create = False
    # Stripe made it; the next try finds it instead of making a second payable one.
    assert billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"]) == "https://pay.example/cs_1"
    assert len(stripe.posts("checkout/sessions")) == 1


def test_cleanup_never_removes_a_stripe_customer(stripe, todo_db, freeze):
    from backend import cleanup, lists

    freeze("2026-01-01T00:00:00")
    kept, gone = (lists.create_list("UTC")["list_id"] for _ in range(2))
    _plan(kept, "", customer="cus_9")  # opened checkout, cleared its email, made nothing
    freeze("2026-03-01T00:00:00")
    assert cleanup.delete_unused_lists() == 1
    assert _row(kept) is not None and _row(gone) is None


def test_a_stripe_customer_is_deleted_only_once_stripe_can_take_nothing(stripe, L, run, monkeypatch):
    _plan(L, "canceled", customer="cus_1")
    delete = ("delete", L, f"--yes-delete-list-{L}", "--no-snapshot")
    with pytest.raises(SystemExit) as refused:
        run(*delete)  # the customer still exists in Stripe
    assert "delete the customer" in str(refused.value) and _row(L) is not None
    stripe.deleted.add("cus_1")
    stripe.invoices.append({"id": "in_1", "customer": "cus_1", "status": "open"})
    with pytest.raises(SystemExit):
        run(*delete)  # an open invoice could still be paid
    stripe.invoices.clear()
    monkeypatch.delenv("STRIPE_SECRET_KEY")  # Stripe cannot be asked: refuse rather than guess
    with pytest.raises(SystemExit) as unchecked:
        run(*delete)
    assert "so Stripe can be checked" in str(unchecked.value)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    assert run("delete", L)[0] == 1 and _row(L) is not None  # no flag: nothing asked or done
    assert run(*delete)[0] == 0 and _row(L) is None


def test_checkout_uses_the_email_it_checked(stripe, L):
    _confirm(L, "old@example.com")
    with db.transaction() as conn:  # another tab changes the address after the check
        conn.execute("UPDATE lists SET email = 'new@example.com', email_verified_at = NULL WHERE id = ?", (L,))
    with pytest.raises(billing.EmailChanged):
        billing.checkout_url(L, "month", "https://sites.example", "old@example.com")
    assert stripe.posts("customers") == [] and stripe.posts("checkout/sessions") == []


def test_an_email_changed_while_stripe_answered_closes_the_session(stripe, L):
    _confirm(L, "old@example.com")
    real = stripe.__call__

    def meanwhile(method, path, data=None, key=None):
        answer = real(method, path, data, key)
        if path == "checkout/sessions" and method == "POST":
            with db.transaction() as conn:  # another tab, while Stripe was answering
                conn.execute("UPDATE lists SET email = 'new@example.com', email_verified_at = NULL WHERE id = ?", (L,))
        return answer

    billing._stripe = meanwhile
    with pytest.raises(billing.EmailChanged):
        billing.checkout_url(L, "month", "https://sites.example", "old@example.com")
    assert stripe.sessions["cs_1"]["status"] == "expired"
    billing._stripe = stripe


def test_a_subscribed_account_is_not_disabled(stripe, L, run):
    _plan(L, "active", customer="cus_1")
    stripe.sub("cus_1", "active", created=1)
    with pytest.raises(SystemExit) as refused:
        run("disable", L)
    assert "settle it in Stripe" in str(refused.value) and _row(L)["disabled_at"] is None
    stripe.subs[0]["status"] = "canceled"
    assert run("disable", L)[0] == 0 and _row(L)["disabled_at"] is not None


def test_disable_closes_open_checkouts_and_refuses_open_invoices(stripe, L, run):
    _confirm(L)
    billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"])
    stripe.invoices.append({"id": "in_1", "customer": "cus_1", "status": "open"})
    with pytest.raises(SystemExit) as refused:
        run("disable", L)
    assert "an open invoice" in str(refused.value)
    assert stripe.sessions["cs_1"]["status"] == "expired"  # nothing payable left open
    stripe.invoices.clear()
    assert run("disable", L)[0] == 0


def test_a_reused_session_is_not_handed_out_after_the_email_changed(stripe, L):
    _confirm(L, "old@example.com")
    billing.checkout_url(L, "year", "https://sites.example", "old@example.com")
    real = stripe.__call__

    def meanwhile(method, path, data=None, key=None):
        answer = real(method, path, data, key)
        if path == "checkout/sessions" and method == "GET":
            with db.transaction() as conn:
                conn.execute("UPDATE lists SET email = 'new@example.com', email_verified_at = NULL WHERE id = ?", (L,))
        return answer

    billing._stripe = meanwhile
    with pytest.raises(billing.EmailChanged):
        billing.checkout_url(L, "year", "https://sites.example", "old@example.com")
    billing._stripe = stripe
    assert stripe.sessions["cs_1"]["status"] == "expired"


def test_a_checkout_in_flight_when_the_account_is_disabled_is_closed(stripe, L):
    _confirm(L)
    real = stripe.__call__

    def meanwhile(method, path, data=None, key=None):
        answer = real(method, path, data, key)
        if path == "checkout/sessions" and method == "POST":
            with db.transaction() as conn:  # admin disable, in its own process
                conn.execute("UPDATE lists SET disabled_at = '2026-10-14T00:00:00.000Z' WHERE id = ?", (L,))
        return answer

    billing._stripe = meanwhile
    with pytest.raises(billing.BillingError):
        billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"])
    billing._stripe = stripe
    assert stripe.sessions["cs_1"]["status"] == "expired"


def test_a_refused_disable_leaves_the_account_enabled(stripe, L, run):
    _plan(L, "active", customer="cus_1")
    stripe.sub("cus_1", "active", created=1)
    with pytest.raises(SystemExit):
        run("disable", L)
    assert _row(L)["disabled_at"] is None


def test_an_open_invoice_sends_checkout_to_manage_billing(stripe, new_list):
    made = new_list()
    c, L = made["client"], made["list_id"]
    _confirm(L)
    _plan(L, "canceled", customer="cus_1")
    stripe.sub("cus_1", "canceled", created=1)
    stripe.invoices.append({"id": "in_1", "customer": "cus_1", "status": "open"})
    res = c.post("/api/app/billing/checkout", json={"interval": "month"})
    assert res.status_code == 409 and "Manage billing" in res.json()["detail"]


def test_a_first_customer_made_while_the_account_is_marked_is_never_used(stripe, L):
    _confirm(L)
    real = stripe.__call__

    def meanwhile(method, path, data=None, key=None):
        answer = real(method, path, data, key)
        if path == "customers" and method == "POST":  # admin marks the account meanwhile
            with db.transaction() as conn:
                conn.execute("UPDATE lists SET disabled_at = '2026-10-14T00:00:00.000Z' WHERE id = ?", (L,))
        return answer

    billing._stripe = meanwhile
    with pytest.raises(billing.BillingError):
        billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"])
    billing._stripe = stripe
    assert stripe.posts("checkout/sessions") == [] and _row(L)["stripe_customer"] == ""


def test_a_session_whose_account_was_deleted_meanwhile_is_closed(stripe, L):
    _confirm(L)
    real = stripe.__call__

    def meanwhile(method, path, data=None, key=None):
        answer = real(method, path, data, key)
        if path == "checkout/sessions" and method == "POST":
            from scripts.admin import _LIST_TABLES

            with db.transaction() as conn:  # admin delete, in its own process
                for table in _LIST_TABLES:
                    conn.execute(f"DELETE FROM {table} WHERE list_id = ?", (L,))
                conn.execute("DELETE FROM lists WHERE id = ?", (L,))
        return answer

    billing._stripe = meanwhile
    with pytest.raises(billing.BillingError):
        billing.checkout_url(L, "year", "https://sites.example", _row(L)["email"])
    billing._stripe = stripe
    assert stripe.sessions["cs_1"]["status"] == "expired"


def test_a_stripe_failure_during_disable_leaves_the_account_enabled(stripe, L, run, monkeypatch):
    _plan(L, "active", customer="cus_1")

    def down(*a, **k):
        raise billing.BillingError("Stripe answered 503")

    monkeypatch.setattr(billing, "_stripe", down)
    with pytest.raises(SystemExit) as refused:
        run("disable", L)
    assert "could not be checked" in str(refused.value) and _row(L)["disabled_at"] is None


def test_a_refused_delete_leaves_the_account_enabled(stripe, L, run):
    _plan(L, "canceled", customer="cus_1")
    with pytest.raises(SystemExit):
        run("delete", L, f"--yes-delete-list-{L}", "--no-snapshot")
    assert _row(L)["disabled_at"] is None


def test_a_failed_snapshot_leaves_the_account_as_it_was(stripe, L, run, monkeypatch):
    from backend import backup

    monkeypatch.setattr(backup, "snapshot", lambda: None)
    with pytest.raises(SystemExit) as refused:
        run("delete", L, f"--yes-delete-list-{L}")
    assert "Could not snapshot" in str(refused.value) and _row(L)["disabled_at"] is None


def test_help_tells_a_confirmed_free_account_that_pro_raises_its_caps(stripe, client, L):
    from backend import lists

    _confirm(L)
    link = f"/link/{lists.get_list(L)['agent_token']}?cmd=HELP"
    assert "Pro raises them" in client.get(link).text
    _plan(L, "active", customer="cus_1")
    assert "final caps" in client.get(link).text


def test_a_subscribed_account_cannot_clear_its_email(stripe, new_list):
    made = new_list()
    c, L = made["client"], made["list_id"]
    _confirm(L)
    _plan(L, "active", customer="cus_1")
    res = c.put("/api/app/email", json={"email": ""})
    assert res.status_code == 409 and "change it to another address" in res.json()["detail"]
    assert _row(L)["email"] == "pat@example.com"
    assert c.put("/api/app/email", json={"email": "new@example.com"}).status_code == 200  # a change is fine
    # Any Stripe customer, even one with no subscription yet (an open checkout, say).
    _plan(L, "", customer="cus_1")
    assert c.put("/api/app/email", json={"email": ""}).status_code == 409


def test_no_checkout_when_stripe_will_not_take_the_new_email(stripe, L):
    _confirm(L, "old@example.com")
    _plan(L, "canceled", customer="cus_1")
    stripe.sub("cus_1", "canceled", created=1)
    _confirm(L, "new@example.com")
    real = stripe.__call__

    def refuse(method, path, data=None, key=None):
        if path == "customers/cus_1" and method == "POST":
            raise billing.BillingError("Stripe answered 500")
        return real(method, path, data, key)

    billing._stripe = refuse
    with pytest.raises(billing.BillingError):
        billing.checkout_url(L, "month", "https://sites.example", "new@example.com")
    billing._stripe = stripe
    assert stripe.posts("checkout/sessions") == []


def test_unconfirmed_subscription_keeps_small_site_and_storage_limits(L):
    _plan(L, "active")
    row = _row(L)
    assert row["email_verified_at"] is None
    plan = plans.of(row)
    assert plan == "pro"
    assert common.site_bytes_for(False, True, plan) == 25_000_000
    assert common.storage_quota_for(False, True, plan) == 25_000_000


def test_unconfirmed_grant_keeps_small_site_and_storage_limits(L):
    _comp(L, "max")
    row = _row(L)
    assert row["email_verified_at"] is None
    plan = plans.of(row)
    assert plan == "max"
    assert common.site_bytes_for(False, True, plan) == 25_000_000
    assert common.storage_quota_for(False, True, plan) == 25_000_000
