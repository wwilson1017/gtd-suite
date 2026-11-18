"""Lists, tokens, sessions, the schema migration, and cross-list isolation at the service layer."""

import hashlib
import sqlite3
from pathlib import Path

import pytest

from backend import common, db, lists, notes, service, sessions, signin
from backend.common import ValidationError


def test_create_list_mints_two_tokens_and_a_session_all_distinct_and_long(todo_db):
    made = lists.create_list("Europe/Paris")
    tokens = {made["agent_token"], made["capture_token"], made["session_token"]}
    assert len(tokens) == 3
    assert all(len(t) >= 43 for t in tokens)
    # Letters and digits only: a chat's markdown pass escapes _ and breaks on -.
    assert made["agent_token"].isalnum() and made["capture_token"].isalnum()
    assert made["tz"] == "Europe/Paris"
    assert lists.create_list()["agent_token"] != made["agent_token"]


def test_the_session_is_stored_only_as_a_hash_and_the_agent_token_can_be_shown(todo_db):
    made = lists.create_list()
    row = dict(db.get_db().execute("SELECT * FROM lists WHERE id = ?", (made["list_id"],)).fetchone())
    assert "web_token_hash" not in row
    assert row["agent_token_hash"] == hashlib.sha256(made["agent_token"].encode()).hexdigest()
    assert row["agent_token"] == made["agent_token"]
    assert row["capture_token"] == made["capture_token"]
    session = dict(db.get_db().execute("SELECT * FROM sessions").fetchone())
    assert session["token_hash"] == hashlib.sha256(made["session_token"].encode()).hexdigest()
    assert session["list_id"] == made["list_id"] and made["session_token"] not in session.values()
    info = lists.get_list(made["list_id"])
    assert "agent_token_hash" not in info
    assert info["agent_token"] == made["agent_token"]


def test_each_token_resolves_only_on_its_own_surface(todo_db):
    made = lists.create_list()
    lid = made["list_id"]
    agent, capture, session = made["agent_token"], made["capture_token"], made["session_token"]
    assert lists.resolve_agent(agent) == lid
    assert lists.resolve_capture(capture) == lid
    assert sessions.resolve(session)["list_id"] == lid
    # A session is not an agent credential, and so on round the triangle.
    assert lists.resolve_agent(session) is None and lists.resolve_capture(session) is None
    assert sessions.resolve(agent) is None and lists.resolve_capture(agent) is None
    assert sessions.resolve(capture) is None and lists.resolve_agent(capture) is None
    # Nor are the stored hashes themselves credentials.
    for stored in (lists.hash_token(session), lists.hash_token(agent)):
        assert sessions.resolve(stored) is None and lists.resolve_agent(stored) is None


@pytest.mark.parametrize("token", ["", None, "nope", "x" * 5000])
def test_unknown_tokens_resolve_to_none(todo_db, token):
    lists.create_list()
    assert sessions.resolve(token) is None
    assert lists.resolve_agent(token) is None
    assert lists.resolve_capture(token) is None


def test_a_session_idle_for_a_year_is_signed_out_and_then_expired(todo_db, freeze):
    freeze("2026-01-01T12:00:00")
    made = lists.create_list()
    freeze("2026-12-31T12:00:00")
    assert sessions.resolve(made["session_token"]) is not None
    assert sessions.expire(common.utcnow()) == 0
    freeze("2027-01-01T12:00:01")
    assert sessions.resolve(made["session_token"]) is None
    assert sessions.expire(common.utcnow()) == 1
    assert db.get_db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_a_session_touch_is_hourly_and_moves_only_the_row(todo_db, freeze):
    freeze("2026-08-08T10:00:00")
    made = lists.create_list()
    token_hash = lists.hash_token(made["session_token"])

    def used():
        return db.get_db().execute("SELECT last_used_at FROM sessions").fetchone()[0]

    freeze("2026-08-08T10:30:00")
    sessions.touch(token_hash)
    assert used() == "2026-08-08T10:00:00.000Z"
    freeze("2026-08-08T11:00:01")
    sessions.touch(token_hash)
    assert used() == "2026-08-08T11:00:01.000Z"
    assert lists.get_list(made["list_id"])["last_used_at"] is None  # the list is not touched


