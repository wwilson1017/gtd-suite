"""Expiring first sites and short names on a raised level, including restore and daily races."""

from contextlib import contextmanager

import pytest

from datetime import timedelta

from backend import common, db, lists, sites
from backend.common import NotFoundError, ValidationError
from backend.tests.conftest import confirm_list
from backend.tests.test_files import store as store
from backend.tests.test_site_sync import manifest, publish


@pytest.fixture()
def account(L, monkeypatch):
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_SHORT_URL", "https://ss.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (L,))
    return L


@pytest.mark.parametrize("domain", ["", "content.example"])
def test_unconfirmed_page_expires_at_seven_days_on_every_surface(account, client, freeze, monkeypatch, domain):
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", domain)
    freeze("2026-11-15T12:00:00Z")
    page = sites.publish(account, "Hello")
    assert page["expires_at"] == "2026-11-22T12:00:00.000Z"
    old = f"https://ss.example/{page['code']}"
    assert client.get(page["address"]).status_code == 200
    freeze("2026-11-22T12:00:00Z")
    assert client.get(page["address"]).status_code == 404
    assert client.get(old).status_code == 404
    assert client.get(old + "/data").status_code == 404
    assert client.post(old + "/data", json={"x": 1}).status_code == 404
    confirm_list(account)
    assert sites.get_site(account, page["id"])["expires_at"] is None
    assert client.get(page["address"]).status_code == 200


def test_file_sync_gets_expiry_once_and_confirmation_clears_it(store, account, freeze):
    freeze("2026-11-15T12:00:00Z")
    page = publish(store, account)
    assert page["expires_at"] == "2026-11-22T12:00:00.000Z"
    freeze("2026-11-16T12:00:00Z")
    assert publish(store, account)["expires_at"] == page["expires_at"]
    with pytest.raises(ValidationError, match="holds 1 page"):
        sites.sync(account, manifest({"index.html": b"hi"}), client_ref="second")
    confirm_list(account)
    assert publish(store, account)["expires_at"] is None


def test_expired_site_deleted_whole_but_blobs_remain_for_gc(store, account, freeze):
    freeze("2026-11-15T12:00:00Z")
    # A grandfathered data site can still be unconfirmed.
    confirm_list(account)
    page = sites.publish(account, "Hello", data="shared")
    sites.add_record(page["id"], "owner", {"x": 1}, list_id=account)
    publish(store, account, site_id=page["id"])
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET email_verified_at = NULL WHERE id = ?", (account,))
        conn.execute("UPDATE sites SET expires_at = '2026-11-22T12:00:00.000Z' WHERE id = ?", (page["id"],))
    freeze("2026-12-22T12:00:00Z")
    assert sites.expire_sites() == 0  # more than 30 days, not the boundary
    freeze("2026-12-22T12:00:01Z")
    assert sites.expire_sites() == 1
    for table in ("sites", "site_files", "site_data", "site_data_fields"):
        assert db.get_db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert db.get_db().execute("SELECT COUNT(*) FROM site_blobs").fetchone()[0] == 1
    confirm_list(account)
    with pytest.raises(NotFoundError):
        sites.get_site(account, page["id"])


def test_confirmation_between_selection_and_deletion_keeps_site(account, freeze, monkeypatch):
    freeze("2026-11-15T12:00:00Z")
    page = sites.publish(account, "Keep me")
    freeze("2026-12-23T12:00:00Z")
    original = db.transaction
    entered = []

    @contextmanager
    def confirming_transaction(*args, **kwargs):
        if not entered:
            entered.append(True)
            with original() as conn:
                lists.set_email_in(conn, account, "keep@example.com")
                lists.verify_email_in(conn, account)
        with original(*args, **kwargs) as conn:
            yield conn

    monkeypatch.setattr(db, "transaction", confirming_transaction)
    assert sites.expire_sites() == 0
    assert entered and sites.get_site(account, page["id"])["expires_at"] is None


def test_self_host_and_existing_sites_get_no_expiry(account, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    pages = [sites.publish(account, "Existing") for _ in range(3)]
    assert all(page["expires_at"] is None for page in pages)
    monkeypatch.setenv("OPEN_SIGNUP", "true")
    db.init_db()  # migration is idempotent and does not backfill expiry
    assert all(sites.get_site(account, p["id"])["expires_at"] is None for p in pages)
    assert sites.publish(account, "Updated", site_id=pages[0]["id"])["expires_at"] is None
    with pytest.raises(ValidationError, match="holds 1 page"):
        sites.publish(account, "New")


def test_every_one_segment_route_is_a_reserved_short_name():
    import re

    from backend.main import app

    segments = {m.group(1) for r in app.routes if (m := re.match(r"^/([a-z0-9-]{4,30})(/|$)", getattr(r, "path", "")))}
    assert segments <= sites._RESERVED_SHORT


@pytest.mark.parametrize("days", [0, 31])
def test_self_host_short_link_works_without_a_plan(account, client, freeze, monkeypatch, days):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    freeze("2026-11-15T12:00:00Z")
    made = sites.shorten(account, "https://example.com/destination", short_name="local-link")
    assert common.short_name_cap_for(False) == 100
    sites.short_name_grace()
    assert db.get_db().execute("SELECT short_grace_until FROM sites WHERE id = ?", (made["id"],)).fetchone()[0] is None
    freeze(common.to_iso(common.utcnow() + timedelta(days=days)))
    sites.short_name_grace()
    assert sites.lookup_short("local-link") is not None
    response = client.get("https://ss.example/local-link", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/destination"
