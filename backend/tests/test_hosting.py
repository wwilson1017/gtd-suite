"""Hosted and self-host plumbing: the two modes, reset, limits behind a proxy,
cleanup, snapshots and one-list repair, sign-in mail, and log scrubbing."""

import datetime
import io
import json
import logging
import os
import re
import sqlite3
import threading

import pytest

from backend import (
    backup,
    cleanup,
    common,
    db,
    lists,
    logscrub,
    ratelimit,
    router,
    service,
    sessions,
    signin,
)
from backend.tests.conftest import confirm_list
from backend.tests.test_mcp import INIT, MCP_HEADERS
from scripts import admin, restore_list


@pytest.fixture()
def single(monkeypatch, client):
    """The self-host default: one list per server."""
    monkeypatch.delenv("OPEN_SIGNUP")
    return client


# ── Modes ─────────────────────────────────────────────────────────────────────


def test_one_list_mode_is_the_default_and_the_first_visit_claims_it(single, new_list):
    assert single.get("/api/config").json() == {
        "mail": False,
        "open_signup": False,
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
        "sites_short_host": "",
    }
    first = new_list("Europe/Paris")
    second = single.post("/api/lists")  # another browser
    assert second.status_code == 409 and "already set up" in second.json()["detail"]
    assert "set-cookie" not in second.headers
    assert single.get("/api/config").json()["claimed"] is True
    assert single.get("/api/config").headers["cache-control"] == "no-store"
    # The refused create made nothing and left the first list alone.
    assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
    assert first["client"].get("/api/app/filters").json()["tz"] == "Europe/Paris"