def test_a_disabled_list_has_no_signed_in_browser(todo_db):
    made = lists.create_list()
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), made["list_id"]))
    assert sessions.resolve(made["session_token"]) is None


def test_rotate_agent_replaces_only_the_agent_token(todo_db):
    made = lists.create_list()
    lid = made["list_id"]
    new = lists.rotate_agent(lid)
    assert new != made["agent_token"]
    assert lists.resolve_agent(made["agent_token"]) is None
    assert lists.resolve_agent(new) == lid
    assert lists.get_list(lid)["agent_token"] == new
    assert sessions.resolve(made["session_token"])["list_id"] == lid
    assert lists.resolve_capture(made["capture_token"]) == lid
    assert lists.rotate_agent(999) is None


def test_startup_adds_the_agent_token_column_and_backfills_old_lists(todo_db, tmp_path):
    """The live database predates `lists.agent_token`: its agent tokens exist only
    as hashes. Startup adds the column and gives each such list a fresh token."""
    kept = lists.create_list()
    old = lists.create_list()
    service.create_todo(old["list_id"], "survives the upgrade")
    db.close_db()
    # Put the file back to the old shape: no agent_token column at all.
    raw = sqlite3.connect(tmp_path / "todo.db")
    raw.execute("ALTER TABLE lists DROP COLUMN agent_token")
    raw.commit()
    raw.close()

    db.init_db()
    rows = {r["id"]: r for r in db.get_db().execute("SELECT * FROM lists")}
    for made in (kept, old):
        row = rows[made["list_id"]]
        # A fresh token (the old one cannot be recovered from its hash), stored both ways.
        assert row["agent_token"] and row["agent_token"] != made["agent_token"]
        assert row["agent_token_hash"] == lists.hash_token(row["agent_token"])
        assert lists.resolve_agent(row["agent_token"]) == made["list_id"]
        assert lists.resolve_agent(made["agent_token"]) is None
        # Nothing else moved.
        assert sessions.resolve(made["session_token"])["list_id"] == made["list_id"]
        assert lists.resolve_capture(made["capture_token"]) == made["list_id"]
    assert [t["title"] for t in service.list_todos(old["list_id"])] == ["survives the upgrade"]

    # Idempotent: a second startup changes nothing.
    before = {i: r["agent_token"] for i, r in rows.items()}
    db.init_db()
    after = {r["id"]: r["agent_token"] for r in db.get_db().execute("SELECT * FROM lists")}
    assert after == before


def test_rotate_capture_replaces_only_the_capture_token(todo_db):
    made = lists.create_list()
    lid = made["list_id"]
    new = lists.rotate_capture(lid)
    assert new != made["capture_token"]
    assert lists.resolve_capture(made["capture_token"]) is None
    assert lists.resolve_capture(new) == lid
    assert sessions.resolve(made["session_token"])["list_id"] == lid
    assert lists.rotate_capture(999) is None


def _signin_count(list_id):
    return db.get_db().execute("SELECT COUNT(*) FROM signin_tokens WHERE list_id = ?", (list_id,)).fetchone()[0]


def test_set_email_normalizes_and_clears(todo_db):
    lid = lists.create_list()["list_id"]
    assert lists.set_email(lid, " Me@Example.com ") == "me@example.com"
    assert lists.get_list(lid)["email"] == "me@example.com"
    assert lists.set_email(lid, "") is None
    assert lists.get_list(lid)["email"] is None
    with pytest.raises(ValidationError, match="email"):
        lists.set_email(lid, "not-an-email")


