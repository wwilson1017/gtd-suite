"""Plans derived from the stored plan columns (plans.py): a subscription's last synced
status within its period and grace, the operator's grants, and the caps they set."""

import datetime

import pytest

from backend.plans import plans
from backend import boards, common, db, notes, recordings, service, sites
from backend.common import ValidationError


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


def test_no_upsell_where_pro_is_not_on_sale(L):
    _confirm(L)
    for i in range(common.SITE_VERIFIED_CAPS[0]):
        sites.publish(L, f"# Page {i}")
    with pytest.raises(ValidationError) as refused:
        sites.publish(L, "# One more")
    assert "Pro" not in str(refused.value)


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
