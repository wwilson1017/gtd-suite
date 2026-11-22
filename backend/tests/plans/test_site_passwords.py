"""Simple Sites locked pages (a raised level): a page with a password answers its form (403, never
its content) until the visitor sends the password, which earns a 30-day pass for that
page only. Every try is charged before any hashing; a new password ends every pass."""

import datetime

import pytest

from backend import common, db, ratelimit, sites
from backend.common import ValidationError
from backend.tests.conftest import confirm_list
from backend.tests.test_sites import ON_SITES, acct, page, path_of, served  # noqa: F401 (fixtures)

SECRET_TEXT = "the private part"


def _raise(list_id, status="active"):
    until = common.to_iso(common.utcnow() + datetime.timedelta(days=30))
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET plan_status = ?, plan_until = ? WHERE id = ?", (status, until, list_id))


@pytest.fixture()
def locked(acct, client):
    """A raised account's locked page, and a way to open it."""
    confirm_list(acct["id"])  # Password passes outlive the unconfirmed site trial.
    _raise(acct["id"])
    made = page(acct["id"], f"# Plans\n\n{SECRET_TEXT}")
    sites.update(acct["id"], made["id"], password="open sesame")
    ratelimit.clear_all()
    return made


def _try(client, made, password):
    return client.post(f"{path_of(made)}/unlock", data={"password": password}, headers=ON_SITES, follow_redirects=False)


def _pass(res, made):
    return {"Cookie": f"sp_{made['code']}={res.cookies[f'sp_{made["code"]}']}", **ON_SITES}


def test_a_locked_page_shows_its_form_never_its_content(locked, client):
    res = client.get(path_of(locked), headers=ON_SITES)
    assert res.status_code == 403 and "This page is locked" in res.text
    assert SECRET_TEXT not in res.text and "www-authenticate" not in res.headers
    assert res.headers["cache-control"] == "no-store"
    assert "form-action 'self'" in res.headers["content-security-policy"]
    assert sites.flush_views() == 0  # the form is not a view


def test_the_right_password_earns_a_pass_for_this_page(locked, client):
    assert _try(client, locked, "nope").status_code == 403
    assert "Wrong password" in _try(client, locked, "nope").text
    res = _try(client, locked, "open sesame")
    assert res.status_code == 303 and res.headers["location"] == path_of(locked)
    cookie = res.headers["set-cookie"]
    assert f"Path={path_of(locked)}" in cookie and "HttpOnly" in cookie and "Secure" in cookie
    shown = client.get(path_of(locked), headers=_pass(res, locked))
    assert shown.status_code == 200 and SECRET_TEXT in shown.text
    assert shown.headers["content-security-policy"] == sites.SANDBOX  # still sandboxed