def test_changing_or_clearing_the_email_cancels_sign_in_links_but_no_session(todo_db):
    a, b = lists.create_list(), lists.create_list()
    lists.set_email(a["list_id"], "me@example.com")
    lists.set_email(b["list_id"], "me@example.com")
    signin.issue_link(a["list_id"])
    signin.issue_link(b["list_id"])

    lists.set_email(a["list_id"], "ME@example.com")  # same address: links stay
    assert _signin_count(a["list_id"]) == 1
    lists.set_email(a["list_id"], "other@example.com")  # changed: gone
    assert _signin_count(a["list_id"]) == 0
    assert _signin_count(b["list_id"]) == 1  # another list's links untouched

    signin.issue_link(a["list_id"])
    lists.set_email(a["list_id"], None)  # cleared: gone
    assert _signin_count(a["list_id"]) == 0
    # The browser that changed it stays signed in.
    assert sessions.resolve(a["session_token"])["list_id"] == a["list_id"]


def test_only_a_change_of_address_clears_its_confirmation(todo_db, confirm, freeze):
    lid = lists.create_list()["list_id"]
    freeze("2026-10-11T12:00:00")
    confirm(lid)
    freeze("2026-10-11T13:00:00")
    with db.transaction() as conn:
        assert lists.set_email_in(conn, lid, " ME@example.com") == ("me@example.com", True)
        lists.verify_email_in(conn, lid)  # a second confirmation, an hour on, keeps the first stamp
    assert lists.get_list(lid)["email_verified_at"] == "2026-10-11T12:00:00.000Z"
    with db.transaction() as conn:
        assert lists.set_email_in(conn, lid, "new@example.com") == ("new@example.com", False)
    assert lists.get_list(lid)["email_verified_at"] is None
    confirm(lid, "new@example.com")
    assert lists.set_email(lid, "") is None
    row = lists.get_list(lid)
    assert (row["email"], row["email_verified_at"]) == (None, None)


def test_touch_records_use_at_most_hourly(todo_db, freeze):
    lid = lists.create_list()["list_id"]
    assert lists.get_list(lid)["last_used_at"] is None
    freeze("2026-08-08T10:00:00")
    lists.touch(lid)
    assert lists.get_list(lid)["last_used_at"] == "2026-08-08T10:00:00.000Z"
    freeze("2026-08-08T10:30:00")
    lists.touch(lid)
    assert lists.get_list(lid)["last_used_at"] == "2026-08-08T10:00:00.000Z"
    freeze("2026-08-08T11:00:01")
    lists.touch(lid)
    assert lists.get_list(lid)["last_used_at"] == "2026-08-08T11:00:01.000Z"
    lists.touch(999)  # unknown list: no error


class TestCrossListIsolation:
    @pytest.fixture()
    def two(self, todo_db):
        a = lists.create_list()["list_id"]
        b = lists.create_list()["list_id"]
        return a, b

    def test_reads_are_scoped(self, two):
        a, b = two
        theirs = service.create_todo(b, "B secret", project="B project", context="@b", tags=["btag"])
        assert service.get_todo(a, theirs["id"]) is None
        assert service.list_todos(a) == []
        assert service.list_todos(a, search="secret") == []
        assert service.list_todos(a, project=theirs["project_id"]) == []
        assert service.list_todos(a, project="B project") == []
        assert service.today_view(a) == []
        assert service.list_projects(a) == []
        assert service.get_project(a, theirs["project_id"]) is None
        filters = service.get_filters(a)
        assert filters["contexts"] == [] and filters["tags"] == []
        assert sum(filters["status_counts"].values()) == 0

    def test_writes_are_scoped(self, two):
        a, b = two
        theirs = service.create_todo(b, "B todo", project="B project")
        assert service.update_todo(a, theirs["id"], {"title": "hijacked"}) is None
        assert service.bulk_update(a, [theirs["id"]], {"status": "dropped"}) == {
            "updated": [],
            "not_found": [theirs["id"]],
        }
        assert service.update_project(a, theirs["project_id"], {"name": "hijacked"}) is None
        after = service.get_todo(b, theirs["id"])
        assert (after["title"], after["status"], after["project_name"]) == (
            "B todo",
            "inbox",
            "B project",
        )

    def test_cannot_attach_another_lists_project(self, two):
        a, b = two
        their_project = service.create_project(b, "B project")["id"]
        mine = service.create_todo(a, "mine")
        with pytest.raises(ValidationError, match="Project id not found"):
            service.create_todo(a, "x", project_id=their_project)
        with pytest.raises(ValidationError, match="Project id not found"):
            service.update_todo(a, mine["id"], {"project_id": their_project})
        with pytest.raises(ValidationError, match="Project id not found"):
            service.bulk_update(a, [mine["id"]], {"project_id": their_project})
        assert service.get_todo(a, mine["id"])["project_id"] is None
        assert service.get_project(b, their_project)["open_count"] == 0

    def test_same_project_name_is_a_separate_project_per_list(self, two):
        a, b = two
        pa = service.create_todo(a, "x", project="Home")["project_id"]
        pb = service.create_todo(b, "y", project="home")["project_id"]
        assert pa != pb
        assert service.create_project(a, "Shared name") and service.create_project(b, "Shared name")

    def test_spawn_stays_in_its_list(self, two):
        a, b = two
        t = service.create_todo(a, "r", status="next_action", repeat="daily")
        service.update_todo(a, t["id"], {"status": "done"})
        assert len(service.list_todos(a)) == 2
        assert service.list_todos(b) == []


