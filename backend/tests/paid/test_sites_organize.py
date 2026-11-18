"""Plan cases moved from test_sites_organize.py."""

import json
from backend.paid import plans
from backend import db, sites
from backend.tests.conftest import confirm_list as confirm_list
from backend.tests.test_admin import run as run
from backend.tests.test_sites import acct as acct, page as page, served as served


def test_comp_grants_pro_by_email_until_a_day_and_takes_it_back(acct, run, freeze):
    lid = acct["id"]
    confirm_list(lid, "pat@example.com")
    assert not plans.active(_row(lid))
    code, out = run("comp", "PAT@example.com")
    assert code == 0 and "for good" in out and plans.active(_row(lid))
    assert sites.caps(lid) == {
        "pages": 2500,
        "links": 2500,
        "page_bytes": 2_000_000,
        "site_bytes": 250_000_000,
        "storage": 10_000_000_000,
        "storage_used": 0,
        "files_per_site": 1000,
        "short_names": 10,
    }
    code, out = run("comp", lid, "--until", "2026-12-01")
    assert "until 2026-12-01" in out
    freeze("2026-11-30T23:00:00")
    assert plans.active(_row(lid))
    freeze("2026-12-01T00:00:01")
    assert not plans.active(_row(lid))
    assert run("comp", lid, "--off")[0] == 0 and _row(lid)["pro_comp_until"] is None
    log = [tuple(r) for r in db.get_db().execute("SELECT command, list_id FROM admin_log")]
    assert log == [("comp", lid), ("comp", lid), ("comp off", lid)]


def test_a_comped_account_shows_as_free_pro_and_is_counted(acct, run, new_list):
    made = new_list()
    run("comp", made["list_id"])
    plan = made["client"].get("/api/app/session").json()["plan"]
    assert plan["pro"] is True and plan["comp_until"].startswith("9999")
    stats = json.loads(run("stats", "--json")[1])
    assert stats["pro_now"] == 1 and stats["pro_comp"] == 1
    assert stats["plan_statuses"] == {}  # a grant is not a Stripe status


def test_the_source_of_pro_is_the_live_one(acct, run, freeze):
    lid = acct["id"]
    freeze("2026-10-17T12:00:00")
    run("comp", lid, "--until", "2026-11-01")
    assert plans.pro_source(_row(lid)) == "comp"
    with db.transaction() as conn:  # a stale paid status, long past its period
        conn.execute(
            "UPDATE lists SET plan_status = 'active', plan_until = '2026-09-01T00:00:00.000Z' WHERE id = ?", (lid,)
        )
    assert plans.pro_source(_row(lid)) == "comp"
    with db.transaction() as conn:  # a live subscription wins
        conn.execute("UPDATE lists SET plan_until = '2026-12-01T00:00:00.000Z' WHERE id = ?", (lid,))
    assert plans.pro_source(_row(lid)) == "stripe"
    freeze("2026-11-15T00:00:00")  # the grant has run out; paid still counts, not free
    stats = json.loads(run("stats", "--json")[1])
    assert stats["pro_now"] == 1 and stats["pro_comp"] == 0


# ── Operator grants ─────────────────────────────────────────────────────


def _row(list_id):
    return db.get_db().execute("SELECT * FROM lists WHERE id = ?", (list_id,)).fetchone()


def test_comp_needs_exactly_one_list(acct, run):
    from backend import lists

    other = lists.create_list("UTC")["list_id"]
    confirm_list(acct["id"], "same@example.com")
    confirm_list(other, "same@example.com")
    code, out = run("comp", "same@example.com")
    assert code == 1 and "give the list id" in out
    assert run("comp", "nobody@example.com")[0] == 1
