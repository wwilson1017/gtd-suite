"""The free suite (plans/settings.free_max, the default): a confirmed hosted account is on
Max, an unconfirmed one keeps the trial caps, a self-host is unchanged, nothing is sold,
and SIGNUP_CLOSED stops new accounts on the hosted service only."""

import re
from urllib.parse import urlsplit

import pytest

from backend import boards, common, db, lists, notes, recordings, service, settings
from backend.plans import admin as plan_admin, extension, plans
from backend.tests.conftest import confirm_list
from backend.tests.test_pages import FRONTEND_INDEX, built as built


@pytest.fixture()
def free(todo_db, monkeypatch):
    monkeypatch.delenv("FREE_MAX")  # the conftest turns the level limits on; this is the default


def _plan(list_id):
    return plans.of(lists.get_list(list_id))


def test_a_confirmed_hosted_account_is_on_max_and_an_unconfirmed_one_on_none(free, L):
    assert _plan(L) is None
    confirm_list(L)
    assert _plan(L) == "max"


def test_every_apps_cap_check_reads_max_for_a_confirmed_account(free, L, monkeypatch):
    confirm_list(L)
    seen = []
    for name in ("caps_for", "board_caps_for", "note_cap_for", "recording_cap_for"):
        real = getattr(common, name)
        monkeypatch.setattr(common, name, lambda *a, real=real: seen.append(a[-1]) or real(*a))
    with db.transaction() as conn:
        service._check_cap(conn, L, "todos")
        boards._check_cap(conn, L, "boards")
        notes._check_cap(conn, L)
        recordings._check_cap(conn, L)
    assert seen == ["max"] * 4


def test_confirmed_gets_max_caps_and_short_names_and_unconfirmed_keeps_the_trial(free, new_list):
    made = new_list()
    c = made["client"]
    session = c.get("/api/app/session").json()
    assert (session["caps"]["todos"], session["caps"]["brains"]) == (common.ANON_CAPS[0], 1)
    assert session["plan"]["free"] is True and session["plan"]["tier"] is None
    refused = c.post("/api/app/sites/links", json={"url": "https://example.com", "short_name": "early"})
    assert refused.status_code == 400 and "confirmed email" in refused.json()["detail"]
    assert "limits" not in refused.json()["detail"]  # it names the email, not a level

    confirm_list(made["list_id"])
    session = c.get("/api/app/session").json()
    assert session["plan"]["tier"] == "max" and session["caps"]["brains_label"] == "Unlimited"
    assert session["caps"]["todos"] == 20_000
    sites_caps = c.get("/api/app/sites").json()["caps"]
    assert (sites_caps["pages"], sites_caps["short_names"]) == (10_000, 100)
    made_link = c.post("/api/app/sites/links", json={"url": "https://example.com", "short_name": "freebie"})
    assert made_link.status_code == 200, made_link.text


def test_the_operators_stats_count_free_max_and_not_when_switched_off(free, L, monkeypatch):
    confirm_list(L)
    conn = db.get_db()
    assert plan_admin.stats(conn)["max_now"] == 1
    monkeypatch.setenv("FREE_MAX", "false")
    assert plan_admin.stats(conn)["max_now"] == 0


def test_self_host_is_unchanged(free, L, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    confirm_list(L)
    assert _plan(L) is None
    assert common.caps_for(True, settings.open_signup(), _plan(L)) == common.SELF_HOST_CAPS


def test_switched_off_the_old_plan_logic_returns(todo_db, L):
    confirm_list(L)  # FREE_MAX=false (conftest)
    assert _plan(L) is None
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET pro_comp_until = '9999-12-31T00:00:00.000Z' WHERE id = ?", (L,))
    assert _plan(L) == "pro"


def test_nothing_extra_without_the_extension(client):
    # The tests with the extension installed live with it; the route tables prove no extra route.
    assert not extension.offers() and extension.cap_note(True) == "" and extension.guide_lines() == []
    config = client.get("/api/config").json()
    assert config["offers"] is False and config["free"] is False


def test_the_policy_pages_read_free(free, client, built):
    (built / "policy").mkdir()
    for name in ("terms.html", "privacy.html", "security.html", "support.html"):
        (built / "policy" / name).write_text((FRONTEND_INDEX.parent / "public" / "policy" / name).read_text())
    assert "the apps are free" in client.get("/terms.html").text
    for name in ("terms.html", "privacy.html", "security.html", "support.html"):
        text = client.get(f"/{name}").text
        # No sales wording: the words a page that sold something would need.
        assert re.findall(r"(?i)\bpro\b|stripe|refund|subscri|\$5\b|<!--", text) == [], name


# ── SIGNUP_CLOSED ─────────────────────────────────────────────────────────────


def test_signup_closed_refuses_every_new_account_and_keeps_existing_ones(client, create, new_list, monkeypatch):
    made = new_list()
    monkeypatch.setenv("SIGNUP_CLOSED", "true")
    assert client.get("/api/config").json()["signup_closed"] is True
    for body in (None, {"tz": "UTC"}, {"tz": "UTC", "connect": "ABCD-EFGH"}):
        refused = create(json=body) if body else create()
        assert refused.status_code == 403 and "Sign-up is closed" in refused.json()["detail"]
        assert refused.headers["cache-control"] == "no-store"
    assert made["client"].get("/api/app/session").status_code == 200
    assert made["client"].post("/api/app/todos", json={"title": "still here"}).status_code == 200
    assert client.get(urlsplit(made["agent_url"]).path, params={"cmd": "LIST"}).status_code == 200
    monkeypatch.setenv("SIGNUP_CLOSED", "false")
    assert create().status_code == 200


def test_signup_closed_keeps_sign_in(client, mail, create, monkeypatch):
    monkeypatch.setenv("SIGNUP_CLOSED", "true")
    assert client.post("/api/signin", json={"email": "me@example.com"}).status_code == 200


def test_signup_closed_never_touches_a_self_host_claim(create, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    monkeypatch.setenv("SIGNUP_CLOSED", "true")
    assert not settings.signup_closed()
    assert create().status_code == 200