# ── Migrating a database made by the link-based release ───────────────────────

OLD_SCHEMA = Path(__file__).with_name("schema_before_sessions.sql").read_text()


@pytest.fixture()
def old_db(todo_db, tmp_path):
    """An empty database in the link-based release's shape, open for writing."""
    db.close_db()
    for f in tmp_path.glob("todo.db*"):
        f.unlink()
    raw = sqlite3.connect(tmp_path / "todo.db")
    raw.executescript(OLD_SCHEMA)
    yield raw
    raw.close()


def _old_list(raw, n, **extra):
    raw.execute(
        "INSERT INTO lists (web_token_hash, agent_token_hash, agent_token, capture_token, "
        "created_at, name, email) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            f"web{n}",
            lists.hash_token(f"agent{n}"),
            f"agent{n}",
            f"capture{n}",
            "2026-01-01T00:00:00.000Z",
            f"List {n}",
            extra.get("email"),
        ),
    )


def _sequence():
    return [tuple(r) for r in db.get_db().execute("SELECT name, seq FROM sqlite_sequence WHERE name = 'lists'")]


def test_rows_from_before_the_change_counter_each_get_a_number(old_db):
    """So a first sync (service.changes from 0) pages through them: parents
    first, one number a row, each list counted on its own."""
    stamp = "'2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z'"
    for n in (1, 2):
        _old_list(old_db, n)
    old_db.execute(f"INSERT INTO todos (list_id, title, created_at, updated_at) VALUES (1, 'a', {stamp})")
    old_db.execute(f"INSERT INTO todos (list_id, title, created_at, updated_at) VALUES (2, 'theirs', {stamp})")
    old_db.execute(f"INSERT INTO todos (list_id, title, created_at, updated_at) VALUES (1, 'b', {stamp})")
    old_db.execute(f"INSERT INTO projects (list_id, name, created_at, updated_at) VALUES (1, 'Fence', {stamp})")
    old_db.execute(f"INSERT INTO areas (list_id, name, created_at, updated_at) VALUES (1, 'Home', {stamp})")
    old_db.commit()
    old_db.close()

    db.init_db()
    db.close_db()
    db.init_db()  # a second start renumbers nothing
    seen, since = [], 0
    while True:
        out = service.changes(1, since, limit=2)
        seen += [row.get("title") or row["name"] for kind in ("areas", "projects", "todos") for row in out[kind]]
        since = out["next_since"]
        if not out["more"]:
            break
    assert seen == ["Home", "Fence", "a", "b"] and since == 4
    assert service.changes(2)["next_since"] == 1
    service.update_todo(1, service.list_todos(1)[0]["id"], {"star": True})
    assert [t["title"] for t in service.changes(1, since)["todos"]] == ["a"]


