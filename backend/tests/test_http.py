"""HTTP contract: the real app, a real SQLite file, real requests."""

import pytest
from fastapi.testclient import TestClient

from backend import common, db, lists, ratelimit, router, service, sessions, signin


# ── Route table ───────────────────────────────────────────────────────────────


def _routes(app):
    return {(method.upper(), path) for path, ops in app.openapi()["paths"].items() for method in ops}


def test_there_are_no_delete_routes_but_simple_sites_one(client, new_list):
    # The person deletes a page or link, or clears a page's records, in the browser
    # ; nothing else.
    assert sorted(r for r in _routes(client.app) if r[0] == "DELETE") == [
        ("DELETE", "/api/app/sites/{site_id}"),
        ("DELETE", "/api/app/sites/{site_id}/data"),
    ]
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(f"{api}/todos", json={"title": "x"}).json()
    assert c.delete(f"{api}/todos/{todo['id']}").status_code == 405
    assert c.get(f"{api}/todos/{todo['id']}").status_code == 200


# ── Creating a list ───────────────────────────────────────────────────────────


def _set_cookie(res) -> tuple[str, set[str]]:
    """The Set-Cookie header: ``name=value``, and its attributes lowercased."""
    pair, *attrs = res.headers["set-cookie"].split(";")
    return pair.strip(), {a.strip().lower() for a in attrs}


def test_create_signs_this_browser_in_and_returns_the_agent_link(client):
    res = client.post("/api/lists", json={"tz": "Europe/Paris"})
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    body = res.json()
    assert set(body) == {"agent_token", "agent_url", "tz", "name"}
    assert body["agent_url"] == f"http://testserver/link/{body['agent_token']}"
    assert body["tz"] == "Europe/Paris"
    # The session is in the cookie only, and stored only as a hash.
    pair, attrs = _set_cookie(res)
    name, token = pair.split("=", 1)
    assert name == sessions.COOKIE and token not in res.text
    assert attrs == {"httponly", "max-age=31536000", "path=/", "samesite=lax"}
    stored = db.get_db().execute("SELECT token_hash FROM sessions").fetchall()
    assert [r[0] for r in stored] == [lists.hash_token(token)]
    # This browser is now in the list.
    list_id = client.get("/api/app/session").json()["list_id"]
    assert client.get("/api/app/filters", headers={"X-List": str(list_id)}).json()["tz"] == "Europe/Paris"


