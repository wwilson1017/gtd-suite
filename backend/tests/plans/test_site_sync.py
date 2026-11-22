"""Level cases moved from test_site_sync.py."""

import pytest
from backend import common, db, sites
from backend.tests.conftest import confirm_list as confirm_list, turn_on as turn_on
from backend.tests.test_files import store as store, item as item
from backend.tests.test_site_sync import account as account, client as client, publish as publish


@pytest.mark.parametrize(
    "verified,hosted,tier,site,pool",
    [
        (False, True, None, 25_000_000, 25_000_000),
        (True, True, None, 25_000_000, 500_000_000),
        (True, True, "pro", 250_000_000, 10_000_000_000),
        (True, True, "max", 1_000_000_000, 100_000_000_000),
        (False, False, None, 1_000_000_000, 100_000_000_000),
    ],
)
def test_limits(verified, hosted, tier, site, pool):
    assert common.site_bytes_for(verified, hosted, tier) == site
    assert common.storage_quota_for(verified, hosted, tier) == pool


def test_file_password_and_suspension_before_conditionals(store, account, client):
    page = publish(store, account)
    url = page["address"]
    etag = client.get(url).headers["etag"]
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET pro_comp_until = '2999-01-01T00:00:00.000Z' WHERE id = ?", (account,))
    sites.update(account, page["id"], password="secret")
    row = sites._row(db.get_db(), account, page["id"])
    cookie = sites.unlock_cookie(row)
    headers = {"if-none-match": etag, "Cookie": f"__Host-ss-pass={cookie}"}
    assert client.get(url, headers={"if-none-match": etag}).status_code == 403
    assert client.get(url, headers=headers).status_code == 304
    sites.update(account, page["id"], password="new-secret")
    assert client.get(url, headers=headers).status_code == 403
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET suspended_at = 'down' WHERE id = ?", (page["id"],))
    publish(store, account, site_id=page["id"])
    denied = client.get(url, headers=headers)
    assert denied.status_code == 404 and denied.headers["clear-site-data"] == '"cache", "storage"'
