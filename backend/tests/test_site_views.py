"""Simple Sites view counts (sites.count_view / flush_views): every open of a page and
follow of a short link is counted in memory and written once a minute; the counts are
shown to entitled accounts (and self-hosted servers) and left out of every answer otherwise."""

import contextlib

import pytest

from backend import db, sites
from backend.tests.conftest import confirm_list
from backend.tests.test_sites import ON_SITES, acct, page, path_of, served  # noqa: F401 (fixtures)


@pytest.fixture(autouse=True)
def fresh_counter():
    sites._views.clear()
    yield
    sites._views.clear()


def _views(site_id):
    return db.get_db().execute("SELECT views FROM sites WHERE id = ?", (site_id,)).fetchone()[0]


def test_opens_and_follows_are_counted_but_not_heads_or_misses(acct, client):
    confirm_list(acct["id"])  # short links need a confirmed email
    shown = page(acct["id"])
    link = sites.shorten(acct["id"], "https://example.com/somewhere")
    assert client.get(path_of(shown), headers=ON_SITES).status_code == 200
    assert client.get(path_of(shown), headers=ON_SITES).status_code == 200
    assert client.get(path_of(link), headers=ON_SITES, follow_redirects=False).status_code == 302
    assert client.head(path_of(shown), headers=ON_SITES).status_code == 200
    assert client.get("/AAAAAAAAAA", headers=ON_SITES).status_code == 404
    assert sites.flush_views() == 3
    assert (_views(shown["id"]), _views(link["id"])) == (2, 1)
    assert sites.flush_views() == 0  # nothing new


def test_a_failed_write_keeps_its_counts_for_the_next_minute(acct, monkeypatch):
    shown = page(acct["id"])
    sites.count_view(shown["id"])
    real = db.transaction

    @contextlib.contextmanager
    def broken():
        raise RuntimeError("disk full")
        yield  # pragma: no cover

    monkeypatch.setattr(db, "transaction", broken)
    with pytest.raises(RuntimeError):
        sites.flush_views()
    monkeypatch.setattr(db, "transaction", real)
    assert sites.flush_views() == 1 and _views(shown["id"]) == 1


def test_views_counted_during_a_write_are_not_lost(acct, monkeypatch):
    shown = page(acct["id"])
    sites.count_view(shown["id"])
    real = db.transaction

    @contextlib.contextmanager
    def busy():
        sites.count_view(shown["id"])  # a visitor opens the page mid-write
        with real() as conn:
            yield conn

    monkeypatch.setattr(db, "transaction", busy)
    sites.flush_views()
    monkeypatch.setattr(db, "transaction", real)
    assert _views(shown["id"]) == 1 and sites.flush_views() == 1 and _views(shown["id"]) == 2


def test_a_self_hosted_server_shows_views_without_pro(acct, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    made = page(acct["id"])
    assert made["views"] == 0