def test_passes_expire_cannot_be_forged_and_end_with_a_new_password(locked, client, freeze):
    res = _try(client, locked, "open sesame")
    good = _pass(res, locked)
    forged = {**ON_SITES, "Cookie": f"sp_{locked['code']}=9999999999.{'0' * 64}"}
    assert client.get(path_of(locked), headers=forged).status_code == 403
    sites.update(_owner(locked), locked["id"], password="a new one")
    assert client.get(path_of(locked), headers=good).status_code == 403
    res = _try(client, locked, "a new one")
    later = _pass(res, locked)
    freeze((common.utcnow() + datetime.timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%S"))
    assert client.get(path_of(locked), headers=later).status_code == 403


def _owner(made):
    return db.get_db().execute("SELECT list_id FROM sites WHERE id = ?", (made["id"],)).fetchone()[0]


def test_tries_are_charged_before_any_hashing(locked, client, monkeypatch):
    hashed = []
    real = sites._pbkdf2
    monkeypatch.setattr(sites, "_pbkdf2", lambda *a: hashed.append(1) or real(*a))
    for _ in range(20):
        assert _try(client, locked, "nope").status_code == 403
    assert _try(client, locked, "open sesame").status_code == 429  # even the right one, now
    assert len(hashed) == 20


def test_a_burst_beyond_the_hashing_slots_is_told_to_wait(locked, client, monkeypatch):
    monkeypatch.setattr(sites, "_hashing", __import__("threading").BoundedSemaphore(1))
    sites._hashing.acquire()
    try:
        res = _try(client, locked, "open sesame")
        assert res.status_code == 429 and res.headers["retry-after"] == "5"
    finally:
        sites._hashing.release()


def test_locking_needs_a_raised_level_unlocking_always_and_pages_only(acct, client):
    lid = acct["id"]
    made = page(lid, f"# Plans\n\n{SECRET_TEXT}")
    with pytest.raises(ValidationError, match="not part of this account.s limits"):
        sites.update(lid, made["id"], password="open sesame")
    _raise(lid)
    sites.update(lid, made["id"], password="open sesame")  # a public page, locked now
    assert client.get(path_of(made), headers=ON_SITES).status_code == 403
    _raise(lid, "canceled")  # the level lapses: the lock stays, and can still be taken off
    assert client.get(path_of(made), headers=ON_SITES).status_code == 403
    sites.update(lid, made["id"], password="")
    assert client.get(path_of(made), headers=ON_SITES).status_code == 200
    _raise(lid)
    with pytest.raises(ValidationError, match="4 to 200"):
        sites.update(lid, made["id"], password="abc")


def test_a_short_link_cannot_be_locked(acct):
    from backend.tests.conftest import confirm_list

    confirm_list(acct["id"])
    _raise(acct["id"])
    link = sites.shorten(acct["id"], "https://example.com/x")
    with pytest.raises(ValidationError, match="Only a page"):
        sites.update(acct["id"], link["id"], password="open sesame")


def test_a_self_hosted_server_locks_without_a_level(acct, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    made = page(acct["id"])
    assert sites.update(acct["id"], made["id"], password="open sesame")["locked"] is True


def test_the_hash_reaches_no_answer(locked, acct, client):
    lid = acct["id"]
    for answer in (
        sites.get_site(lid, locked["id"]),
        *sites.list_sites(lid),
        sites.update(lid, locked["id"], title="Still locked"),
    ):
        assert answer["locked"] is True and "password_hash" not in answer
        assert "pbkdf2" not in str(answer)


def test_unlock_answers_only_on_the_sites_host_for_a_locked_page(locked, acct, client):
    assert client.post(f"{path_of(locked)}/unlock", data={"password": "x"}).status_code == 404
    public = page(acct["id"])
    assert _try(client, public, "x").status_code == 404


def test_the_longest_password_fits_through_the_form(acct, client):
    _raise(acct["id"])
    made = page(acct["id"], f"# Plans\n\n{SECRET_TEXT}")
    longest = "\U0001f511" * sites.PASSWORD_LIMITS[1]  # 200 four-byte characters
    sites.update(acct["id"], made["id"], password=longest)
    ratelimit.clear_all()
    res = _try(client, made, longest)
    assert res.status_code == 303


def test_cross_site_posts_are_refused_before_they_spend_any_tries(locked, client):
    hostile = {**ON_SITES, "Sec-Fetch-Site": "cross-site"}
    for _ in range(25):
        res = client.post(f"{path_of(locked)}/unlock", data={"password": "x"}, headers=hostile)
        assert res.status_code == 403
    assert _try(client, locked, "open sesame").status_code == 303  # the visitor's tries are intact


def test_the_form_sets_no_length_the_server_does_not(locked, client):
    assert "maxlength" not in client.get(path_of(locked), headers=ON_SITES).text


def test_a_huge_forged_expiry_shows_the_form_not_an_error(locked, client):
    forged = {**ON_SITES, "Cookie": f"sp_{locked['code']}={'9' * 5000}.{'0' * 64}"}
    assert client.get(path_of(locked), headers=forged).status_code == 403
    # A digit Python's isdigit() accepts but int() refuses (superscript two).
    row = sites.lookup(path_of(locked).lstrip("/"))
    assert sites.unlocked(row, "\u00b2." + "0" * 64) is False
    assert sites.unlocked(row, "9999999999.\u00b2") is False  # a non-ASCII MAC


def test_no_hashing_for_a_lock_that_would_be_refused(acct, monkeypatch):
    hashed = []
    real = sites._pbkdf2
    monkeypatch.setattr(sites, "_pbkdf2", lambda *a: hashed.append(1) or real(*a))
    made = page(acct["id"])
    with pytest.raises(ValidationError, match="not part of this account.s limits"):  # free
        sites.update(acct["id"], made["id"], password="open sesame")
    with pytest.raises(sites.NotFoundError):
        sites.update(acct["id"], 99999, password="open sesame")
    assert hashed == []


def test_an_unpaired_surrogate_is_refused_not_a_crash(acct):
    _raise(acct["id"])
    made = page(acct["id"])
    with pytest.raises(ValidationError):
        sites.update(acct["id"], made["id"], password="\ud800abcd")


def test_a_password_with_a_line_break_is_refused(acct):
    _raise(acct["id"])
    made = page(acct["id"])
    for bad in ("ab\ncd", "ab\rcd"):
        with pytest.raises(ValidationError, match="line break"):
            sites.update(acct["id"], made["id"], password=bad)
