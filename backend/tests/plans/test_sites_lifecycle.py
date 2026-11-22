"""Plan cases moved from test_sites_lifecycle.py."""

from datetime import timedelta
import pytest
from backend import backup, common, db, lists, sites
from backend.common import ValidationError
from backend.tests.conftest import confirm_list as confirm_list
from backend.tests.test_files import store as store
from backend.tests.test_site_sync import manifest as manifest, publish as publish
from scripts import restore_list
from backend.tests.test_sites_lifecycle import account as account


def grant(lid, plan="pro"):
    confirm_list(lid)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '2099-01-01T00:00:00.000Z', comp_plan = ? WHERE id = ?", (plan, lid)
        )


def lapse(lid):
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET pro_comp_until = NULL WHERE id = ?", (lid,))


@pytest.mark.parametrize(
    "name",
    [
        "abc",
        "a" * 31,
        "UPPER",
        "a_b_c",
        "abcdefghij",
        "x-abcdefghij",
        "app",
        "api",
        "link",
        "mcp",
        "connect",
        "signin",
        "admin",
        "token",
        "register",
        "abuse",
        "support",
        "todo",
        "sites",
        "projects",
        "notes",
        "brain",
        "commonbrain",
        "simple-sites",
    ],
)
def test_short_name_policy(account, name):
    grant(account)
    with pytest.raises(ValidationError, match="short_name"):
        sites.shorten(account, "https://example.com", short_name=name)


@pytest.mark.parametrize("tier, cap", [("pro", 10), ("max", 100)])
def test_short_name_caps_and_uniqueness(account, tier, cap):
    confirm_list(account)
    with pytest.raises(ValidationError, match="Pro or Max"):
        sites.shorten(account, "https://example.com", short_name="hello")
    grant(account, tier)
    for n in range(cap):
        link = sites.shorten(account, "https://example.com", short_name=f"hello-{n}")
        assert link["short_name"] == f"hello-{n}"
        assert link["address"] == f"https://ss.example/hello-{n}"
    assert sites.caps(account)["short_names"] == cap
    with pytest.raises(ValidationError, match=f"{cap} short names"):
        sites.shorten(account, "https://example.com", short_name="one-more")
    other = lists.create_list()["list_id"]
    grant(other)
    with pytest.raises(ValidationError, match="already taken"):
        sites.shorten(other, "https://example.com", short_name="hello-0")


def test_short_resolver_grace_renewal_and_freeing(account, client, freeze):
    freeze("2026-11-15T12:00:00Z")
    grant(account)
    link = sites.shorten(account, "https://example.com/destination", short_name="vancouver")
    for host in ("ss.example", "sites.example"):
        response = client.get(f"https://{host}/vancouver", follow_redirects=False)
        assert response.status_code == 302 and response.headers["location"] == link["target"]
        assert response.headers["cache-control"] == "no-store" and "set-cookie" not in response.headers
    assert client.post("https://ss.example/vancouver").status_code == 404
    assert (
        client.get("https://ss.example/missing", follow_redirects=False).headers["location"]
        == "https://sites.example/missing"
    )
    lapse(account)
    assert sites.lookup_short("vancouver") is not None  # not stamped yet: still resolves
    sites.short_name_grace()
    grace = common.to_iso(common.utcnow() + timedelta(days=30))
    assert sites.get_site(account, link["id"])["short_grace_until"] == grace
    freeze("2026-12-14T12:00:00Z")
    sites.short_name_grace()
    assert sites.lookup_short("vancouver") is not None
    assert sites.get_site(account, link["id"])["short_grace_until"] == grace
    grant(account)
    sites.short_name_grace()
    assert sites.get_site(account, link["id"])["short_grace_until"] is None
    lapse(account)
    sites.short_name_grace()
    freeze("2027-01-13T12:00:00Z")
    assert sites.lookup_short("vancouver") is None
    sites.short_name_grace()
    assert sites.get_site(account, link["id"])["short_name"] is None
    grant(account)
    assert sites.shorten(account, "https://elsewhere.example", short_name="vancouver")["short_name"] == "vancouver"


@pytest.mark.parametrize(
    "field, value", [("status", "unpublished"), ("suspended_at", "2026-01-01"), ("expires_at", "2000-01-01")]
)
def test_short_resolver_obeys_servable(account, field, value):
    grant(account)
    link = sites.shorten(account, "https://example.com", short_name="hello")
    with db.transaction() as conn:
        conn.execute(f"UPDATE sites SET {field} = ? WHERE id = ?", (value, link["id"]))
    assert sites.lookup_short("hello") is None


def test_short_resolver_disabled_account(account):
    grant(account)
    sites.shorten(account, "https://example.com", short_name="hello")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), account))
    assert sites.lookup_short("hello") is None


def test_restore_keeps_live_names_and_grace_and_never_reclaims_snapshot_names(account, capsys):
    grant(account)
    kept = sites.shorten(account, "https://example.com", short_name="kept-name")
    gone = sites.shorten(account, "https://example.com", short_name="gone-name")
    snap = backup.snapshot()
    assert snap is not None
    with db.transaction() as conn:
        conn.execute(
            "UPDATE sites SET short_name = 'live-name', short_grace_until = '2090-01-01' WHERE id = ?", (kept["id"],)
        )
    sites.delete_site(account, gone["id"])
    other = lists.create_list()["list_id"]
    grant(other)
    sites.shorten(other, "https://other.example", short_name="gone-name")
    restore_list.restore(snap, account, db.db_path())
    current = sites.get_site(account, kept["id"])
    assert current["short_name"] == "live-name" and current["short_grace_until"] == "2090-01-01"
    assert sites.get_site(account, gone["id"])["short_name"] is None
    assert sites.lookup_short("gone-name")["list_id"] == other
    assert "has no short name" in capsys.readouterr().out


def test_paid_account_with_unconfirmed_new_email_keeps_caps_and_no_expiry(account):
    grant(account)
    with db.transaction() as conn:  # changed its address: unconfirmed again, still paying
        conn.execute("UPDATE lists SET email_verified_at = NULL WHERE id = ?", (account,))
    pages = [sites.publish(account, "Paid") for _ in range(2)]
    assert all(page["expires_at"] is None for page in pages)
