"""Plan cases moved from test_site_views.py."""

import datetime
from backend import common, db, sites
from backend.tests.conftest import confirm_list as confirm_list
from backend.tests.test_sites import (
    ON_SITES as ON_SITES,
    acct as acct,
    page as page,
    path_of as path_of,
    served as served,
)
from backend.tests.test_site_views import fresh_counter as fresh_counter


def _pro(list_id):
    until = common.to_iso(common.utcnow() + datetime.timedelta(days=30))
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET plan_status = 'active', plan_until = ? WHERE id = ?", (until, list_id))


def test_views_are_left_out_for_a_free_account_and_shown_with_pro(acct, client):
    lid = acct["id"]
    made = page(lid)
    sites.count_view(made["id"])
    sites.flush_views()
    assert "views" not in made
    assert "views" not in sites.get_site(lid, made["id"])
    assert all("views" not in s for s in sites.list_sites(lid))
    _pro(lid)
    assert sites.get_site(lid, made["id"])["views"] == 1
    assert [s["views"] for s in sites.list_sites(lid)] == [1]
    assert sites.update(lid, made["id"], title="Renamed")["views"] == 1