def test_the_cookie_is_secure_only_when_the_configured_address_is_https(create, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todogtd.com")
    assert "secure" in _set_cookie(create())[1]
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")
    assert "secure" not in _set_cookie(create())[1]


def test_ordinary_responses_never_set_or_clear_the_cookie(client, new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    responses = [
        c.get(f"{api}/session"),
        c.get(f"{api}/todos"),
        c.post(f"{api}/todos", json={"title": "x"}),
        c.get(f"{api}/todos", headers={"X-List": "0"}),
        c.post(f"{api}/signout"),
        c.get(f"{api}/todos"),
        c.post(f"{api}/signout-all"),
        client.get("/api/config"),
    ]
    assert [r.status_code for r in responses] == [200, 200, 200, 409, 200, 401, 401, 200]
    assert not [r.url for r in responses if "set-cookie" in r.headers]
    assert c.cookies[sessions.COOKIE] == made["session"]


def test_signing_out_everywhere_leaves_the_cookie_in_place(new_list):
    made = new_list()
    c = made["client"]
    res = c.post("/api/app/signout-all")  # signed in, so this one really runs
    assert res.status_code == 200 and "set-cookie" not in res.headers
    assert c.cookies[sessions.COOKIE] == made["session"]
    assert c.get("/api/app/todos").status_code == 401  # the row is gone; the cookie is stale


def test_creating_while_signed_in_is_409(new_list):
    made = new_list()
    c = made["client"]
    res = c.post("/api/lists")
    assert res.status_code == 409 and "already signed in" in res.json()["detail"]
    assert "set-cookie" not in res.headers and res.headers["cache-control"] == "no-store"
    assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
    # Signed out, the same browser may make another.
    c.post("/api/app/signout")
    assert c.post("/api/lists").status_code == 200


def test_create_list_without_a_body_or_with_a_bad_zone_falls_back_to_utc(create):
    assert create().json()["tz"] == "UTC"
    assert create(json={}).json()["tz"] == "UTC"
    assert create(json={"tz": "Mars/Olympus"}).json()["tz"] == "UTC"


def test_public_base_url_overrides_the_request_host(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todogtd.com/")
    body = client.post("/api/lists").json()
    assert body["agent_url"] == f"https://todogtd.com/link/{body['agent_token']}"


def test_create_list_is_rate_limited_per_ip(create):
    codes = [create().status_code for _ in range(11)]
    assert codes == [200] * 10 + [429]


def test_rate_limit_window_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    limiter = ratelimit.IPRateLimiter(window=60, max_hits=2)
    assert [limiter.allow("ip") for _ in range(3)] == [True, True, False]
    now[0] += 60
    assert limiter.allow("ip")


# ── Sessions: /api/app is the one place that answers 401 ──────────────────────

APP_ROUTES = [
    ("GET", "todos"),
    ("GET", "today"),
    ("GET", "filters"),
    ("GET", "projects"),
    ("GET", "areas"),
    ("GET", "todos/1"),
    ("GET", "capture-link"),
    ("POST", "capture-link/rotate"),
    ("GET", "agent-link"),
    ("POST", "agent-link/rotate"),
    ("GET", "name"),
    ("PUT", "tz"),
    ("GET", "session"),
    ("PUT", "email"),
    ("POST", "signin-link"),
    ("POST", "signout"),
    ("POST", "signout-all"),
    ("POST", "restore"),
    ("POST", "billing/checkout"),
    ("POST", "billing/manage"),
    ("POST", "billing/sync"),
]


@pytest.mark.parametrize("method,path", APP_ROUTES)
def test_no_session_is_401_without_www_authenticate_and_the_cookie_is_left_alone(client, method, path):
    for cookie in ({}, {"Cookie": f"{sessions.COOKIE}=not-a-real-token"}):
        res = client.request(
            method, f"/api/app/{path}", headers={"X-List": "1", **cookie}, json=None if method == "GET" else {}
        )
        assert res.status_code == 401
        assert "www-authenticate" not in res.headers and "set-cookie" not in res.headers
        assert res.headers["cache-control"] == "no-store"


def test_no_session_is_401_before_the_body_is_validated(client):
    assert client.post("/api/app/todos", json={"nope": 1}).status_code == 401
    assert client.put("/api/app/email", json={"email": 5}).status_code == 401


def _as(cookie: str, list_id: int) -> dict:
    return {"Cookie": f"{sessions.COOKIE}={cookie}", "X-List": str(list_id)}


def test_agent_capture_and_hashed_tokens_are_not_session_cookies(client, new_list):
    made = new_list()
    for other in (made["agent_token"], made["capture_token"], lists.hash_token(made["session"])):
        for method, path, body in (
            ("GET", "todos", None),
            ("GET", "filters", None),
            ("GET", "capture-link", None),
            ("GET", "agent-link", None),
            ("POST", "agent-link/rotate", None),
            ("POST", "capture-link/rotate", None),
            ("PUT", "email", {"email": "x@example.com"}),
            ("PUT", "tz", {"tz": "Asia/Tokyo"}),
            ("POST", "signin-link", None),
            ("POST", "signout-all", None),
        ):
            res = client.request(method, f"/api/app/{path}", headers=_as(other, made["list_id"]), json=body)
            assert res.status_code == 401, (other, path)
    # Nothing changed.
    c = made["client"]
    assert c.get("/api/app/agent-link").json()["token"] == made["agent_token"]
    assert c.get("/api/app/capture-link").json()["token"] == made["capture_token"]
    assert c.get("/api/app/filters").json()["tz"] == "America/Chicago"
    assert lists.get_list(made["list_id"])["email"] is None


def test_session_and_agent_tokens_are_rejected_on_the_capture_surface(client, new_list):
    made = new_list()
    for other in (made["session"], made["agent_token"]):
        assert client.post(f"/api/c/{other}", json={"text": "x"}).status_code == 404
    assert made["client"].get("/api/app/todos").json()["todos"] == []


def test_capture_surface_is_write_only(client, new_list):
    capture = new_list()["capture_token"]
    assert client.get(f"/api/c/{capture}").status_code == 405
    assert client.get(f"/api/c/{capture}/todos").status_code == 404


def test_a_session_is_not_an_agent_or_capture_credential(new_list):
    made = new_list()
    assert lists.resolve_agent(made["session"]) is None
    assert lists.resolve_capture(made["session"]) is None
    assert sessions.resolve(made["agent_token"]) is None
    assert sessions.resolve(made["capture_token"]) is None
    assert sessions.resolve(made["session"])["list_id"] == lists.resolve_agent(made["agent_token"])


def test_one_list_cannot_reach_another_over_http(new_list):
    a, b = new_list(), new_list()
    ca, cb = a["client"], b["client"]
    theirs = cb.post("/api/app/todos", json={"title": "B secret", "project": "B proj"}).json()
    assert ca.get(f"/api/app/todos/{theirs['id']}").status_code == 404
    assert ca.put(f"/api/app/todos/{theirs['id']}", json={"title": "x"}).status_code == 404
    assert ca.put(f"/api/app/projects/{theirs['project_id']}", json={"name": "x"}).status_code == 404
    res = ca.post("/api/app/todos", json={"title": "x", "project_id": theirs["project_id"]})
    assert res.status_code == 400
    assert ca.get("/api/app/todos").json()["todos"] == []
    assert cb.get(f"/api/app/todos/{theirs['id']}").json()["title"] == "B secret"


# ── Tab safety: X-List ────────────────────────────────────────────────────────


def test_the_session_reports_the_confirmed_email_and_the_caps_it_brings(new_list, confirm, monkeypatch):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    confirm(lid)
    body = c.get("/api/app/session").json()
    assert (body["email"], body["verified"]) == ("me@example.com", True)
    assert body["caps"] == {
        "todos": 5_000,
        "projects": 1_000,
        "areas": 100,
        "brains": 1,
        "links": 3,
        "brains_label": "1",
        "links_label": "3",
        "upsell": True,
        "storage": 500_000_000,
        "storage_used": 0,
    }
    monkeypatch.delenv("OPEN_SIGNUP")  # one-list self-host: its own caps, confirmed or not
    body = c.get("/api/app/session").json()
    assert body["hosted"] is False and body["caps"] == {
        "todos": 20_000,
        "projects": 1_000,
        "areas": 100,
        "brains": 100,
        "links": 1000,
        "brains_label": "Unlimited",
        "links_label": "Unlimited",
        "upsell": False,
        "storage": 100_000_000_000,
        "storage_used": 0,
    }


def test_every_other_app_route_needs_x_list_naming_this_list(new_list):
    made = new_list()
    c = made["client"]
    for value in ("", "x", str(made["list_id"] + 1)):
        res = c.get("/api/app/todos", headers={"X-List": value})
        assert res.status_code == 409 and res.json() == {"detail": {"list_changed": True}}
        assert res.headers["cache-control"] == "no-store"
    del c.headers["X-List"]
    for method, path, body in (
        ("GET", "todos", None),
        ("POST", "todos", {"title": "x"}),
        ("PUT", "email", {"email": "a@b.co"}),
        ("POST", "signout", None),
    ):
        assert c.request(method, f"/api/app/{path}", json=body).status_code == 409, path
    assert service.list_todos(made["list_id"]) == []
    assert lists.get_list(made["list_id"])["email"] is None
    assert c.get("/api/app/session").status_code == 200  # still signed in


def test_a_sign_in_in_another_tab_never_lets_this_tab_write_into_that_list(new_list):
    """Tab 1 shows list A. Tab 2 signs the same browser in to list B, so the
    cookie both tabs send is now B's. Tab 1's next write still names A: refused,
    and B is untouched. Reloading (the session call) shows B."""
    a, b = new_list(), new_list()
    tab1 = a["client"]
    swapped = {"Cookie": f"{sessions.COOKIE}={b['session']}"}
    res = tab1.post("/api/app/todos", json={"title": "meant for A"}, headers=swapped)
    assert res.status_code == 409 and res.json()["detail"] == {"list_changed": True}
    assert tab1.put("/api/app/email", json={"email": "a@b.co"}, headers=swapped).status_code == 409
    assert service.list_todos(b["list_id"]) == [] and service.list_todos(a["list_id"]) == []
    assert lists.get_list(b["list_id"])["email"] is None
    assert tab1.get("/api/app/session", headers=swapped).json()["list_id"] == b["list_id"]


# ── Cross-site requests ───────────────────────────────────────────────────────


def test_app_writes_must_come_from_this_site(new_list):
    made = new_list()
    c = made["client"]
    for site in ("cross-site", "same-site", "none"):
        res = c.post("/api/app/todos", json={"title": "x"}, headers={"Sec-Fetch-Site": site})
        assert res.status_code == 403 and res.headers["cache-control"] == "no-store", site
    assert c.get("/api/app/todos", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
    del c.headers["Sec-Fetch-Site"]  # an older browser: Origin decides
    assert c.post("/api/app/todos", json={"title": "x"}).status_code == 403  # neither header
    evil = {"Origin": "https://evil.example"}
    assert c.post("/api/app/todos", json={"title": "x"}, headers=evil).status_code == 403
    assert c.post("/api/app/signout", headers=evil).status_code == 403
    ours = {"Origin": "http://testserver"}
    assert c.post("/api/app/todos", json={"title": "ok"}, headers=ours).status_code == 200
    assert [t["title"] for t in service.list_todos(made["list_id"])] == ["ok"]


def test_without_sec_fetch_site_origin_must_be_the_configured_public_address(client, new_list, monkeypatch):
    # Behind a proxy the request's own address is internal; the configured one is
    # what a browser's Origin names.
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    made = new_list()
    c = made["client"]
    token = _link(made)
    del c.headers["Sec-Fetch-Site"]  # an older browser: Origin decides
    bare = TestClient(client.app)  # signed in to nothing, and sends no Origin by itself
    ours, theirs = {"Origin": "https://todo.example"}, {"Origin": "http://testserver"}

    # The address the request came in on is not this site's.
    assert c.post("/api/app/todos", json={"title": "x"}, headers=theirs).status_code == 403
    assert bare.post("/api/lists", headers=theirs).status_code == 403
    assert bare.post(f"/api/signin/{token}", headers=theirs).status_code == 403
    assert service.list_todos(made["list_id"]) == []

    assert c.post("/api/app/todos", json={"title": "ok"}, headers=ours).status_code == 200
    assert bare.post("/api/lists", headers=ours).status_code == 200
    assert bare.post(f"/api/signin/{token}", headers=ours).status_code == 200  # the refusal spent nothing
    bare.close()


def test_create_and_redeem_must_come_from_this_site_but_capture_need_not(client, new_list):
    bare = TestClient(client.app)  # sends neither Sec-Fetch-Site nor Origin by itself
    evil = {"Origin": "https://evil.example"}
    for headers in ({}, evil, {"Sec-Fetch-Site": "cross-site"}):
        res = bare.post("/api/lists", headers=headers)
        assert res.status_code == 403 and "set-cookie" not in res.headers
    made = new_list()
    token = made["client"].post("/api/app/signin-link").json()["url"].rsplit("/", 1)[1]
    # A cross-site form POST would sign the victim's browser in to the attacker's list.
    for headers in ({}, evil, {"Sec-Fetch-Site": "cross-site"}):
        res = bare.post(f"/api/signin/{token}", headers=headers)
        assert res.status_code == 403 and "set-cookie" not in res.headers
    # The refusals spent nothing.
    assert bare.post(f"/api/signin/{token}", headers={"Origin": "http://testserver"}).status_code == 200
    # Capture is token-authed and posted from anywhere (shortcuts, other apps).
    res = bare.post(f"/api/c/{made['capture_token']}", json={"text": "x"}, headers=evil)
    assert res.status_code == 200
    bare.close()


# ── Bounds per list ───────────────────────────────────────────────────────────


def test_at_most_twenty_sessions_per_list_and_the_newest_always_works(client, new_list, freeze):
    freeze("2026-10-11T12:00:00")  # one instant: the order falls to insertion
    made = new_list()
    tokens = [made["session"]]
    with db.transaction() as conn:
        tokens += [sessions.create_in(conn, made["list_id"]) for _ in range(sessions.MAX_PER_LIST)]
    assert [sessions.resolve(t) is not None for t in tokens] == [False] + [True] * 20
    assert db.get_db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 20
    assert made["client"].get("/api/app/todos").status_code == 401
    assert client.get("/api/app/todos", headers=_as(tokens[-1], made["list_id"])).status_code == 200


def test_the_least_recently_used_session_is_the_one_signed_out(new_list, freeze):
    freeze("2026-10-11T12:00:00")
    made = new_list()
    with db.transaction() as conn:
        tokens = [sessions.create_in(conn, made["list_id"]) for _ in range(19)]
    freeze("2026-10-11T14:00:00")
    made["client"].get("/api/app/todos")  # the first browser is used again
    with db.transaction() as conn:
        sessions.create_in(conn, made["list_id"])
    assert sessions.resolve(made["session"]) is not None
    assert sessions.resolve(tokens[0]) is None


def _link(made) -> str:
    """A sign-in link's token, from Connect's "Sign in on another device"."""
    return made["client"].post("/api/app/signin-link").json()["url"].rsplit("/", 1)[1]


def test_at_most_ten_unspent_sign_in_links_per_list(client, new_list, freeze):
    freeze("2026-10-11T12:00:00")
    made = new_list()
    tokens = [_link(made) for _ in range(11)]
    assert db.get_db().execute("SELECT COUNT(*) FROM signin_tokens").fetchone()[0] == 10
    assert client.post(f"/api/signin/{tokens[0]}").status_code == 404
    assert client.post(f"/api/signin/{tokens[-1]}").status_code == 200


def test_one_lists_caps_never_touch_another_list(client, new_list, freeze):
    freeze("2026-10-11T12:00:00")  # one instant: the order falls to insertion
    other, busy = new_list(), new_list()
    other_link = _link(other)
    for _ in range(11):
        _link(busy)  # before the sessions: the cap below signs the busy list's own browser out
    with db.transaction() as conn:
        for _ in range(sessions.MAX_PER_LIST + 1):
            sessions.create_in(conn, busy["list_id"])
    count = lambda table: (
        db.get_db()
        .execute(  # noqa: E731
            f"SELECT COUNT(*) FROM {table} WHERE list_id = ?", (busy["list_id"],)
        )
        .fetchone()[0]
    )
    assert (count("sessions"), count("signin_tokens")) == (sessions.MAX_PER_LIST, 10)
    # The busy list shed its own; the other list lost nothing.
    assert other["client"].get("/api/app/session").status_code == 200
    res = client.post(f"/api/signin/{other_link}")
    assert res.status_code == 200 and sessions.resolve(res.cookies[sessions.COOKIE])["list_id"] == other["list_id"]


# ── Signing in on another device, signing out ────────────────────────────────


def test_sign_in_on_another_device(client, new_list):
    made = new_list()
    res = made["client"].post("/api/app/signin-link")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    body = res.json()
    assert set(body) == {"url", "expires_at"} and body["url"].startswith("http://testserver/signin/")
    token = body["url"].rsplit("/", 1)[1]
    # Stored as a hash, and not as a mailed link.
    row = db.get_db().execute("SELECT token_hash, mailed_to, expires_at FROM signin_tokens").fetchone()
    assert tuple(row) == (lists.hash_token(token), None, body["expires_at"])

    # The phone (the shared client, signed in to nothing) opens it and presses the button.
    res = client.post(f"/api/signin/{token}")
    assert res.status_code == 200 and res.json() == {"verified": False}
    assert res.headers["cache-control"] == "no-store"
    assert _set_cookie(res)[0].startswith(f"{sessions.COOKIE}=")
    assert client.get("/api/app/session").json()["list_id"] == made["list_id"]
    # Both browsers are in, and nothing was rotated.
    assert made["client"].get("/api/app/todos").status_code == 200
    assert lists.resolve_agent(made["agent_token"]) == made["list_id"]
    assert lists.resolve_capture(made["capture_token"]) == made["list_id"]
    # Once only.
    replay = client.post(f"/api/signin/{token}")
    assert replay.status_code == 404 and "www-authenticate" not in replay.headers


def test_a_sign_in_link_works_for_one_hour(client, new_list, freeze):
    made = new_list()
    freeze("2026-10-11T12:00:00")
    issued = [made["client"].post("/api/app/signin-link").json() for _ in range(2)]
    first, second = (link["url"].rsplit("/", 1)[1] for link in issued)
    assert {link["expires_at"] for link in issued} == {"2026-10-11T13:00:00.000Z"}
    freeze("2026-10-11T13:00:00")
    assert client.post(f"/api/signin/{second}").status_code == 404
    freeze("2026-10-11T12:30:00")
    assert client.post(f"/api/signin/{second}").status_code == 404  # and it was spent
    assert client.get("/api/app/session").status_code == 401
    freeze("2026-10-11T12:59:59")  # the last second of the hour
    assert client.post(f"/api/signin/{first}").status_code == 200
    assert client.get("/api/app/session").json()["list_id"] == made["list_id"]


def test_sign_out_signs_out_only_this_browser(client, new_list):
    made = new_list()
    client.post(f"/api/signin/{_link(made)}")  # a second browser on the same list
    res = made["client"].post("/api/app/signout")
    assert res.status_code == 200 and res.json() == {"ok": True}
    assert made["client"].get("/api/app/todos").status_code == 401
    assert made["client"].get("/api/app/session").status_code == 401
    assert client.get("/api/app/todos", headers={"X-List": str(made["list_id"])}).status_code == 200
    assert lists.resolve_agent(made["agent_token"]) == made["list_id"]


def test_sign_out_everywhere_also_cancels_unspent_links(client, new_list):
    made = new_list()
    unspent = _link(made)
    client.post(f"/api/signin/{_link(made)}")
    assert made["client"].post("/api/app/signout-all").json() == {"ok": True}
    assert made["client"].get("/api/app/todos").status_code == 401
    assert client.get("/api/app/session").status_code == 401
    assert client.post(f"/api/signin/{unspent}").status_code == 404
    # The agent and capture links are separate, and keep working.
    assert lists.resolve_agent(made["agent_token"]) == made["list_id"]
    assert client.post(f"/api/c/{made['capture_token']}", json={"text": "x"}).status_code == 200


# ── Todos ─────────────────────────────────────────────────────────────────────


def test_app_responses_are_no_store(new_list):
    made = new_list()
    for path in ("todos", "today", "filters", "review", "projects", "areas", "capture-link", "session"):
        assert made["client"].get(f"/api/app/{path}").headers["cache-control"] == "no-store", path


def test_create_sets_ui_provenance_and_clients_cannot_choose_it(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(
        f"{api}/todos",
        json={
            "title": "x",
            "source": "agent",
            "source_client": "Evil",
            "list_id": 999,
        },
    ).json()
    assert (todo["source"], todo["source_client"]) == ("ui", None)
    res = c.post(f"{api}/todos/bulk", json={"ids": [todo["id"]], "fields": {"source": "agent"}})
    assert res.status_code == 400
    assert c.get(f"{api}/todos/{todo['id']}").json()["source"] == "ui"


def test_partial_update_omitted_versus_explicit_null(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(
        f"{api}/todos",
        json={
            "title": "x",
            "notes": "keep me",
            "due_date": "2030-01-02",
            "project": "P",
            "context": "@home",
            "tags": ["a"],
            "star": True,
            "repeat": "weekly",
        },
    ).json()
    url = f"{api}/todos/{todo['id']}"

    # Omitted fields are untouched.
    after = c.put(url, json={"title": "renamed"}).json()
    assert after["title"] == "renamed"
    for field in ("notes", "due_date", "project_id", "context", "tags", "star", "repeat"):
        assert after[field] == todo[field], field

    # Explicit null clears.
    after = c.put(
        url,
        json={
            "due_date": None,
            "project_id": None,
            "notes": None,
            "context": None,
            "tags": None,
            "repeat": None,
            "star": None,
        },
    ).json()
    assert after["due_date"] is None and after["project_id"] is None
    assert after["notes"] == "" and after["context"] == "" and after["tags"] == []
    assert after["repeat"] == "" and after["star"] is False
    assert after["title"] == "renamed"

    # A null title is not "leave it alone": it is an empty title, which is refused.
    assert c.put(url, json={"title": None}).status_code == 400
    # An empty body changes nothing and says so.
    assert c.put(url, json={}).status_code == 400
    assert c.put(f"{api}/todos/99999", json={"title": "x"}).status_code == 404


def test_archive_and_unarchive_a_todo(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(f"{api}/todos", json={"title": "x", "status": "next_action"}).json()
    url = f"{api}/todos/{todo['id']}"

    dropped = c.put(url, json={"status": "dropped"}).json()
    assert dropped["status"] == "dropped" and dropped["completed_at"] is None
    assert c.get(f"{api}/todos", params={"status": "next_action"}).json()["todos"] == []
    assert [t["id"] for t in c.get(f"{api}/todos", params={"status": "dropped"}).json()["todos"]] == [todo["id"]]
    assert c.get(f"{api}/today").json()["todos"] == []
    assert c.get(url).status_code == 200  # archived, not gone

    restored = c.put(url, json={"status": "next_action"}).json()
    assert restored["status"] == "next_action"
    assert c.get(f"{api}/filters").json()["status_counts"]["dropped"] == 0


def test_archive_and_unarchive_a_project(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    project = c.post(f"{api}/projects", json={"name": "P"}).json()
    url = f"{api}/projects/{project['id']}"
    assert c.put(url, json={"status": "dropped"}).json()["status"] == "dropped"
    assert c.get(f"{api}/projects", params={"status": "active"}).json()["projects"] == []
    assert c.put(url, json={"status": "active"}).json()["status"] == "active"
    assert c.post(f"{api}/projects", json={"name": "p"}).status_code == 400  # duplicate


def test_complete_repeating_todo_over_http(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(
        f"{api}/todos",
        json={
            "title": "water",
            "status": "next_action",
            "repeat": "weekly",
            "due_date": "2099-06-01",
        },
    ).json()
    assert c.put(f"{api}/todos/{todo['id']}", json={"status": "done"}).json()["status"] == "done"
    assert c.put(f"{api}/todos/{todo['id']}", json={"status": "done"}).status_code == 200
    nxt = c.get(f"{api}/todos", params={"status": "next_action"}).json()["todos"]
    assert [(t["title"], t["due_date"], t["source"]) for t in nxt] == [("water", "2099-06-08", "ui")]


def test_bulk_update_over_http(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    ids = [c.post(f"{api}/todos", json={"title": t}).json()["id"] for t in "ab"]
    res = c.post(f"{api}/todos/bulk", json={"ids": ids + [999], "fields": {"status": "someday_maybe"}})
    assert res.json() == {"updated": ids, "not_found": [999]}
    assert c.post(f"{api}/todos/bulk", json={"ids": list(range(501)), "fields": {"star": True}}).status_code == 422
    assert c.post(f"{api}/todos/bulk", json={"ids": ids, "fields": {}}).status_code == 400


def test_bulk_update_rejects_a_string_for_a_boolean(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(f"{api}/todos", json={"title": "x", "star": True}).json()
    for field in ("star", "auto_star_on_due"):
        res = c.post(f"{api}/todos/bulk", json={"ids": [todo["id"]], "fields": {field: "false"}})
        assert res.status_code == 400 and "true or false" in res.json()["detail"]
    res = c.post(f"{api}/todos/bulk", json={"ids": [todo["id"]], "fields": {"star": False}})
    assert res.status_code == 200
    assert c.get(f"{api}/todos/{todo['id']}").json()["star"] is False


def test_validation_errors_are_400_with_a_message(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    res = c.post(f"{api}/todos", json={"title": "x", "due_date": "tomorrow"})
    assert res.status_code == 400 and "YYYY-MM-DD" in res.json()["detail"]
    assert c.get(f"{api}/todos", params={"status": "bogus"}).status_code == 400
    assert c.get(f"{api}/todos", params={"limit": 501}).status_code == 422
    assert c.post(f"{api}/todos", json={"title": "x" * 20_001}).status_code == 422


def test_out_of_range_input_is_400_not_a_crash(new_list):
    made = new_list()
    c, api, huge = made["client"], made["api"], 10**20  # beyond SQLite's 64-bit integers
    assert c.get(f"{api}/todos/{huge}").status_code == 400
    assert c.put(f"{api}/projects/{huge}", json={"name": "a"}).status_code == 400
    assert c.post(f"{api}/todos", json={"title": "x", "project_id": huge}).status_code == 400
    bulk = {"ids": [huge], "fields": {"star": True}}
    assert c.post(f"{api}/todos/bulk", json=bulk).status_code == 400
    # An over-long digit string is not an id; it falls through to the name lookup.
    assert c.get(f"{api}/todos", params={"project": "9" * 25}).json() == {"todos": []}
    assert c.get(f"{api}/todos", params={"project": "²"}).json() == {"todos": []}
    # A repeat cannot step past the last representable date; the completion rolls back.
    todo = c.post(f"{api}/todos", json={"title": "x", "repeat": "daily", "due_date": "9999-12-31"}).json()
    assert c.put(f"{api}/todos/{todo['id']}", json={"status": "done"}).status_code == 400
    assert c.get(f"{api}/todos/{todo['id']}").json()["status"] == "inbox"


def test_total_caps_over_http(client, new_list, monkeypatch):
    made = new_list()
    c, api = made["client"], made["api"]
    monkeypatch.setattr(common, "ANON_CAPS", (2, 1, 10))
    first = c.post(f"{api}/todos", json={"title": "a", "project": "P"}).json()
    c.put(f"{api}/todos/{first['id']}", json={"status": "dropped"})  # archived still counts
    assert c.post(f"{api}/todos", json={"title": "b"}).status_code == 200

    res = c.post(f"{api}/todos", json={"title": "c"})
    # The detail is the sentence the app shows (and what its "add your email" banner keys on).
    assert res.status_code == 400 and res.json()["detail"] == (
        "This list holds 2 todos until an email is confirmed under Connect. Nothing was changed."
    )
    assert client.post(f"/api/c/{made['capture_token']}", json={"text": "d"}).status_code == 400
    assert c.post(f"{api}/projects", json={"name": "Q"}).status_code == 400
    # Existing data is untouched and still editable.
    assert len(c.get(f"{api}/todos").json()["todos"]) == 2
    assert c.put(f"{api}/todos/{first['id']}", json={"title": "still editable"}).status_code == 200


# ── Capture ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def capture(new_list):
    made = new_list()
    made["capture"] = made["client"].get(f"{made['api']}/capture-link").json()
    return made


def test_capture_link_shape(capture):
    link = capture["capture"]
    assert link["url"] == f"http://testserver/c/{link['token']}"
    assert link["token"] not in (capture["session"], capture["agent_token"])


def test_capture_success_shape_and_lands_in_inbox(client, capture):
    res = client.post(f"/api/c/{capture['capture']['token']}", json={"text": "  buy milk  "})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"ok", "id"} and body["ok"] is True  # write-only: nothing read back
    todo = capture["client"].get(f"{capture['api']}/todos/{body['id']}").json()
    assert (todo["title"], todo["status"], todo["source"]) == ("buy milk", "inbox", "capture")


def test_capture_unknown_token_is_404(client, capture):
    res = client.post("/api/c/not-a-real-token", json={"text": "x"})
    assert res.status_code == 404
    assert "www-authenticate" not in res.headers


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"json": {"text": "   "}}, 400),
        ({"json": {}}, 400),
        ({"json": {"text": 5}}, 400),
        ({"json": ["text"]}, 400),
        ({"content": b"not json"}, 400),
        ({"content": b""}, 400),
        ({"json": {"text": "x" * 20_001}}, 400),
        ({"content": b"x" * (64 * 1024 + 1)}, 413),
    ],
)
def test_capture_rejects_bad_bodies(client, capture, kwargs, status):
    assert client.post(f"/api/c/{capture['capture']['token']}", **kwargs).status_code == status
    assert capture["client"].get(f"{capture['api']}/todos").json()["todos"] == []


def test_capture_oversize_is_refused_from_the_declared_length_alone(client, capture):
    res = client.post(
        f"/api/c/{capture['capture']['token']}",
        content=b"{}",
        headers={"content-length": str(64 * 1024 + 1)},
    )
    assert res.status_code == 413


def test_capture_oversize_chunked_body_is_refused(client, capture):
    # A generator body is sent chunked, with no Content-Length to check up front.
    res = client.post(f"/api/c/{capture['capture']['token']}", content=(b"a" * 4096 for _ in range(17)))
    assert res.status_code == 413


def test_capture_deeply_nested_json_is_a_400(client, capture):
    res = client.post(f"/api/c/{capture['capture']['token']}", content=b"[" * 60_000)
    assert res.status_code == 400


def test_capture_is_rate_limited_before_the_token_lookup(client, capture):
    token = capture["capture"]["token"]
    for _ in range(30):
        assert client.post(f"/api/c/{token}", json={"text": "x"}).status_code == 200
    assert client.post(f"/api/c/{token}", json={"text": "x"}).status_code == 429
    assert client.post("/api/c/unknown", json={"text": "x"}).status_code == 429
    assert len(capture["client"].get(f"{capture['api']}/todos").json()["todos"]) == 30


def test_capture_is_also_limited_per_token_across_ips(client, capture):
    token = capture["capture"]["token"]
    for _ in range(30):
        assert router.capture_token_limiter.allow(token)
    assert client.post(f"/api/c/{token}", json={"text": "x"}).status_code == 429


# ── Link management ───────────────────────────────────────────────────────────


def test_rotate_capture_link(client, capture):
    c, old = capture["client"], capture["capture"]["token"]
    res = c.post(f"{capture['api']}/capture-link/rotate")
    assert res.headers["cache-control"] == "no-store"
    new = res.json()["token"]
    assert new != old
    assert client.post(f"/api/c/{old}", json={"text": "x"}).status_code == 404
    assert client.post(f"/api/c/{new}", json={"text": "x"}).status_code == 200
    assert c.get(f"{capture['api']}/capture-link").json()["token"] == new


def test_the_agent_link_can_always_be_shown_again(capture):
    res = capture["client"].get(f"{capture['api']}/agent-link")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json() == {
        "url": f"http://testserver/link/{capture['agent_token']}",
        "token": capture["agent_token"],
    }


def test_regenerating_the_agent_link_leaves_the_session_and_capture_link_alone(capture):
    c, api = capture["client"], capture["api"]
    res = c.post(f"{api}/agent-link/rotate")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    new = res.json()
    assert new["token"] != capture["agent_token"]
    assert new["url"] == f"http://testserver/link/{new['token']}"
    assert lists.resolve_agent(capture["agent_token"]) is None
    assert lists.resolve_agent(new["token"]) == capture["list_id"]
    # The browser stays signed in, and shows the new agent link.
    assert c.get(f"{api}/agent-link").json() == new
    assert c.get(f"{api}/capture-link").json()["token"] == capture["capture"]["token"]


def test_regenerating_the_capture_link_leaves_the_agent_link_alone(capture):
    c = capture["client"]
    c.post(f"{capture['api']}/capture-link/rotate")
    assert c.get(f"{capture['api']}/agent-link").json()["token"] == capture["agent_token"]


def test_set_change_and_clear_the_email(new_list):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    res = c.put("/api/app/email", json={"email": " Me@Example.com "})
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json() == {
        "email": "me@example.com",
        "verified": False,
        "sent": False,
        "caps": {"todos": 200, "projects": 20, "areas": 10},
    }
    assert lists.get_list(lid)["email"] == "me@example.com"
    assert c.get("/api/app/session").json()["email"] == "me@example.com"
    assert c.put("/api/app/email", json={"email": "nope"}).status_code == 400
    assert lists.get_list(lid)["email"] == "me@example.com"
    assert c.put("/api/app/email", json={"email": None}).json()["email"] is None
    assert lists.get_list(lid)["email"] is None
    # Changing the address never signs this browser out.
    assert c.get("/api/app/todos").status_code == 200
    # Without mail nothing is minted to confirm it.
    assert db.get_db().execute("SELECT COUNT(*) FROM signin_tokens").fetchone()[0] == 0


def test_saving_an_email_mails_a_link_that_confirms_it(client, new_list, mail):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    res = c.put("/api/app/email", json={"email": "me@example.com"})
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json() == {
        "email": "me@example.com",
        "verified": False,
        "sent": True,
        "caps": {"todos": 200, "projects": 20, "areas": 10},
    }
    assert [to for to, _ in mail] == ["me@example.com"]
    assert c.get("/api/app/session").json()["verified"] is False

    token = mail[0][1].split("/signin/")[1].split()[0]
    redeemed = client.post(f"/api/signin/{token}")  # opened on another device
    assert redeemed.status_code == 200 and redeemed.json() == {"verified": True}
    body = c.get("/api/app/session").json()
    assert body["verified"] is True and body["caps"]["todos"] == 5_000

    # The same address again: still confirmed, nothing mailed. (The limiter is emptied so
    # it is the confirmation, not the address's 15-minute budget, that holds the mail back.)
    signin.confirm_limiter.clear()
    assert c.put("/api/app/email", json={"email": "ME@example.com"}).json() == {
        "email": "me@example.com",
        "verified": True,
        "sent": False,
        "caps": {"todos": 5_000, "projects": 1_000, "areas": 100},
    }
    # A new address starts over, unconfirmed, with the anonymous caps.
    assert c.put("/api/app/email", json={"email": "new@example.com"}).json() == {
        "email": "new@example.com",
        "verified": False,
        "sent": True,
        "caps": {"todos": 200, "projects": 20, "areas": 10},
    }
    body = c.get("/api/app/session").json()
    assert body["verified"] is False and body["caps"]["todos"] == 200
    # Clearing it: no address, nothing confirmed, nothing mailed.
    assert c.put("/api/app/email", json={"email": ""}).json() == {
        "email": None,
        "verified": False,
        "sent": False,
        "caps": {"todos": 200, "projects": 20, "areas": 10},
    }
    assert len(mail) == 2 and lists.get_list(lid)["email_verified_at"] is None


def test_an_email_another_account_confirmed_mails_the_way_back_to_it(client, new_list, mail, confirm):
    old, new = new_list(), new_list()
    confirm(old["list_id"], "kid@example.com")
    stranger = new_list()
    stranger["client"].put("/api/app/email", json={"email": "other@example.com"})
    signin.confirm_limiter.clear()
    mail.clear()

    # The answer is a plain "saved, sent", the same as for a new address: it never
    # says whether the address has an account.
    res = new["client"].put("/api/app/email", json={"email": "Kid@example.com"})
    assert res.json() == {
        "email": "kid@example.com",
        "verified": False,
        "sent": True,
        "caps": {"todos": 200, "projects": 20, "areas": 10},
    }
    [(to, text)] = mail
    assert to == "kid@example.com" and "already belongs to your account" in text

    # The link is to the OLD account, and the new one stays unconfirmed.
    token = text.split("/signin/")[1].split()[0]
    back = client.post(f"/api/signin/{token}")
    assert back.status_code == 200 and back.json() == {"verified": True}
    assert lists.get_list(old["list_id"])["email_verified_at"] is not None
    assert lists.get_list(new["list_id"])["email_verified_at"] is None

    # A confirmation link minted before another account confirmed the address
    # still signs in, but no longer confirms: one account per address.
    signin.confirm_limiter.clear()
    mail.clear()
    stranger["client"].put("/api/app/email", json={"email": "late@example.com"})
    confirm(new["list_id"], "late@example.com")
    late = mail[0][1].split("/signin/")[1].split()[0]
    assert client.post(f"/api/signin/{late}").json() == {"verified": False}
    assert lists.get_list(stranger["list_id"])["email_verified_at"] is None

    # A disabled account still holds its address: nothing is mailed (its link could
    # not be redeemed) and the new list is not confirmed, so enabling it again later
    # cannot leave two accounts on one address. The answer is the same.
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), old["list_id"]))
    other = new_list()
    signin.confirm_limiter.clear()
    mail.clear()
    assert other["client"].put("/api/app/email", json={"email": "kid@example.com"}).json()["sent"] is True
    assert mail == [] and lists.get_list(other["list_id"])["email_verified_at"] is None


def test_change_the_time_zone(new_list, freeze):
    made = new_list("America/Chicago")
    c, api = made["client"], made["api"]
    # 02:00 UTC on Aug 2: still Aug 1 in Chicago, already Aug 2 in Tokyo.
    freeze("2026-08-02T02:00:00")
    c.post(f"{api}/todos", json={"title": "due the 2nd", "due_date": "2026-08-02", "status": "next_action"})
    assert c.get(f"{api}/today").json()["todos"] == []

    res = c.put(f"{api}/tz", json={"tz": "Asia/Tokyo"})
    assert res.status_code == 200 and res.json() == {"tz": "Asia/Tokyo"}
    assert c.get(f"{api}/filters").json()["tz"] == "Asia/Tokyo"
    assert [t["title"] for t in c.get(f"{api}/today").json()["todos"]] == ["due the 2nd"]

    # An unknown zone is refused, not silently stored as UTC.
    assert c.put(f"{api}/tz", json={"tz": "Mars/Olympus"}).status_code == 400
    assert c.put(f"{api}/tz", json={}).status_code == 422
    assert c.get(f"{api}/filters").json()["tz"] == "Asia/Tokyo"


# ── Weekly review ─────────────────────────────────────────────────────────────


def test_the_review_page_reads_the_weekly_review_stamp_and_can_mark_one_done(new_list, freeze):
    freeze("2026-09-20T15:00:00")
    made = new_list("America/Chicago")
    c, api, lid = made["client"], made["api"], made["list_id"]
    # A new list has had no review and, like the agents' hint, is not nagged for one.
    assert c.get(f"{api}/review").json() == {"review_due": False, "days_since_review": None}
    # Over a week old and still none: due, with nothing to count from.
    freeze("2026-09-28T15:00:00")
    assert c.get(f"{api}/review").json() == {"review_due": True, "days_since_review": None}
    assert lists.review_due(lid) is True

    # "Mark review done" leaves the stamp an agent's todo_weekly_review leaves,
    # so the agents' hint goes quiet too.
    now = freeze("2026-10-04T15:00:00")  # 10:00 in Chicago
    res = c.post(f"{api}/review/done")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json() == {"review_due": False, "days_since_review": 0}
    assert lists.get_list(lid)["review_started_at"] == common.to_iso(now)
    assert lists.review_due(lid) is False

    # Counted in the list's calendar days: 23:50 that Chicago evening is still
    # today, ten past midnight is yesterday (both are Oct 5 in UTC).
    freeze("2026-10-05T04:50:00")
    assert c.get(f"{api}/review").json() == {"review_due": False, "days_since_review": 0}
    freeze("2026-10-05T05:10:00")
    assert c.get(f"{api}/review").json() == {"review_due": False, "days_since_review": 1}
    # A week and a minute after the stamp it is due again.
    freeze("2026-10-11T15:01:00")
    assert c.get(f"{api}/review").json() == {"review_due": True, "days_since_review": 7}


def test_marking_a_review_done_is_a_write_from_this_site_into_this_list(new_list):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    cross = c.post("/api/app/review/done", headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    assert c.post("/api/app/review/done", headers={"X-List": str(lid + 1)}).status_code == 409
    assert c.get("/api/app/review/done").status_code == 405  # a GET never stamps
    assert lists.get_list(lid)["review_started_at"] is None


def test_config_is_public_and_says_whether_this_browser_is_signed_in(client):
    assert client.get("/api/config").json() == {
        "mail": False,
        "open_signup": True,
        "claimed": False,
        "reset": False,
        "signed_in": False,
        "billing": False,
        "app": "todo",
        "apps": {
            "todo": {"title": "Todo GTD", "url": "http://testserver"},
            "notes": {"title": "Notes GTD", "url": "http://testserver/notes"},
            "projects": {"title": "Projects GTD", "url": "http://testserver/projects"},
            "sites": {"title": "Simple Sites", "url": "http://testserver/sites"},
            "brain": {"title": "Common Brain", "url": "http://testserver/brain"},
        },
        "moved": "",
        "sites_short_host": "",
    }
    client.post("/api/lists")
    assert client.get("/api/config").json()["signed_in"] is True
    list_id = client.get("/api/app/session").json()["list_id"]
    client.post("/api/app/signout", headers={"X-List": str(list_id)})
    assert client.get("/api/config").json()["signed_in"] is False


def test_app_requests_mark_the_list_as_used_and_the_session_call_does_not(new_list):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    c.get("/api/app/session")
    assert lists.get_list(lid)["last_used_at"] is None
    c.get("/api/app/filters")
    assert lists.get_list(lid)["last_used_at"] is not None
