"""scripts/admin.py: the operator's command line, against a real SQLite file and the real app."""

import json
import sqlite3

import pytest

from backend import backup, common, db, lists, service, signin
from backend.tests.test_mcp import INIT, MCP_HEADERS
from scripts import admin, restore_list


@pytest.fixture()
def run(capsys):
    """Run one admin command; returns (exit code, everything it printed)."""

    def go(*argv):
        capsys.readouterr()
        code = admin.main([str(a) for a in argv])
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    return go


def _log():
    return [tuple(r) for r in db.get_db().execute("SELECT command, list_id FROM admin_log ORDER BY id")]


def _surfaces(client, made) -> dict[str, int]:
    """The status each of a list's surfaces answers with right now."""
    browser = made["client"]
    return {
        "web page": browser.get("/app", follow_redirects=False).status_code,
        "session": browser.get("/api/app/session").status_code,
        "api": browser.get("/api/app/todos").status_code,
        "capture": client.post(f"/api/c/{made['capture']}", json={"text": "x"}).status_code,
        "mcp": client.post(f"/mcp/{made['agent_token']}", json=INIT, headers=MCP_HEADERS).status_code,
    }


@pytest.fixture()
def made(new_list):
    """A list with some content, its signed-in browser and both of its tokens."""
    body = new_list()
    body["id"], body["capture"] = body["list_id"], body["capture_token"]
    c = body["client"]
    c.post("/api/app/todos", json={"title": "Buy secret milk", "status": "next_action"})
    c.post("/api/app/todos", json={"title": "Old thing", "status": "done"})
    c.post("/api/app/projects", json={"name": "Secret project"})
    return body


# ── Read commands ─────────────────────────────────────────────────────────────


def test_stats_counts_everything(made, new_list, run, confirm):
    lists.set_email(new_list()["list_id"], "you@example.com")
    confirm(made["id"])
    backup.snapshot()
    code, out = run("stats", "--json")
    data = json.loads(out)
    assert code == 0
    assert data["lists"] == 2 and data["lists_with_email"] == 2 and data["lists_disabled"] == 0
    assert data["lists_verified"] == 1
    assert data["todos"] == 2 and data["projects"] == 1 and data["areas"] == 0
    assert data["todos_by_status"]["next_action"] == 1 and data["todos_by_status"]["inbox"] == 0
    days = data["lists_created_by_day"]
    assert len(days) == 14 and days[common.utcnow().date().isoformat()] == 2
    assert data["database_bytes"] > 0
    assert data["snapshots"]["count"] == 1 and data["snapshots"]["newest"].startswith("todo-")
    _, text = run("stats")
    assert "Lists: 2 (2 with an email, 1 confirmed, 0 disabled)" in text
    assert "Snapshots: 1," in text


def test_lists_rows_filters_and_hidden_email(made, new_list, client, run, confirm):
    other_id = new_list()["list_id"]
    lists.set_name(other_id, "Work stuff")
    confirm(made["id"])

    rows = json.loads(run("lists", "--json")[1])
    assert [r["id"] for r in rows] == [other_id, made["id"]]  # newest first
    mine = rows[1]
    assert mine == {
        "id": made["id"],
        "account_no": mine["account_no"],
        "name": "",
        "created_at": mine["created_at"],
        "last_used_at": mine["last_used_at"],
        "todos_open": 1,
        "todos_total": 2,
        "projects": 1,
        "has_email": True,
        "email_verified": True,
        "disabled_at": None,
        "state": "active",
    }
    assert rows[0]["has_email"] is False and rows[0]["email_verified"] is False
    text = run("lists")[1]
    assert "OPEN/TOTAL" in text and "1/2" in text and "Work stuff" in text
    assert "CONFIRMED" in text
    assert "me@example.com" not in text
    assert "me@example.com" in run("lists", "--show-email")[1]

    def ids(*flags):
        return [r["id"] for r in json.loads(run("lists", "--json", *flags)[1])]

    assert ids("--email", "ME@example.com") == [made["id"]]
    assert ids("--name", "work") == [other_id]
    assert ids("--unused") == [other_id]
    assert ids("--limit", 1) == [other_id]
    today = common.utcnow().date().isoformat()
    assert ids("--created-before", today) == []
    assert ids("--created-after", today) == [other_id, made["id"]]