def test_two_first_visitors_at_once_get_exactly_one_list(todo_db):
    barrier, made = threading.Barrier(8), []

    def claim():
        barrier.wait()
        made.append(lists.create_list("UTC", only_if_none=True))

    threads = [threading.Thread(target=claim) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([m for m in made if m]) == 1
    assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1


def test_open_signup_makes_many_lists_and_never_reports_claimed(client, create):
    assert create().status_code == 200
    assert create().status_code == 200
    assert client.get("/api/config").json() == {
        "mail": False,
        "open_signup": True,
        "claimed": False,
        "reset": False,
        "signed_in": True,
        "billing": False,
        "app": "todo",
        "apps": {
            "todo": {"title": "Todo GTD", "url": "http://testserver"},
            "notes": {"title": "Notes GTD", "url": "http://testserver/notes"},
            "projects": {"title": "Projects GTD", "url": "http://testserver/projects"},
            "sites": {"title": "Simple Sites", "url": "http://testserver/sites"},
            "brain": {"title": "Common Brain", "url": "http://testserver/brain"},
        },
        "sites_short_host": "",
    }


# ── Reset ─────────────────────────────────────────────────────────────────────


def test_reset_does_not_exist_without_a_code_or_with_open_signup(single, monkeypatch):
    single.post("/api/lists")
    assert single.post("/api/reset", json={"code": ""}).status_code == 404
    monkeypatch.setenv("RESET_CODE", "s3cret")
    monkeypatch.setenv("OPEN_SIGNUP", "true")
    assert single.post("/api/reset", json={"code": "s3cret"}).status_code == 404
    assert single.get("/api/config").json()["reset"] is False


def test_reset_with_the_code_takes_the_list_back_and_signs_this_browser_in(single, new_list, monkeypatch):
    old = new_list()
    old["client"].post("/api/app/todos", json={"title": "keep me"})
    old["client"].put("/api/app/email", json={"email": "me@example.com"})
    monkeypatch.setenv("RESET_CODE", "s3cret")
    assert single.get("/api/config").json()["reset"] is True

    wrong = single.post("/api/reset", json={"code": "s3cre"})
    assert wrong.status_code == 403 and "www-authenticate" not in wrong.headers
    assert old["client"].get("/api/app/filters").status_code == 200

    res = single.post("/api/reset", json={"code": "s3cret"})
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json() == {"ok": True} and res.headers["set-cookie"].startswith(f"{sessions.COOKIE}=")
    # Taking the deployment back: whoever held a browser session, the agent link,
    # the capture link or the email is out.
    assert old["client"].get("/api/app/filters").status_code == 401
    assert lists.resolve_agent(old["agent_token"]) is None
    assert lists.resolve_capture(old["capture_token"]) is None
    assert lists.get_list(old["list_id"])["email"] is None
    # This browser is in, and shows the new links; the todos are untouched.
    in_list = {"X-List": str(single.get("/api/app/session").json()["list_id"])}
    agent = single.get("/api/app/agent-link", headers=in_list).json()["token"]
    capture = single.get("/api/app/capture-link", headers=in_list).json()["token"]
    assert agent != old["agent_token"] and lists.resolve_agent(agent) == old["list_id"]
    assert capture != old["capture_token"] and lists.resolve_capture(capture) == old["list_id"]
    todos = single.get("/api/app/todos", headers=in_list).json()["todos"]
    assert [t["title"] for t in todos] == ["keep me"]


def test_reset_cancels_unspent_sign_in_links(single, new_list, monkeypatch):
    made = new_list()
    token = made["client"].post("/api/app/signin-link").json()["url"].rsplit("/", 1)[1]
    monkeypatch.setenv("RESET_CODE", "s3cret")
    assert single.post("/api/reset", json={"code": "s3cret"}).status_code == 200
    assert single.post(f"/api/signin/{token}").status_code == 404


def test_after_a_reset_the_former_email_gets_no_sign_in_link(single, new_list, mail, monkeypatch):
    made = new_list()
    # Confirmed the real way: saved under Connect, the mailed link opened.
    made["client"].put("/api/app/email", json={"email": "me@example.com"})
    assert made["client"].post(f"/api/signin/{_links(mail[0][1])[0]}").json() == {"verified": True}
    signin.address_limiter.clear()
    single.post("/api/signin", json={"email": "me@example.com"})
    assert len(mail) == 2  # before the reset, the address gets a sign-in link
    monkeypatch.setenv("RESET_CODE", "s3cret")
    assert single.post("/api/reset", json={"code": "s3cret"}).status_code == 200
    row = lists.get_list(made["list_id"])
    assert (row["email"], row["email_verified_at"]) == (None, None)
    signin.address_limiter.clear()
    single.post("/api/signin", json={"email": "me@example.com"})
    assert len(mail) == 2


def test_reset_must_come_from_this_site(single, monkeypatch):
    single.post("/api/lists")
    monkeypatch.setenv("RESET_CODE", "s3cret")
    res = single.post("/api/reset", json={"code": "s3cret"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403 and "set-cookie" not in res.headers


def test_reset_before_any_list_exists_is_a_404(single, monkeypatch):
    monkeypatch.setenv("RESET_CODE", "s3cret")
    assert single.post("/api/reset", json={"code": "s3cret"}).status_code == 404


def test_reset_attempts_are_rate_limited_per_ip(single, monkeypatch):
    single.post("/api/lists")
    monkeypatch.setenv("RESET_CODE", "s3cret")
    codes = [single.post("/api/reset", json={"code": "nope"}).status_code for _ in range(6)]
    assert codes == [403] * 5 + [429]
    # Over the limit, even the right code waits.
    assert single.post("/api/reset", json={"code": "s3cret"}).status_code == 429


# ── Limits, and whose address they are keyed on ───────────────────────────────


def test_a_forwarded_address_is_ignored_unless_the_proxy_is_trusted(create):
    codes = [create(headers={"X-Real-IP": f"203.0.113.{n}"}).status_code for n in range(11)]
    assert codes == [200] * 10 + [429]  # all one peer, whatever the header claims


def test_with_trust_proxy_each_forwarded_address_has_its_own_budget(create, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    a, b = {"X-Real-IP": "203.0.113.7"}, {"X-Real-IP": "203.0.113.8"}
    assert [create(headers=a).status_code for _ in range(11)] == [200] * 10 + [429]
    assert create(headers=b).status_code == 200
    assert create(headers=a).status_code == 429


def test_the_trusted_header_is_configurable_and_takes_the_first_hop(create, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setenv("TRUSTED_IP_HEADER", "X-Forwarded-For")
    seen = []
    monkeypatch.setattr(router.create_limiter, "allow", lambda ip: seen.append(ip) or True)
    create(headers={"X-Forwarded-For": "198.51.100.4, 100.64.0.2", "X-Real-IP": "203.0.113.9"})
    create()  # header absent: the peer
    assert seen == ["198.51.100.4", "testclient"]


def test_wrong_tokens_are_throttled_but_a_valid_link_is_always_served(client, new_list, monkeypatch):
    """One bad actor (or one misconfigured AI tool) behind a shared address must
    not lock everyone there out of their own lists: only MISSES are refused."""
    made = new_list()
    capture = made["capture_token"]
    monkeypatch.setattr(ratelimit.bad_token_limiter, "max_hits", 4)
    assert client.get("/c/nope").status_code == 404
    assert client.post("/api/c/nope", json={"text": "x"}).status_code == 404
    assert client.post("/api/signin/nope").status_code == 404
    assert client.get("/c/nope/manifest.webmanifest").status_code == 404
    # The address has used up its misses: every further miss is a 429…
    for method, path in (
        ("POST", "/api/signin/nope"),
        ("GET", "/c/nope"),
        ("GET", "/c/nope/manifest.webmanifest"),
        ("POST", "/api/c/nope"),
        ("GET", "/link/nope"),
        ("POST", "/mcp/nope"),
        ("POST", "/nope/mcp"),
    ):
        res = client.request(method, path, json={"text": "x"} if method == "POST" else None)
        assert res.status_code == 429, path
        assert "retry-after" in res.headers and "www-authenticate" not in res.headers
    wrong_bearer = client.post("/mcp", headers={"Authorization": "Bearer nope"})
    assert wrong_bearer.status_code == 429 and "www-authenticate" not in wrong_bearer.headers
    # …while every VALID link from the same address still works.
    assert made["client"].get("/api/app/todos").status_code == 200
    assert made["client"].post("/api/app/todos", json={"title": "still mine"}).status_code == 200
    assert client.get(f"/c/{capture}/manifest.webmanifest").status_code == 200
    assert client.post(f"/api/c/{capture}", json={"text": "x"}).status_code == 200
    # A stale cookie and an old /w/ link are not guesses: no 429 for them.
    stale = {"Cookie": f"{sessions.COOKIE}=nope", "X-List": "1"}
    assert client.get("/api/app/todos", headers=stale).status_code == 401
    assert client.get("/w/nope").status_code == 404
    # (The agent link under the same exhausted bucket is covered in test_mcp.py.)


def test_right_tokens_and_stale_cookies_never_count_as_wrong_ones(client, new_list, monkeypatch):
    made = new_list()
    monkeypatch.setattr(ratelimit.bad_token_limiter, "max_hits", 2)
    assert {made["client"].get("/api/app/todos").status_code for _ in range(5)} == {200}
    stale = {"Cookie": f"{sessions.COOKIE}=nope", "X-List": "1"}
    assert {client.get("/api/app/todos", headers=stale).status_code for _ in range(5)} == {401}
    assert client.post("/api/c/nope", json={"text": "x"}).status_code == 404  # bucket untouched


def test_writes_are_limited_per_list_not_per_session(client, new_list, monkeypatch):
    a, b = new_list(), new_list()
    monkeypatch.setattr(router.write_limiter, "max_hits", 3)
    codes = [a["client"].post("/api/app/todos", json={"title": "x"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    res = a["client"].post("/api/app/todos", json={"title": "x"})
    assert res.headers["cache-control"] == "no-store" and res.headers["retry-after"] == "60"
    assert a["client"].get("/api/app/todos").status_code == 200  # reads go on
    assert b["client"].post("/api/app/todos", json={"title": "x"}).status_code == 200
    # A second browser does not buy a new budget: the limit follows the list.
    token, _ = signin.issue_link(a["list_id"])
    client.post(f"/api/signin/{token}")
    in_a = {"X-List": str(a["list_id"])}
    assert client.post("/api/app/todos", json={"title": "x"}, headers=in_a).status_code == 429


# ── Cleanup of lists nobody ever used ─────────────────────────────────────────


def _aged(list_id, days):
    then = common.to_iso(common.utcnow() - datetime.timedelta(days=days))
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = ? WHERE id = ?", (then, list_id))


def test_cleanup_deletes_only_old_lists_with_nothing_in_them(todo_db):
    make = lambda: lists.create_list("UTC")["list_id"]  # noqa: E731
    empty_old, empty_new, dropped, project, area, email = (make() for _ in range(6))
    todo = service.create_todo(dropped, "archived", source="ui")
    service.update_todo(dropped, todo["id"], {"status": "dropped"})
    service.create_project(project, "P")
    service.create_area(area, "A")
    lists.set_email(email, "me@example.com")
    for lid in (empty_old, dropped, project, area, email):
        _aged(lid, 31)
    _aged(empty_new, 29)
    for lid in (empty_old, empty_new, dropped, project, area, email):
        signin.issue_link(lid)  # opened, and a link issued: empty_old is still never used
        with db.transaction() as conn:
            sessions.create_in(conn, lid)

    assert cleanup.delete_unused_lists() == 1
    left = {r["id"] for r in db.get_db().execute("SELECT id FROM lists")}
    assert left == {empty_new, dropped, project, area, email}
    # Its session and sign-in link went with it; every other list keeps its own.
    for table in ("sessions", "signin_tokens"):
        assert {r[0] for r in db.get_db().execute(f"SELECT list_id FROM {table}")} == left, table
    assert cleanup.delete_unused_lists() == 0


def test_the_maintenance_loop_expires_always_and_cleans_up_only_with_open_signup(single, monkeypatch):
    import asyncio
    from backend import main

    monkeypatch.setattr(main.settings, "snapshot_interval", lambda: 0.01)
    monkeypatch.setattr(main.backup, "snapshot", lambda: None)

    async def one_pass():
        task = asyncio.create_task(main._maintain())
        await asyncio.sleep(0.3)  # many intervals; the first pass runs the cleanup
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    lid = lists.create_list("UTC")["list_id"]
    _aged(lid, 31)
    signin.issue_link(lid)
    with db.transaction() as conn:  # a year idle, and past its hour
        conn.execute("UPDATE sessions SET last_used_at = '2020-01-01T00:00:00.000Z'")
        conn.execute("UPDATE signin_tokens SET expires_at = '2020-01-01T00:00:00.000Z'")
    asyncio.run(one_pass())
    assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1  # one-list server
    # Expiry runs on every server.
    for table in ("sessions", "signin_tokens"):
        assert db.get_db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    monkeypatch.setenv("OPEN_SIGNUP", "true")
    asyncio.run(one_pass())
    assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0


# ── Snapshots ─────────────────────────────────────────────────────────────────


def _names():
    return sorted(p.name for p in backup.backups_dir().iterdir())


def test_snapshot_is_a_complete_database_with_no_temp_file_left(L):
    service.create_todo(L, "in the snapshot", source="ui")
    path = backup.snapshot()
    assert path is not None and path.parent == backup.backups_dir()
    assert _names() == [path.name] and re.fullmatch(r"todo-\d{8}T\d{6}Z\.db", path.name)
    snap = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    assert snap.execute("SELECT title FROM todos").fetchall() == [("in the snapshot",)]
    assert snap.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    snap.close()


def test_a_failed_snapshot_is_logged_and_skipped(L, monkeypatch, caplog):
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    with monkeypatch.context() as broken, caplog.at_level(logging.ERROR):
        broken.setattr(backup.sqlite3, "connect", boom)
        assert backup.snapshot() is None
    assert "Snapshot failed" in caplog.text
    assert backup.snapshot() is not None  # the next run is unaffected
    assert not [n for n in _names() if n.endswith(".tmp")]


def test_snapshots_pause_with_a_warning_when_space_is_low(L, monkeypatch, caplog):
    # The floor is the live database's size plus MIN_FREE_BYTES: one byte short pauses, exact proceeds.
    need = db.db_path().stat().st_size + backup.MIN_FREE_BYTES
    free = {"n": need - 1}
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda p: type("U", (), {"free": free["n"]})())
    with caplog.at_level(logging.WARNING):
        assert backup.snapshot() is None
    assert "Snapshots are paused" in caplog.text and _names() == []
    free["n"] = need
    assert backup.snapshot() is not None and len(_names()) == 1


def test_prune_keeps_six_hours_of_hourlies_then_a_week_of_dailies(todo_db, freeze):
    now = freeze("2026-10-20T12:30:00")
    out = backup.backups_dir()
    out.mkdir()
    stamp = lambda **ago: (now - datetime.timedelta(**ago)).strftime(backup._NAME)  # noqa: E731
    hourly = [stamp(hours=h) for h in range(0, 7)]  # 0..6 hours old: all kept
    old_same_day = [stamp(days=3, hours=h) for h in (0, 1, 2)]  # one day, three snapshots
    last_daily, too_old = stamp(days=6, hours=23), stamp(days=7, hours=1)
    for name in [*hourly, *old_same_day, last_daily, too_old, "left-over.db.tmp", "notes.txt"]:
        (out / name).write_bytes(b"")
    backup.prune(now)
    # The newest snapshot of an older day is that day's daily.
    assert set(_names()) == {*hourly, old_same_day[0], last_daily, "notes.txt"}


def test_each_snapshot_run_drops_every_snapshot_from_the_page_cache(L, monkeypatch):
    # Railway bills cached file pages as memory; an older snapshot, read again by an off-site copy, is dropped too,
    # and so it is on a run that takes no snapshot (low space, or a failure).
    backup.backups_dir().mkdir()
    older = backup.backups_dir() / (common.utcnow() - datetime.timedelta(hours=1)).strftime(backup._NAME)
    older.write_bytes(b"")
    dropped = []

    def fadvise(fd, offset, length, advice):
        dropped.append((os.fstat(fd).st_ino, offset, length, advice))

    # Faked on every platform (macOS has no posix_fadvise), so the test runs everywhere.
    monkeypatch.setattr(os, "posix_fadvise", fadvise, raising=False)
    monkeypatch.setattr(os, "POSIX_FADV_DONTNEED", "dontneed", raising=False)
    newest = backup.snapshot()
    assert newest is not None
    assert sorted(dropped) == sorted((p.stat().st_ino, 0, 0, "dontneed") for p in (older, newest))

    dropped.clear()
    monkeypatch.setattr(backup, "_snapshot", lambda: None)  # e.g. paused for space
    assert backup.snapshot() is None
    assert len(dropped) == 2

    def boom(_out):
        raise OSError("volume I/O error")

    monkeypatch.setattr(backup, "_uncache", boom)  # never raises: the maintenance loop must live on
    assert backup.snapshot() is None


def test_prune_never_deletes_the_newest_snapshot_however_old(todo_db, freeze):
    now = freeze("2026-10-20T12:30:00")
    out = backup.backups_dir()
    out.mkdir()
    names = [(now - datetime.timedelta(days=d)).strftime(backup._NAME) for d in (20, 21, 22)]
    for name in names:
        (out / name).write_bytes(b"")
    backup.prune(now)
    assert _names() == [names[0]]


# ── One-list repair ───────────────────────────────────────────────────────────


def test_restore_list_puts_back_one_list_and_touches_nothing_else(new_list, capsys, freeze):
    freeze("2026-10-04T12:00:00")
    a, b = new_list(), new_list()
    ca, cb, a_id = a["client"], b["client"], a["list_id"]
    area = ca.post("/api/app/areas", json={"name": "Home"}).json()
    ca.post("/api/app/projects", json={"name": "Paint", "area_id": area["id"]})
    kept = ca.post("/api/app/todos", json={"title": "buy paint", "project": "Paint"}).json()
    snapshot = backup.snapshot()

    # After the snapshot: A is wrecked, B moves on, and A's agent link is replaced.
    freeze("2026-10-04T15:00:00")
    ca.put(f"/api/app/todos/{kept['id']}", json={"title": "WRECKED", "status": "dropped"})
    ca.post("/api/app/todos", json={"title": "added later"})
    ca.post("/api/app/projects", json={"name": "Later project"})
    cb.post("/api/app/todos", json={"title": "B after the snapshot"})
    new_agent = ca.post("/api/app/agent-link/rotate").json()["token"]

    restore_list.main([str(snapshot), "--list-id", str(a_id)])
    assert f"List {a_id} restored" in capsys.readouterr().out

    todos = ca.get("/api/app/todos").json()["todos"]
    assert [(t["title"], t["status"], t["project_name"]) for t in todos] == [("buy paint", "inbox", "Paint")]
    assert [p["name"] for p in ca.get("/api/app/projects").json()["projects"]] == ["Paint"]
    assert [x["name"] for x in ca.get("/api/app/areas").json()["areas"]] == ["Home"]
    # A keeps its CURRENT links and browsers (not the snapshot's); B is exactly as it was.
    assert lists.resolve_agent(new_agent) == a_id and lists.resolve_agent(a["agent_token"]) is None
    assert [t["title"] for t in cb.get("/api/app/todos").json()["todos"]] == ["B after the snapshot"]
    # The state just before the repair was snapshotted first.
    assert len(_names()) == 2
    # The repaired list still takes writes.
    assert ca.post("/api/app/todos", json={"title": "after"}).status_code == 200


def test_a_snapshot_is_never_overwritten(L, freeze, caplog):
    freeze("2026-10-04T12:00:00")
    first = backup.snapshot()
    service.create_todo(L, "later", source="ui")
    assert backup.snapshot() is None and "already exists" in caplog.text
    snap = sqlite3.connect(first)
    assert snap.execute("SELECT COUNT(*) FROM todos").fetchone() == (0,)
    snap.close()


def test_restore_list_refuses_a_list_the_snapshot_does_not_have(todo_db):
    old = lists.create_list("UTC")["list_id"]
    snapshot = backup.snapshot()
    newer = lists.create_list("UTC")["list_id"]
    service.create_todo(newer, "mine", source="ui")
    with pytest.raises(SystemExit, match="not in that snapshot"):
        restore_list.restore(snapshot, newer, db.db_path())
    assert len(service.list_todos(newer)) == 1 and old != newer


# ── Sign-in by email ──────────────────────────────────────────────────────────

# `mail` (conftest) switches mail on and records what would be sent.


def _links(text):
    return re.findall(r"https://todo\.example/signin/(\S+)", text)


def _with_email(new_list, email="me@example.com"):
    """A new list whose email is confirmed: the only kind sign-in mail goes to."""
    made = new_list()
    confirm_list(made["list_id"], email)
    return made


def _signed_in_to(res) -> int:
    """The list a redemption's Set-Cookie signs the browser in to."""
    return sessions.resolve(res.cookies[sessions.COOKIE])["list_id"]


def test_sign_in_by_email_is_absent_until_mail_is_configured(client, monkeypatch):
    assert client.post("/api/signin", json={"email": "me@example.com"}).status_code == 404
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    assert client.get("/api/config").json()["mail"] is False  # no sender yet
    monkeypatch.setenv("MAIL_FROM", "signin@todo.example")
    assert client.get("/api/config").json()["mail"] is False  # no base address yet
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    assert client.get("/api/config").json()["mail"] is True


def test_sign_in_mail_needs_a_configured_base_address_never_the_host_header(client, new_list, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "signin@todo.example")
    sent = []
    monkeypatch.setattr(signin, "_send", lambda to, subject, text: sent.append(text))
    _with_email(new_list)
    assert client.get("/api/config").json()["mail"] is False
    res = client.post("/api/signin", json={"email": "me@example.com"}, headers={"Host": "evil.example"})
    assert res.status_code == 404 and sent == []


def test_signin_answers_the_same_for_known_unknown_and_malformed(client, new_list, mail):
    _with_email(new_list)
    answers = [
        client.post("/api/signin", json={"email": e})
        for e in ("me@example.com", "nobody@example.com", "not an address")
    ]
    assert {(r.status_code, r.text) for r in answers} == {(200, '{"ok":true}')}
    assert [to for to, _ in mail] == ["me@example.com"]


def test_one_message_carries_a_link_per_list_and_each_signs_in_to_its_own(client, new_list, mail):
    a, b = _with_email(new_list), _with_email(new_list, "ME@example.com ")
    other = _with_email(new_list, "someone@example.com")
    client.post("/api/signin", json={"email": "Me@Example.com"})
    assert len(mail) == 1
    tokens = _links(mail[0][1])
    assert len(tokens) == 2 and "more than" not in mail[0][1]
    # Only hashes are stored, each with the address it was mailed to.
    stored = {tuple(r) for r in db.get_db().execute("SELECT token_hash, mailed_to FROM signin_tokens")}
    assert stored == {(lists.hash_token(t), "me@example.com") for t in tokens}

    first = client.post(f"/api/signin/{tokens[0]}")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    assert first.json() == {"verified": True}
    second = client.post(f"/api/signin/{tokens[1]}")
    assert {_signed_in_to(first), _signed_in_to(second)} == {a["list_id"], b["list_id"]}
    # Signing in changes nothing else: every browser and link of all three lists still works.
    for m in (a, b, other):
        assert m["client"].get("/api/app/filters").status_code == 200
        assert lists.resolve_agent(m["agent_token"]) == m["list_id"]


def test_a_mailed_link_works_once(client, new_list, mail):
    _with_email(new_list)
    client.post("/api/signin", json={"email": "me@example.com"})
    token = _links(mail[0][1])[0]
    assert client.post(f"/api/signin/{token}").status_code == 200
    replay = client.post(f"/api/signin/{token}")
    assert replay.status_code == 404 and "www-authenticate" not in replay.headers
    assert "set-cookie" not in replay.headers


def test_a_mailed_link_expires_after_an_hour(client, new_list, mail, freeze):
    made = _with_email(new_list)
    freeze("2026-10-04T12:00:00")
    client.post("/api/signin", json={"email": "me@example.com"})
    signin.address_limiter.clear()
    client.post("/api/signin", json={"email": "me@example.com"})
    first, second = (_links(text)[0] for _, text in mail)
    assert {r[0] for r in db.get_db().execute("SELECT expires_at FROM signin_tokens")} == {"2026-10-04T13:00:00.000Z"}
    freeze("2026-10-04T13:00:00")
    assert client.post(f"/api/signin/{second}").status_code == 404
    assert made["client"].get("/api/app/filters").status_code == 200  # nothing else changed
    freeze("2026-10-04T12:30:00")
    assert client.post(f"/api/signin/{second}").status_code == 404  # and it was spent
    freeze("2026-10-04T12:59:59")  # the last second of the hour
    assert client.post(f"/api/signin/{first}").status_code == 200


def test_a_mailed_link_dies_with_its_address(client, new_list, mail):
    made = _with_email(new_list)
    client.post("/api/signin", json={"email": "me@example.com"})
    token = _links(mail[0][1])[0]
    made["client"].put("/api/app/email", json={"email": "new@example.com"})
    assert client.post(f"/api/signin/{token}").status_code == 404
    # And redemption checks the address itself, whatever changed it.
    with db.transaction() as conn:
        token, _ = signin.issue_link_in(conn, made["list_id"], mailed_to="new@example.com")
        conn.execute("UPDATE lists SET email = 'other@example.com' WHERE id = ?", (made["list_id"],))
    assert signin.redeem(token) is None
    assert lists.get_list(made["list_id"])["email_verified_at"] is None  # and it confirmed nothing


def test_redeeming_one_link_spends_only_that_one(client, new_list, mail):
    made = _with_email(new_list)
    client.post("/api/signin", json={"email": "me@example.com"})
    signin.address_limiter.clear()
    client.post("/api/signin", json={"email": "me@example.com"})
    first, second = (_links(text)[0] for _, text in mail)
    assert _signed_in_to(client.post(f"/api/signin/{second}")) == made["list_id"]
    assert _signed_in_to(client.post(f"/api/signin/{first}")) == made["list_id"]
    assert db.get_db().execute("SELECT COUNT(*) FROM signin_tokens").fetchone()[0] == 0


def test_of_two_concurrent_redemptions_one_wins(new_list):
    made = new_list()
    token, _ = signin.issue_link(made["list_id"])
    barrier, results = threading.Barrier(6), []

    def go():
        barrier.wait()
        results.append(signin.redeem(token))

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    winners = [r for r in results if r]
    assert len(winners) == 1
    assert sessions.resolve(winners[0]["session_token"])["list_id"] == made["list_id"]


def test_only_the_ten_most_recently_used_lists_are_mailed_and_it_says_so(client, new_list, mail):
    made = [_with_email(new_list) for _ in range(10)]
    ids = [m["list_id"] for m in made]
    # Created directly: the HTTP create limit is ten per address.
    extra = lists.create_list("UTC")["list_id"]
    confirm_list(extra)
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET last_used_at = '2020-01-01T00:00:00.000Z' WHERE id = ?", (ids[0],))
    client.post("/api/signin", json={"email": "me@example.com"})
    text = mail[0][1]
    assert len(_links(text)) == 10 and "more than 10 lists" in text
    covered = {r[0] for r in db.get_db().execute("SELECT list_id FROM signin_tokens")}
    assert covered == {*ids[1:], extra}  # the stalest one is the one left out


def test_one_message_per_address_per_fifteen_minutes(client, new_list, mail, monkeypatch):
    _with_email(new_list)
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    for _ in range(3):
        assert client.post("/api/signin", json={"email": "me@example.com"}).status_code == 200
    assert len(mail) == 1
    now[0] += 900
    client.post("/api/signin", json={"email": "me@example.com"})
    assert len(mail) == 2


def test_sign_in_requests_are_rate_limited_per_ip(client, mail):
    codes = [client.post("/api/signin", json={"email": f"a{n}@example.com"}).status_code for n in range(6)]
    assert codes == [200] * 5 + [429]


def test_a_failed_send_still_answers_ok_and_may_be_retried(client, new_list, mail, monkeypatch, caplog):
    _with_email(new_list)

    def fail(*a):
        raise RuntimeError("smtp down https://todo.example/signin/SECRET me@example.com")

    monkeypatch.setattr(signin, "_send", fail)
    with caplog.at_level(logging.ERROR):
        assert client.post("/api/signin", json={"email": "me@example.com"}).json() == {"ok": True}
    assert "Sign-in mail failed: RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text and "me@example.com" not in caplog.text
    monkeypatch.setattr(signin, "_send", lambda to, subject, text: mail.append((to, text)))
    client.post("/api/signin", json={"email": "me@example.com"})
    assert len(mail) == 1  # the address was not left rate-limited by the failure


def test_the_mail_is_plain_text_through_resend(client, new_list, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Todo GTD <signin@todo.example>")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    calls = []

    class OK:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(signin.httpx, "post", lambda url, **kw: calls.append((url, kw)) or OK())
    made = _with_email(new_list)
    made["client"].put("/api/app/name", json={"name": "Home"})
    client.post("/api/signin", json={"email": "me@example.com"})
    ((url, kw),) = calls
    assert url == "https://api.resend.com/emails"
    assert kw["headers"] == {"Authorization": "Bearer re_test"}
    body = kw["json"]
    # Text only: no HTML body for click tracking to rewrite the link in.
    assert set(body) == {"from", "to", "subject", "text"}
    assert body["from"] == "Todo GTD <signin@todo.example>" and body["to"] == ["me@example.com"]
    assert body["subject"] == "Your Todo GTD sign-in link"
    assert re.search(r"List 1 \(created .*\):\nhttps://todo\.example/signin/[\w-]{43}\n", body["text"])
    # The name is user text on an unverified address: it must never ride in the mail.
    assert "Home" not in body["text"]
    assert "works once, for one hour" in body["text"] and "ignore this message" in body["text"]


# ── Confirming an email ───────────────────────────────────────────────────────


def _pending(list_id):
    return [
        tuple(r)
        for r in db.get_db().execute("SELECT token_hash, mailed_to FROM signin_tokens WHERE list_id = ?", (list_id,))
    ]


def test_only_lists_with_a_confirmed_email_get_sign_in_mail(client, new_list, mail):
    confirmed = _with_email(new_list)
    unconfirmed = new_list()
    lists.set_email(unconfirmed["list_id"], "me@example.com")
    client.post("/api/signin", json={"email": "me@example.com"})
    (token,) = _links(mail[0][1])
    assert _signed_in_to(client.post(f"/api/signin/{token}")) == confirmed["list_id"]
    assert _pending(unconfirmed["list_id"]) == []
    # An address no list has confirmed gets nothing at all.
    lists.set_email(confirmed["list_id"], "")
    signin.address_limiter.clear()
    client.post("/api/signin", json={"email": "me@example.com"})
    assert len(mail) == 1


def test_the_confirmation_link_is_minted_in_the_transaction_that_saves_the_address(new_list, mail, monkeypatch):
    made = new_list()
    seen, real = [], signin.issue_link_in

    def spy(conn, list_id, **kw):
        # The address is written, and not yet committed: another connection cannot see it.
        mine = conn.execute("SELECT email FROM lists WHERE id = ?", (list_id,)).fetchone()[0]
        other = sqlite3.connect(db.db_path())
        theirs = other.execute("SELECT email FROM lists WHERE id = ?", (list_id,)).fetchone()[0]
        other.close()
        seen.append((mine, theirs))
        return real(conn, list_id, **kw)

    monkeypatch.setattr(signin, "issue_link_in", spy)
    made["client"].put("/api/app/email", json={"email": "me@example.com"})
    assert seen == [("me@example.com", None)]
    (token,) = _links(mail[0][1])
    assert _pending(made["list_id"]) == [(lists.hash_token(token), "me@example.com")]


def test_opening_the_confirmation_link_confirms_and_signs_that_browser_in(client, new_list, mail, freeze):
    freeze("2026-10-11T12:00:00")
    made = new_list()
    made["client"].put("/api/app/email", json={"email": "me@example.com"})
    (token,) = _links(mail[0][1])
    res = client.post(f"/api/signin/{token}")
    assert res.status_code == 200 and res.json() == {"verified": True}
    assert _signed_in_to(res) == made["list_id"]
    assert lists.get_list(made["list_id"])["email_verified_at"] == "2026-10-11T12:00:00.000Z"
    assert made["client"].get("/api/app/todos").status_code == 200  # the first browser too
    # Confirmed, the address now gets sign-in mail.
    signin.address_limiter.clear()
    client.post("/api/signin", json={"email": "me@example.com"})
    assert len(mail) == 2 and len(_links(mail[1][1])) == 1


def test_a_link_shown_in_the_app_confirms_nothing(client, new_list):
    made = new_list()
    lists.set_email(made["list_id"], "me@example.com")
    token, _ = signin.issue_link(made["list_id"])
    assert client.post(f"/api/signin/{token}").json() == {"verified": False}
    assert lists.get_list(made["list_id"])["email_verified_at"] is None


def test_an_address_change_before_the_link_is_opened_makes_it_unknown(client, new_list, mail):
    made = new_list()
    made["client"].put("/api/app/email", json={"email": "me@example.com"})
    made["client"].put("/api/app/email", json={"email": "new@example.com"})
    first, second = (_links(text)[0] for _, text in mail)
    res = client.post(f"/api/signin/{first}")
    assert res.status_code == 404 and "set-cookie" not in res.headers
    assert lists.get_list(made["list_id"])["email_verified_at"] is None
    assert client.post(f"/api/signin/{second}").json() == {"verified": True}


def test_send_again_right_away_keeps_the_first_link_and_says_nothing_was_sent(client, new_list, mail):
    made = new_list()
    c = made["client"]
    assert c.put("/api/app/email", json={"email": "me@example.com"}).json()["sent"] is True
    again = c.put("/api/app/email", json={"email": "me@example.com"})
    assert again.json() == {
        "email": "me@example.com",
        "verified": False,
        "sent": False,
        "caps": {"todos": 200, "projects": 20, "areas": 10},
    }
    assert len(mail) == 1 and len(_pending(made["list_id"])) == 1
    # Once the wait is over, Send again mails a second link, and the first still works.
    signin.confirm_limiter.clear()
    assert c.put("/api/app/email", json={"email": "me@example.com"}).json()["sent"] is True
    first, second = (_links(text)[0] for _, text in mail)
    assert client.post(f"/api/signin/{first}").json() == {"verified": True}
    assert client.post(f"/api/signin/{second}").json() == {"verified": True}


def test_an_address_change_while_throttled_still_cancels_the_old_links(client, new_list, mail):
    made = new_list()
    c = made["client"]
    c.put("/api/app/email", json={"email": "me@example.com"})
    (old,) = _links(mail[0][1])
    signin.confirm_limiter.allow("new@example.com")  # that address just had its one mail
    res = c.put("/api/app/email", json={"email": "new@example.com"})
    assert res.json() == {
        "email": "new@example.com",
        "verified": False,
        "sent": False,
        "caps": {"todos": 200, "projects": 20, "areas": 10},
    }
    assert len(mail) == 1 and _pending(made["list_id"]) == []
    assert client.post(f"/api/signin/{old}").status_code == 404


def test_one_list_cannot_mail_address_after_address(new_list, mail):
    made = new_list()
    sent = [made["client"].put("/api/app/email", json={"email": f"a{n}@example.com"}).json()["sent"] for n in range(6)]
    # The asking address's mail budget (the sign-in form's too) runs out; the address is still saved.
    assert sent == [True] * 5 + [False] and len(mail) == 5
    assert lists.get_list(made["list_id"])["email"] == "a5@example.com"


def test_a_failed_confirmation_send_is_logged_without_details_and_may_be_retried(new_list, mail, monkeypatch, caplog):
    made = new_list()

    def fail(*a):
        raise RuntimeError("smtp down https://todo.example/signin/SECRET me@example.com")

    monkeypatch.setattr(signin, "_send", fail)
    with caplog.at_level(logging.ERROR):
        assert made["client"].put("/api/app/email", json={"email": "me@example.com"}).status_code == 200
    assert "Confirmation mail failed: RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text and "me@example.com" not in caplog.text
    monkeypatch.setattr(signin, "_send", lambda to, subject, text: mail.append((to, text)))
    assert made["client"].put("/api/app/email", json={"email": "me@example.com"}).json()["sent"] is True
    assert len(mail) == 1  # the failure did not leave the address rate-limited


def test_the_confirmation_mail_is_plain_text_with_its_own_subject(new_list, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Todo GTD <signin@todo.example>")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    calls = []

    class OK:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(signin.httpx, "post", lambda url, **kw: calls.append((url, kw)) or OK())
    made = new_list()
    made["client"].put("/api/app/name", json={"name": "Home"})
    made["client"].put("/api/app/email", json={"email": "me@example.com"})
    ((url, kw),) = calls
    body = kw["json"]
    assert set(body) == {"from", "to", "subject", "text"} and body["to"] == ["me@example.com"]
    assert body["subject"] == "Confirm your email for Todo GTD"
    assert re.search(r"\nhttps://todo\.example/signin/[\w-]{43}\n", body["text"])
    assert "works once, for one hour, and signs in the device that opens it" in body["text"]
    assert body["text"].endswith("If you did not add this address to a list, ignore this message.")
    assert "Home" not in body["text"]  # only our own words


# ── Idle lifecycle (lifecycle.py) ─────────────────────────────────────────────

# Every list here is made at T0 and never used after it: idle = created_at.
T0 = datetime.datetime(2026, 1, 1, 12, 0, 0)


def _idle(freeze, **delta):
    """Move the frozen clock to ``delta`` after T0."""
    freeze((T0 + datetime.timedelta(**delta)).isoformat())


def _made_at_t0(new_list, freeze):
    freeze(T0.isoformat())
    return new_list()


def _use(client, made, surface: str) -> int:
    """One call on the list's agent or capture link; its status."""
    if surface == "agent":
        return client.post(f"/mcp/{made['agent_token']}", json=INIT, headers=MCP_HEADERS).status_code
    return client.post(f"/api/c/{made['capture_token']}", json={"text": "x"}).status_code


def _untouched(made) -> tuple:
    """(the app's state, the agent link resolves, the capture link resolves), asked
    without using the list, so no answer can bring it back before the next."""
    return (
        made["client"].get("/api/app/session").json()["state"],
        lists.resolve_agent(made["agent_token"]) == made["list_id"],
        lists.resolve_capture(made["capture_token"]) == made["list_id"],
    )


def _refused(res, state: str) -> bool:
    return (
        res.status_code == 403
        and res.json() == {"detail": {"state": state}}
        and res.headers["cache-control"] == "no-store"
    )


def test_a_list_is_active_for_59_days_and_23_hours(client, new_list, mail, freeze):
    made = _made_at_t0(new_list, freeze)
    _idle(freeze, days=59, hours=23)
    assert _untouched(made) == ("active", True, True)
    assert made["client"].get("/api/app/todos").status_code == 200


def test_at_60_days_the_app_is_put_away_until_restored(client, new_list, mail, freeze):
    made = _made_at_t0(new_list, freeze)
    c, lid = made["client"], made["list_id"]
    _idle(freeze, days=60)
    assert _refused(c.get("/api/app/todos"), "archived")
    assert _refused(c.post("/api/app/todos", json={"title": "x"}), "archived")
    assert _refused(c.get("/api/app/agent-link"), "archived")
    # A refusal is not a use: opening the app does not bring the list back.
    assert lists.get_list(lid)["last_used_at"] is None
    assert _untouched(made) == ("archived", True, True)
    res = c.post("/api/app/restore")
    assert res.status_code == 200 and res.json() == {"state": "active"}
    assert lists.get_list(lid)["last_used_at"] == common.now_iso()
    assert c.get("/api/app/session").json()["state"] == "active"
    assert c.get("/api/app/todos").status_code == 200


@pytest.mark.parametrize("surface", ["agent", "capture"])
def test_using_the_agent_or_capture_link_brings_an_archived_list_back(client, new_list, mail, freeze, surface):
    made = _made_at_t0(new_list, freeze)
    _idle(freeze, days=100)
    assert made["client"].get("/api/app/session").json()["state"] == "archived"
    assert _use(client, made, surface) == 200
    assert made["client"].get("/api/app/session").json()["state"] == "active"
    assert made["client"].get("/api/app/todos").status_code == 200


def test_at_180_days_every_surface_agrees_the_list_is_removed(client, new_list, mail, freeze):
    made = _made_at_t0(new_list, freeze)
    c = made["client"]
    _idle(freeze, days=180)
    assert _refused(c.get("/api/app/todos"), "removed")
    assert _use(client, made, "agent") == 404
    assert _use(client, made, "capture") == 404
    # The app still learns which list it is, and why; a button cannot bring it back.
    session = c.get("/api/app/session").json()
    assert (session["list_id"], session["state"]) == (made["list_id"], "removed")
    assert _refused(c.post("/api/app/restore"), "removed")
    assert lists.get_list(made["list_id"])["last_used_at"] is None


@pytest.mark.parametrize("surface", ["agent", "capture"])
def test_one_second_before_180_days_the_app_is_archived_and_the_links_still_work(
    client, new_list, mail, freeze, surface
):
    made = _made_at_t0(new_list, freeze)
    _idle(freeze, days=180, seconds=-1)
    assert _refused(made["client"].get("/api/app/todos"), "archived")
    assert _use(client, made, surface) == 200


def test_confirming_an_email_brings_a_removed_list_back_for_good(client, new_list, mail, freeze):
    made = _made_at_t0(new_list, freeze)
    c = made["client"]
    _idle(freeze, days=200)
    res = c.put("/api/app/email", json={"email": "me@example.com"})
    assert res.status_code == 200 and res.json()["sent"] is True
    (token,) = _links(mail[0][1])
    redeemed = client.post(f"/api/signin/{token}")
    assert redeemed.status_code == 200 and redeemed.json() == {"verified": True}
    assert _untouched(made) == ("active", True, True)
    assert c.get("/api/app/todos").status_code == 200
    # Confirmed, it never ages again.
    _idle(freeze, days=500)
    assert _untouched(made) == ("active", True, True)
    assert _use(client, made, "agent") == 200 and _use(client, made, "capture") == 200


def test_a_confirmed_list_never_ages(client, new_list, mail, freeze, confirm):
    made = _made_at_t0(new_list, freeze)
    confirm(made["list_id"])
    _idle(freeze, days=364)
    assert _untouched(made) == ("active", True, True)
    assert made["client"].get("/api/app/todos").status_code == 200


def test_a_one_list_server_never_ages_its_list(single, new_list, mail, freeze):
    made = _made_at_t0(new_list, freeze)
    _idle(freeze, days=364)
    assert _untouched(made) == ("active", True, True)
    assert made["client"].get("/api/app/todos").status_code == 200


def test_without_mail_lists_never_age(client, new_list, freeze, capsys):
    """No mail, no way to confirm an email, so no way back from removed: the
    lifecycle is off (lifecycle.enabled) and every surface stays served."""
    made = _made_at_t0(new_list, freeze)
    _idle(freeze, days=364)
    assert _untouched(made) == ("active", True, True)
    admin.main(["lists", "--json"])
    assert [r["state"] for r in json.loads(capsys.readouterr().out)] == ["active"]
    assert made["client"].get("/api/app/todos").status_code == 200
    assert _use(client, made, "agent") == 200 and _use(client, made, "capture") == 200


def test_a_removed_lists_page_cannot_write_into_the_list_the_browser_moved_to(client, new_list, mail, freeze):
    old = _made_at_t0(new_list, freeze)
    _idle(freeze, days=200)
    session = old["client"].get("/api/app/session").json()
    assert (session["list_id"], session["state"]) == (old["list_id"], "removed")
    # Another tab signs the browser in to another list; this tab's email form
    # still names the removed one.
    tab = new_list()["client"]
    res = tab.put("/api/app/email", json={"email": "me@example.com"}, headers={"X-List": str(old["list_id"])})
    assert res.status_code == 409 and res.json() == {"detail": {"list_changed": True}}
    assert [r["email"] for r in db.get_db().execute("SELECT email FROM lists")] == [None, None]
    assert mail == []


def test_open_signup_without_mail_warns_at_startup(todo_db, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from backend.main import app

    def started() -> bool:
        caplog.clear()
        with TestClient(app):
            pass
        return "Open signup without mail" in caplog.text

    assert started()
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "signin@todo.example")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    assert not started()
    monkeypatch.delenv("RESEND_API_KEY")
    monkeypatch.delenv("OPEN_SIGNUP")
    assert not started()  # a one-list server without mail is ordinary


# ── Logs ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/signin/TOKEN",
        "/api/signin/TOKEN",
        "https://todo.example/signin/TOKEN#x",
        "/c/TOKEN",
        "/api/c/TOKEN",
        "/mcp/TOKEN",
        "/link/TOKEN",
        # Gone, but old bookmarks still send them.
        "/w/TOKEN",
        "/w/TOKEN/inbox",
        "/api/w/TOKEN/todos?search=x",
        "/recover/TOKEN",
        "http://testserver/w/TOKEN#x",
    ],
)
def test_token_segments_are_scrubbed(path):
    clean = logscrub.scrub(path)
    assert "TOKEN" not in clean and "***" in clean
    assert clean.replace("***", "TOKEN") == path  # nothing else changed


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/lists",
        "/api/config",
        "/healthz",
        "/assets/w.js",
        "/mcp",
        "/app",
        "/app/inbox",
        "/api/app/todos?status=inbox",
        "/api/signin",
        "/app/manifest.webmanifest",
        "https://a-very-long-host-name-that-is-not-a-token.example/mcp",
    ],
)
def test_other_paths_are_left_alone(path):
    assert logscrub.scrub(path) == path


def test_the_agent_links_other_shape_is_scrubbed_too():
    token = lists.mint_token()
    for path in (
        f"/{token}/mcp",
        f"/{token}/mcp?x=1",
        f"http://testserver/{token}/mcp",
        f"/.well-known/oauth-protected-resource/{token}/mcp",
        f"/.well-known/oauth-protected-resource/mcp/{token}",
    ):
        clean = logscrub.scrub(path)
        assert token not in clean, path
        assert clean.replace("***", token) == path


def test_the_log_filter_scrubs_access_lines_and_plain_messages():
    f = logscrub.ScrubTokens()
    access = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "POST", "/api/signin/TOKEN", "1.1", 200),
        None,
    )
    assert f.filter(access)
    assert access.getMessage() == '1.2.3.4:5 - "POST /api/signin/*** HTTP/1.1" 200'
    assert access.args[4] == 200  # uvicorn's formatter needs the status as a number
    plain = logging.LogRecord(
        "x", logging.ERROR, "", 0, "failed on /signin/TOKEN %s", (ValueError("at /c/TOKEN2/x"),), None
    )
    f.filter(plain)
    assert plain.getMessage() == "failed on /signin/*** at /c/***/x"


def test_the_log_filter_keeps_the_placeholder_when_the_template_spells_the_path():
    """Scrubbing the template alone eats the %s; logging then fails to format the line and
    prints the raw arguments, token included, in its own error report."""
    record = logging.LogRecord("x", logging.WARNING, "", 0, "refused /c/%s", ("TOKEN",), None)
    logscrub.ScrubTokens().filter(record)
    assert record.getMessage() == "refused /c/***"


def test_the_log_filter_scrubs_arguments_passed_as_a_dict():
    record = logging.LogRecord("x", logging.INFO, "", 0, "%(r)s", ({"r": "GET /mcp/TOKEN"},), None)
    logscrub.ScrubTokens().filter(record)
    assert record.getMessage() == "GET /mcp/***"


def test_the_log_filter_scrubs_a_message_that_is_not_a_string():
    """`log.error(exc)` hands the filter an object, and logging prints str() of it."""
    record = logging.LogRecord("x", logging.ERROR, "", 0, ValueError("no such list at /c/TOKEN"), None, None)
    logscrub.ScrubTokens().filter(record)
    assert record.getMessage() == "no such list at /c/***"
    # An object with nothing to hide is passed through untouched, type and all.
    harmless = ValueError("nothing to hide")
    record = logging.LogRecord("x", logging.ERROR, "", 0, harmless, None, None)
    logscrub.ScrubTokens().filter(record)
    assert record.msg is harmless


def test_the_log_filter_scrubs_a_traceback():
    try:
        raise RuntimeError("boom at /signin/TOKEN")
    except RuntimeError as e:
        record = logging.LogRecord("x", logging.ERROR, "", 0, "failed", None, (type(e), e, e.__traceback__))
    logscrub.ScrubTokens().filter(record)
    text = logging.Formatter().format(record)
    assert "TOKEN" not in text and "boom at /signin/***" in text


def test_the_trace_level_scope_dump_is_scrubbed(client):
    """`uvicorn --log-level trace` prints the whole ASGI scope on `uvicorn.asgi`, the path as
    text and as bytes. `client` imported the app, which installs the filter on that logger."""
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    asgi = logging.getLogger("uvicorn.asgi")
    level = asgi.level
    asgi.addHandler(handler)
    asgi.setLevel(5)
    try:
        scope = {"type": "http", "path": "/mcp/TOKEN", "raw_path": b"/mcp/TOKEN"}
        asgi.log(5, "%s - ASGI [%d] Started scope=%s", "1.2.3.4:5", 1, scope)
    finally:
        asgi.removeHandler(handler)
        asgi.setLevel(level)
    assert "TOKEN" not in out.getvalue() and "/mcp/***" in out.getvalue()


# ── Small fixes ───────────────────────────────────────────────────────────────


def test_a_bare_c_is_the_invalid_link_page_not_a_broken_app(client):
    for path in ("/c", "/c/"):
        res = client.get(path)
        assert res.status_code == 404, path
        assert "This link isn" in res.text and '<div id="root">' not in res.text
        assert res.headers["cache-control"] == "no-store"


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_startup_refuses_a_data_dir_it_cannot_write(tmp_path, monkeypatch):
    blocker = tmp_path / "data"
    blocker.write_text("a file where the directory should be")
    monkeypatch.setenv("DATA_DIR", str(blocker))
    with pytest.raises(RuntimeError, match="DATA_DIR .* is not writable.*volume"):
        db.init_db()


def test_every_generated_link_uses_public_base_url(new_list, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example/")
    made = new_list()
    c = made["client"]
    assert c.get("/api/app/capture-link").json()["url"].startswith("https://todo.example/c/")
    assert made["agent_url"] == f"https://todo.example/link/{made['agent_token']}"
    assert c.get("/api/app/agent-link").json()["url"] == made["agent_url"]
    assert c.post("/api/app/agent-link/rotate").json()["url"].startswith("https://todo.example/link/")
    assert c.post("/api/app/signin-link").json()["url"].startswith("https://todo.example/signin/")


def test_railways_own_domain_is_the_fallback_base(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "todo-production.up.railway.app")
    body = client.post("/api/lists").json()
    assert body["agent_url"] == f"https://todo-production.up.railway.app/link/{body['agent_token']}"


def test_sent_never_reveals_whether_a_confirmed_list_uses_the_address(client, new_list, mail, confirm):
    """The sign-in form spends its per-address budget only when a confirmed list exists.
    If the confirmation PUT shared that budget, `sent` would tell any list holder
    whether an address is registered. The two limiters are separate."""
    confirm(new_list()["list_id"], "victim@example.com")
    for address in ("victim@example.com", "nobody@example.com"):
        probe = new_list()
        client.post("/api/signin", json={"email": address})
        res = probe["client"].put("/api/app/email", json={"email": address})
        assert res.status_code == 200 and res.json()["sent"] is True, address


def test_a_long_lived_list_in_steady_use_keeps_its_links(client, new_list, mail, freeze):
    """The resolver keys on the last use, not the creation date: a list made
    long ago but used recently stays reachable on every surface."""
    made = _made_at_t0(new_list, freeze)
    _idle(freeze, days=170)
    assert _use(client, made, "capture") == 200  # touches it
    _idle(freeze, days=200)  # 30 days since that use, 200 since creation
    assert _untouched(made) == ("active", True, True)
    assert _use(client, made, "agent") == 200


@pytest.mark.parametrize("days", [60, 200])
def test_signing_out_works_on_a_put_away_list(client, new_list, mail, freeze, days):
    """The put-away page's "Sign out and start a new list" must not need an active list."""
    made = _made_at_t0(new_list, freeze)
    _idle(freeze, days=days)
    assert made["client"].post("/api/app/signout").json() == {"ok": True}
    assert made["client"].get("/api/app/session").status_code == 401