def test_an_upgrade_from_the_counter_without_changed_at_makes_the_triggers_again(todo_db, tmp_path):
    """That release had the same triggers without the stamp, and CREATE TRIGGER
    IF NOT EXISTS would keep them: the count would move and changed_at never."""
    list_id = lists.create_list("UTC")["list_id"]
    todo = service.create_todo(list_id, "a")
    db.close_db()
    raw = sqlite3.connect(tmp_path / "todo.db")
    for trigger in db._rev_triggers():
        raw.execute(f"DROP TRIGGER {trigger.split()[5]}")
    raw.execute("ALTER TABLE lists DROP COLUMN changed_at")
    for trigger in db._rev_triggers():
        old = trigger.replace(f", changed_at = {db.NOW_SQL}", "")
        assert "changed_at" not in old
        raw.execute(old)
    raw.commit()
    raw.close()

    db.init_db()
    assert service.changes_count(list_id) == {"count": 1, "last_change_at": None}
    service.update_todo(list_id, todo["id"], {"star": True})
    after = service.changes_count(list_id)
    assert after["count"] == 2 and after["last_change_at"] is not None
    db.close_db()
    db.init_db()  # a second start changes nothing
    assert service.changes_count(list_id) == after


def test_startup_rebuilds_lists_without_the_web_token_and_every_id_survives(old_db):
    for n in (1, 2, 3):
        _old_list(old_db, n, email="me@example.com" if n == 1 else None)
    old_db.execute(
        "INSERT INTO todos (list_id, title, created_at, updated_at) "
        "VALUES (2, 'survives', '2026-01-01T00:00:00.000Z', '2026-01-01T00:00:00.000Z')"
    )
    old_db.execute("INSERT INTO recovery_tokens VALUES ('h', 1, '2099-01-01T00:00:00.000Z')")
    old_db.execute("DELETE FROM lists WHERE id = 3")  # the highest id, deleted
    old_db.commit()
    old_db.close()

    db.init_db()
    conn = db.get_db()
    assert "web_token_hash" not in {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}
    assert [(r["id"], r["name"], r["email"]) for r in conn.execute("SELECT * FROM lists ORDER BY id")] == [
        (1, "List 1", "me@example.com"),
        (2, "List 2", None),
    ]
    # An email from before confirmation existed starts unconfirmed.
    assert lists.get_list(1)["email_verified_at"] is None
    assert [lists.resolve_agent(f"agent{n}") for n in (1, 2)] == [1, 2]
    assert [lists.resolve_capture(f"capture{n}") for n in (1, 2)] == [1, 2]
    assert [t["title"] for t in service.list_todos(2)] == ["survives"]
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "recovery_tokens" not in tables and {"sessions", "signin_tokens"} <= tables
    assert "idx_lists_email" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # Exactly one high-water mark, and the deleted list's id is never handed out again.
    assert _sequence() == [("lists", 3)]
    assert lists.create_list()["list_id"] == 4
    # The children still point at the rebuilt table, with foreign keys enforced.
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO todos (list_id, title, created_at, updated_at) "
                "VALUES (99, 'x', '2026-01-01', '2026-01-01')"
            )

    # A second startup changes nothing.
    before = [tuple(r) for r in conn.execute("SELECT * FROM lists ORDER BY id")]
    db.init_db()
    assert [tuple(r) for r in db.get_db().execute("SELECT * FROM lists ORDER BY id")] == before
    assert _sequence() == [("lists", 4)]


def test_the_rebuild_keeps_the_high_water_mark_of_an_emptied_table(old_db):
    _old_list(old_db, 1)
    _old_list(old_db, 2)
    old_db.execute("DELETE FROM lists")
    old_db.commit()
    old_db.close()
    db.init_db()
    assert _sequence() == [("lists", 2)]
    assert lists.create_list()["list_id"] == 3


def test_no_delete_functions_exist():
    for module in (service, lists, notes):
        assert not [n for n in dir(module) if "delete" in n.lower()], module
    assert "DELETE FROM todos" not in open(service.__file__).read()
    assert common.TODO_SOURCES == ("ui", "capture", "agent")