def test_lists_shows_an_unconfirmed_address_as_unconfirmed(made, new_list, run, confirm):
    pending = new_list()["list_id"]
    lists.set_email(pending, "me@example.com")  # an address, but nobody has opened its link
    bare = new_list()["list_id"]
    confirm(made["id"], "mine@example.com")

    rows = {r["id"]: r for r in json.loads(run("lists", "--json")[1])}
    assert (rows[pending]["has_email"], rows[pending]["email_verified"]) == (True, False)
    assert (rows[made["id"]]["has_email"], rows[made["id"]]["email_verified"]) == (True, True)
    assert (rows[bare]["has_email"], rows[bare]["email_verified"]) == (False, False)

    # The table's CONFIRMED column, read by position: yes, no, or '-' where there is no address.
    head, *body = run("lists")[1].splitlines()
    at = head.index("CONFIRMED")
    cell = {int(line.split()[0]): line[at : at + len("CONFIRMED")].strip() for line in body}
    assert cell == {made["id"]: "yes", pending: "no", bare: "-"}


def test_lists_shows_whether_each_list_is_put_away(new_list, run, mail, freeze, confirm):
    freeze("2026-01-01T12:00:00")
    archived, removed, kept = (new_list()["list_id"] for _ in range(3))
    confirm(kept)
    with db.transaction() as conn:  # idle since three months before the rest
        conn.execute("UPDATE lists SET created_at = '2025-10-01T12:00:00.000Z' WHERE id = ?", (removed,))
    freeze("2026-05-01T12:00:00")  # 120 days after the others were made
    rows = json.loads(run("lists", "--json")[1])
    assert {r["id"]: r["state"] for r in rows} == {archived: "archived", removed: "removed", kept: "active"}
    assert run("disable", removed)[0] == 0
    assert json.loads(run("show", removed, "--json")[1])["state"] == "disabled"
    assert "archived" in run("lists")[1]


def test_find_identifies_each_kind_of_link_and_nothing_for_an_unknown_one(made, run):
    for kind, link in (
        ("agent", made["agent_token"]),
        ("agent", f"https://todogtd.com/link/{made['agent_token']}"),
        ("agent", f"https://todogtd.com/mcp/{made['agent_token']}"),
        ("agent", f"https://todogtd.com/{made['agent_token']}/mcp"),
        ("capture", f"https://todogtd.com/c/{made['capture']}"),
        ("capture", f"https://todogtd.com/api/c/{made['capture']}"),
    ):
        # --link=…: a bare token may start with "-", which "--link <token>" would
        # read as another option.
        code, out = run("find", f"--link={link}", "--json")
        assert code == 0
        assert json.loads(out) == {"list_id": made["id"], "kind": kind, "disabled": False}
    code, out = run("find", f"--link={made['capture']}")
    assert out.strip() == f"List {made['id']}: that is its capture link"
    code, out = run("find", "--link", "https://todogtd.com/w/not-a-real-token")
    assert code == 1 and out.startswith("No list has that link.")
    # A sign-in link or a session cannot be identified.
    token, _ = signin.issue_link(made["id"])
    for secret in (f"https://todogtd.com/signin/{token}", made["session"]):
        code, out = run("find", f"--link={secret}")
        assert code == 1 and "a sign-in link cannot" in out


def test_show_is_metadata_only_unless_content_is_asked_for(made, run):
    code, out = run("show", made["id"])
    assert code == 0
    assert "Time zone: America/Chicago" in out and "next_action 1" in out
    assert "Secret" not in out and "milk" not in out
    assert _log() == []

    code, out = run("show", made["id"], "--content")
    assert "Buy secret milk" in out and "Secret project" in out
    assert f"Reading the private content of list {made['id']}" in out
    assert _log() == [("show --content", made["id"])]
    data = json.loads(
        run("show", made["id"], "--content", "--json")[1].split("Reading the")[0]
    )  # the notice is on stderr
    assert data["projects"] == 1 and [p["name"] for p in data["project_items"]] == ["Secret project"]
    assert [t["title"] for t in data["todo_items"]] == ["Buy secret milk", "Old thing"]

    data = json.loads(run("show", made["id"], "--json")[1])
    assert data["tz"] == "America/Chicago" and data["todos_by_status"]["done"] == 1
    assert "todo_items" not in data and "email" not in data

    with pytest.raises(SystemExit, match="No list has id 999"):
        run("show", 999)


def test_snapshots_lists_the_files(made, run):
    assert "No snapshots" in run("snapshots")[1]
    path = backup.snapshot()
    rows = json.loads(run("snapshots", "--json")[1])
    assert [r["name"] for r in rows] == [path.name]
    assert rows[0]["bytes"] == path.stat().st_size and rows[0]["taken_at"].endswith("Z")
    assert path.name in run("snapshots")[1]


# ── Write commands ────────────────────────────────────────────────────────────


def test_signin_link_prints_one_link_that_signs_a_browser_in_and_changes_nothing_else(made, client, run):
    code, out = run("signin-link", made["id"])
    assert code == 0
    token = out.strip().splitlines()[1].rsplit("/signin/", 1)[1]
    assert client.post(f"/api/signin/{token}").status_code == 200
    assert client.get("/api/app/session").json()["list_id"] == made["id"]
    assert made["client"].get("/api/app/todos").status_code == 200
    assert lists.resolve_agent(made["agent_token"]) == made["id"]
    assert lists.resolve_capture(made["capture"]) == made["id"]
    assert _log() == [("signin-link", made["id"])]


def test_signin_link_uses_the_configured_address(made, run, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todogtd.com/")
    out = run("signin-link", made["id"])[1]
    assert out.strip().splitlines()[-1].startswith("https://todogtd.com/signin/")


def test_sign_out_all_signs_every_browser_out_and_cancels_links(made, client, run):
    client.post(f"/api/signin/{signin.issue_link(made['id'])[0]}")  # a second browser
    unspent, _ = signin.issue_link(made["id"])
    code, out = run("sign-out-all", made["id"])
    assert code == 0 and "every browser is signed out" in out
    assert made["client"].get("/api/app/todos").status_code == 401
    assert client.get("/api/app/session").status_code == 401
    assert client.post(f"/api/signin/{unspent}").status_code == 404
    assert lists.resolve_agent(made["agent_token"]) == made["id"]
    assert lists.resolve_capture(made["capture"]) == made["id"]
    assert _log() == [("sign-out-all", made["id"])]


def test_set_email_and_clear_email_cancel_sign_in_links(made, run, confirm):
    def pending():
        return db.get_db().execute("SELECT COUNT(*) FROM signin_tokens").fetchone()[0]

    confirm(made["id"])
    signin.issue_link(made["id"])
    code, out = run("set-email", made["id"], "New@Example.com")
    assert code == 0 and "email set to new@example.com, unconfirmed" in out
    assert "Sign-in links already mailed" in out
    row = lists.get_list(made["id"])
    assert (row["email"], row["email_verified_at"]) == ("new@example.com", None) and pending() == 0

    signin.issue_link(made["id"])
    assert "nothing changed" in run("set-email", made["id"], "new@example.com")[1]
    assert pending() == 1  # the app's rule: only a CHANGE cancels them
    assert made["client"].get("/api/app/todos").status_code == 200  # and never a session

    assert "email removed" in run("clear-email", made["id"])[1]
    assert lists.get_list(made["id"])["email"] is None and pending() == 0
    assert _log() == [("set-email", made["id"]), ("clear-email", made["id"])]

    with pytest.raises(SystemExit, match="doesn't look like an email"):
        run("set-email", made["id"], "not-an-address")
    with pytest.raises(SystemExit, match="No list has id 999"):
        run("set-email", 999, "a@b.co")


def test_disable_turns_every_surface_into_an_unknown_link_and_enable_restores_them(
    made, new_list, client, run, tmp_path, monkeypatch
):
    from backend import pages

    (tmp_path / "index.html").write_text("<html><head></head></html>")
    monkeypatch.setattr(pages, "INDEX_PATH", tmp_path / "index.html")
    monkeypatch.setattr(pages, "_index_cache", None)
    other = new_list()
    working = {"web page": 200, "session": 200, "api": 200, "capture": 200, "mcp": 200}
    assert _surfaces(client, made) == working

    code, out = run("disable", made["id"])
    assert code == 0 and f"List {made['id']}: disabled" in out
    assert _surfaces(client, made) == {"web page": 303, "session": 401, "api": 401, "capture": 404, "mcp": 404}
    assert client.get(f"/c/{made['capture']}").status_code == 404
    assert other["client"].get("/api/app/todos").status_code == 200  # only that list
    assert service.list_todos(made["id"])  # nothing was deleted
    assert "disabled" in run("lists")[1]
    assert json.loads(run("find", f"--link={made['agent_token']}", "--json")[1])["disabled"] is True
    assert "nothing changed" in run("disable", made["id"])[1]

    code, out = run("enable", made["id"])
    assert f"List {made['id']}: enabled" in out
    assert _surfaces(client, made) == working
    assert "nothing changed" in run("enable", made["id"])[1]
    assert _log() == [("disable", made["id"]), ("enable", made["id"])]


def test_a_disabled_list_gets_no_sign_in_mail(made, run, monkeypatch, confirm):
    sent = []
    monkeypatch.setattr(signin, "_send", lambda *a: sent.append(a))
    confirm(made["id"])
    run("disable", made["id"])
    signin.request_signin("me@example.com", "https://todo.example")
    assert sent == []


def test_a_sign_in_link_mailed_before_disable_redeems_nothing_until_enable(made, run, monkeypatch, confirm):
    sent = []
    monkeypatch.setattr(signin, "_send", lambda *a: sent.append(a))
    confirm(made["id"])
    signin.request_signin("me@example.com", "https://todo.example")
    token = sent[0][2].split("/signin/")[1].split()[0]
    run("disable", made["id"])
    assert signin.redeem(token) is None
    run("enable", made["id"])
    assert made["client"].get("/api/app/todos").status_code == 200  # still signed in
    assert signin.redeem(token)["list_id"] == made["id"]


def test_delete_needs_the_exact_flag_and_removes_only_that_list(made, new_list, client, run):
    other = new_list()
    other_id = other["list_id"]
    other["client"].post("/api/app/todos", json={"title": "keep me"})
    signin.issue_link(made["id"])

    for wrong in ([], ["--yes"], [f"--yes-delete-list-{other_id}"], [f"--yes-delete-list-{made['id']}", "--yes"]):
        code, out = run("delete", made["id"], *wrong)
        assert code == 1 and "Nothing was deleted" in out
        assert f"add --yes-delete-list-{made['id']}" in out
        assert (
            "2 todos, 1 projects, 0 areas, 0 rule fired, 0 rules, 0 readings, 0 boosts, 0 bookmarks, 0 events, 0 recordings, 0 cards, 0 labels, 0 board columns, 0 boards, 0 people, 0 site data fields, 0 site data, 0 site files, 0 site blobs, 0 sites, 0 notes, 0 brain files, 0 brain misses, 0 brain ais, 0 brain versions, 0 brain pages, 0 brain memories, 1 sessions, 1 signin tokens, 0 api keys"
            in out
        )
        assert lists.get_list(made["id"]) is not None
    assert list(backup.backups_dir().glob("todo-*.db")) == [] and _log() == []

    code, out = run("delete", made["id"], f"--yes-delete-list-{made['id']}")
    assert code == 0 and f"List {made['id']}: deleted." in out
    snapshots = list(backup.backups_dir().glob("todo-*.db"))
    assert len(snapshots) == 1 and snapshots[0].name in out
    conn = db.get_db()
    for table in ("todos", "projects", "areas", "sessions", "signin_tokens"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE list_id = ?", (made["id"],)).fetchone()[0] == 0
    assert lists.get_list(made["id"]) is None
    assert made["client"].get("/api/app/todos").status_code == 401
    assert [t["title"] for t in other["client"].get("/api/app/todos").json()["todos"]] == ["keep me"]
    assert _log() == [("delete", made["id"])]
    # The snapshot still has the list, for restore.
    snap = sqlite3.connect(snapshots[0])
    assert snap.execute("SELECT COUNT(*) FROM todos WHERE list_id = ?", (made["id"],)).fetchone()[0] == 2
    snap.close()


def test_delete_no_snapshot_skips_the_snapshot(made, run):
    code, _ = run("delete", made["id"], "--no-snapshot", f"--yes-delete-list-{made['id']}")
    assert code == 0 and lists.get_list(made["id"]) is None
    assert list(backup.backups_dir().glob("todo-*.db")) == []


def test_restore_delegates_to_restore_list(made, run, monkeypatch):
    snapshot = backup.snapshot()
    calls = []
    monkeypatch.setattr(restore_list, "main", calls.append)
    run("restore", made["id"], "--from", snapshot.name)  # a bare name is looked up in backups/
    run("restore", made["id"], "--from", snapshot)
    assert calls == [[str(snapshot), "--list-id", str(made["id"])]] * 2
    assert _log() == [("restore", made["id"])] * 2


def test_restore_puts_the_list_back(made, run, freeze):
    freeze("2026-10-04T12:00:00")
    snapshot = backup.snapshot()
    freeze("2026-10-04T12:00:05")  # restore_list snapshots first; names are per second
    made["client"].post("/api/app/todos", json={"title": "added later"})
    code, out = run("restore", made["id"], "--from", snapshot.name)
    assert code == 0 and f"List {made['id']} restored from {snapshot.name}" in out
    assert len(service.list_todos(made["id"])) == 2


def test_an_unknown_flag_is_refused_outside_delete(made, run):
    with pytest.raises(SystemExit):
        run("disable", made["id"], f"--yes-delete-list-{made['id']}")
    assert lists.get_list(made["id"])["disabled_at"] is None


# ── Privacy and concurrency ───────────────────────────────────────────────────


def test_no_token_is_ever_printed_except_the_one_sign_in_link(made, run, monkeypatch):
    lists.set_email(made["id"], "me@example.com")
    snapshot = backup.snapshot()
    monkeypatch.setattr(restore_list, "main", lambda argv: None)
    row = db.get_db().execute("SELECT * FROM lists WHERE id = ?", (made["id"],)).fetchone()
    secrets = [
        made["session"],
        made["agent_token"],
        made["capture"],
        lists.hash_token(made["session"]),
        row["agent_token_hash"],
    ]
    out = ""
    for argv in (
        ["stats"],
        ["stats", "--json"],
        ["lists", "--show-email"],
        ["lists", "--json"],
        ["find", f"--link={made['session']}"],
        ["find", f"--link={made['agent_token']}", "--json"],
        ["find", "--link", f"https://x/c/{made['capture']}"],
        ["show", made["id"], "--content", "--show-email"],
        ["show", made["id"], "--content", "--json"],
        ["set-email", made["id"], "you@example.com"],
        ["clear-email", made["id"]],
        ["disable", made["id"]],
        ["enable", made["id"]],
        ["sign-out-all", made["id"]],
        ["snapshots"],
        ["restore", made["id"], "--from", snapshot.name],
        ["delete", made["id"]],
    ):
        out += run(*argv)[1]
    assert not [s for s in secrets if s in out]

    new_out = run("signin-link", made["id"])[1]
    new = new_out.strip().splitlines()[1].rsplit("/signin/", 1)[1]
    assert new_out.count(new) == 1 and signin.redeem(new)["list_id"] == made["id"]
    assert not [s for s in secrets if s in new_out]
    out += run("delete", made["id"], "--no-snapshot", f"--yes-delete-list-{made['id']}")[1]
    assert not [s for s in [*secrets, new] if s in out]
    logged = " ".join(str(v) for r in db.get_db().execute("SELECT * FROM admin_log") for v in r)
    assert not [s for s in [*secrets, new, "me@example.com", "you@example.com"] if s in logged]


def test_a_write_succeeds_while_another_connection_holds_a_read_transaction(made, run):
    # The running app, mid-read, as a separate connection to the same file.
    reader = sqlite3.connect(db.db_path(), isolation_level=None)
    reader.execute("BEGIN")
    assert reader.execute("SELECT disabled_at FROM lists WHERE id = ?", (made["id"],)).fetchone()[0] is None
    try:
        code, out = run("disable", made["id"])
        assert code == 0 and "disabled" in out
        assert lists.get_list(made["id"])["disabled_at"] is not None
        # The reader's snapshot is the one it started with: no half-finished state.
        assert reader.execute("SELECT disabled_at FROM lists WHERE id = ?", (made["id"],)).fetchone()[0] is None
    finally:
        reader.execute("ROLLBACK")
        reader.close()


def test_no_database_is_refused_rather_than_created(tmp_path, monkeypatch, run):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(SystemExit, match="No database at"):
        run("stats")
    assert not (tmp_path / "nowhere").exists()


def test_startup_adds_the_new_columns_to_an_older_database(todo_db):
    made = lists.create_list()
    conn = db.get_db()
    conn.execute("ALTER TABLE lists DROP COLUMN name")
    conn.execute("ALTER TABLE lists DROP COLUMN disabled_at")
    conn.execute("ALTER TABLE lists DROP COLUMN email_verified_at")
    db.init_db()
    db.init_db()  # and again: the step is idempotent
    row = lists.get_list(made["list_id"])
    assert row["name"] == "" and row["disabled_at"] is None and row["email_verified_at"] is None
    assert lists.resolve_agent(made["agent_token"]) == made["list_id"]


def test_a_new_number_skips_one_that_is_taken(todo_db, monkeypatch):
    taken = lists.create_list()["list_id"]
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET account_no = '1234-5678' WHERE id = ?", (taken,))
    rolls = iter([234, 5678, 235, 78])
    monkeypatch.setattr(lists.secrets, "randbelow", lambda _: next(rolls))
    assert lists.account_no_in(db.get_db()) == "1235-0078"


def test_every_list_argument_takes_an_id_or_an_account_number(made, run):
    number = "1234-5678"
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET account_no = ? WHERE id = ?", (number, made["id"]))
    for ref in (made["id"], number, "12345678", f" {number} "):
        data = json.loads(run("show", ref, "--json")[1])
        assert data["id"] == made["id"] and data["account_no"] == number
    assert json.loads(run("lists", "--json")[1])[0]["account_no"] == number
    assert number in run("lists")[1]
    assert run("sign-out-all", number)[0] == 0
    assert _log() == [("sign-out-all", made["id"])]
    code, out = run("delete", number)  # the confirmation flag still names the id
    assert code == 1 and f"--yes-delete-list-{made['id']}" in out
    with pytest.raises(SystemExit, match="No list has id or account number 9999-9999"):
        run("show", "9999-9999")
    with pytest.raises(SystemExit, match="No list has id 99999999"):
        run("show", "99999999")


def test_site_down_and_up_by_id_and_host(L, run, monkeypatch):
    from backend import sites

    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (L,))
    page = sites.publish(L, "Hello")
    host = db.get_db().execute("SELECT host FROM sites WHERE id = ?", (page["id"],)).fetchone()[0]
    code, out = run("site-down", host)
    assert code == 0 and "taken down by the operator" in out and host not in out
    assert sites.lookup_host(host) is None
    sites.publish(L, "Republished", site_id=page["id"])
    sites.update(L, page["id"], status="published")
    assert sites.get_site(L, page["id"])["suspended_at"]
    assert sites.lookup_host(host) is None
    code, out = run("site-up", page["id"])
    assert code == 0 and "suspension cleared" in out
    assert sites.lookup_host(host)["id"] == page["id"]
    assert _log() == [(f"site-down {page['id']}", L), (f"site-up {page['id']}", L)]
    run("site-down", page["id"])
    run("site-up", host)
    with pytest.raises(SystemExit, match="Site not found"):
        run("site-down", "unknown")
