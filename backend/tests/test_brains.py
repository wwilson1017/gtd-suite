"""Brain gates, account-wide limits, and moves/restores across the storage boundary."""

import re
import json
import sqlite3
import zipfile

import pytest

from backend import apps, brain, brain_import, cleanup, common, db, files, keys, lists, objectstore, service
from backend.common import NotFoundError, ValidationError
from backend.tests.conftest import confirm_list
from backend.tests.test_files import CFG, FakeStore, item
from scripts import restore_list

TABLES = ("brain_memories", "brain_pages", "brain_versions", "brain_ais", "brain_misses", "brain_files")


def add_brain(list_id, folder="second"):
    with db.transaction() as conn:
        return conn.execute(
            "INSERT INTO brains (list_id, folder, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (list_id, folder, common.now_iso(), common.now_iso()),
        ).lastrowid


@pytest.fixture()
def two(L):
    second = add_brain(L)
    other = lists.create_list()["list_id"]
    assert second == other  # A brain id is deliberately also a DIFFERENT account's id.
    return L, brain.first_brain(L), second, other


@pytest.fixture()
def store(todo_db, monkeypatch):
    for name, value in CFG.items():
        monkeypatch.setenv(f"FILES_S3_{name}", value)
    fake = FakeStore()
    monkeypatch.setattr(objectstore.httpx, "request", fake.request)
    return fake


def copy_db(path):
    with sqlite3.connect(path) as target:
        db.get_db().backup(target)


def old_shape(path):
    """Turn a fixture into the pre-brains schema, keeping ids, FTS and sequences.

    Drop the new column by rebuilding because pages and AIs also changed constraints.
    This is fixture preparation only; init_db then runs the real forward migration.
    """
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ALTER TABLE lists DROP COLUMN link_brains")
        conn.execute("ALTER TABLE api_keys DROP COLUMN brains")
        conn.execute("ALTER TABLE api_keys DROP COLUMN kind")
        for table in TABLES:
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
            sql = re.sub(r"brain_id\s+INTEGER NOT NULL REFERENCES brains\(id\),\s*", "", sql)
            sql = sql.replace("UNIQUE(brain_id, path)", "UNIQUE(list_id, path)")
            sql = sql.replace("PRIMARY KEY (brain_id, name)", "PRIMARY KEY (list_id, name)")
            sql = (
                sql.replace(f'"{table}"', f"{table}_old", 1)
                if f'"{table}"' in sql
                else sql.replace(table, table + "_old", 1)
            )
            cols = ", ".join(r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] != "brain_id")
            seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
            conn.execute(sql)
            conn.execute(f"INSERT INTO {table}_old ({cols}) SELECT {cols} FROM {table}")
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {table}_old RENAME TO {table}")
            if seq:
                conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (seq[0], table))
        conn.execute("DELETE FROM brains")
        # Make new brain ids differ from their lists after migration.
        conn.execute("UPDATE sqlite_sequence SET seq = 100 WHERE name = 'brains'")
        for ddl in db._BRAIN_FTS_TRIGGERS:
            conn.execute(ddl)


def test_create_and_cleanup(L):
    rows = brain.brains(L)
    assert len(rows) == 1
    assert rows[0] == brain._brain_out(db.get_db().execute("SELECT * FROM brains WHERE list_id = ?", (L,)).fetchone())
    assert (rows[0]["name"], rows[0]["folder"], rows[0]["settled_at"]) == ("", "brain", None)
    assert rows[0]["ai_access"] == "write" and rows[0]["rules"] == []
    assert "brains" not in apps.content_tables()
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = '2000-01-01T00:00:00Z' WHERE id = ?", (L,))
    assert cleanup.delete_unused_lists() == 1
    assert brain.brains(L) == []
    assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_account_boundaries_and_ai_admission(two, monkeypatch):
    account, first, second, other = two
    conn = db.get_db()
    brain.remember(first, ["First memory"], by="Claude")
    brain.remember(second, ["Second memory"], by="Claude")  # already admitted, even at the cap
    assert brain._ai_names(conn, second) == ["Claude"]
    assert brain._count(conn, "brain_memories", second) == 2
    assert brain._count(conn, "brain_memories", brain.first_brain(other)) == 0
    cap = brain._plan(conn, second)["memories"]
    assert brain.start(second, "Claude", ["brain"])["limits"]["memories"] == f"2 of {cap}"  # the account's
    assert brain.curate(second)["counts"]["memories"] == f"2 of {cap}"
    assert "Claude" in brain._email_nudge(conn, second, "ChatGPT")
    with pytest.raises(ValidationError):
        brain.remember(second, ["Refused"], by="ChatGPT")
    assert brain._plan(conn, second)["needs_email"]
    confirm_list(other)
    assert brain._plan(conn, second)["needs_email"]  # no accidental use of the other account
    confirm_list(account)
    assert not brain._plan(conn, second)["needs_email"]
    service.create_todo(account, "Account task")
    assert "1 in the inbox" in brain._todo_line(second)
    assert brain._todo_line(brain.first_brain(other)) == "Todo GTD is empty."
    monkeypatch.setattr(common, "brain_caps_for", lambda *args: (10, 2, 2))
    with pytest.raises(ValidationError):
        brain.remember(second, ["Shared cap"])
    a = brain.write_page(first, "same", "first needle")
    b = brain.write_page(second, "same", "second needle")
    assert [r["id"] for r in brain.search(second, "needle")["pages"]] == [b["id"]]
    assert [r["id"] for r in brain.pages(first)] == [a["id"]]
    assert [r["text"] for r in brain.memories(second)] == ["Second memory"]
    for call in (
        lambda: brain.get_page(second, a["id"]),
        lambda: brain.get_memory(second, brain.memories(first)[0]["id"]),
        lambda: brain.update_page(second, a["id"], {"body": "bad"}),
        lambda: brain.history(second, "page", a["id"]),
        lambda: brain.restore(second, "page", a["id"], 1),
        lambda: brain.forget(second, "page", a["id"]),
    ):
        with pytest.raises(NotFoundError):
            call()


def test_share_publishes_to_account(two, monkeypatch):
    account, _, second, other = two
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    page = brain.write_page(second, "share-me", "Share this")
    brain.share(second, page["id"])
    assert db.get_db().execute("SELECT list_id FROM sites").fetchone()[0] == account
    assert not db.get_db().execute("SELECT 1 FROM sites WHERE list_id = ?", (other,)).fetchone()


def test_file_quota_keys_and_operator_delete(two, store, monkeypatch):
    account, first, second, other = two
    confirm_list(account)
    confirm_list(other)
    monkeypatch.setattr(common, "file_quota_for", lambda *args: 6)
    for bid in (first, second, brain.first_brain(other)):
        reserved = files.reserve(bid, [item("same.pdf", b"abc")])["files"][0]
        store.put(reserved["upload"], b"abc")
        files.done(bid, reserved["id"])
    assert files._used(db.get_db(), second) == 6
    assert files._used(db.get_db(), brain.first_brain(other)) == 3
    with pytest.raises(ValidationError):
        files.reserve(second, [item("over.pdf", b"x")])
    for row in db.get_db().execute("SELECT list_id, object_key FROM brain_files"):
        assert row["object_key"].startswith(f"{row['list_id']}/")
    theirs = files.listing(first)[0]
    with pytest.raises(NotFoundError):
        files.get(second, theirs["id"])
    assert len(files.listing(second)) == 1
    assert files.delete_objects(account) == 2
    assert len(store.objects) == 1
    assert next(iter(store.objects)).startswith(f"{other}/")


def test_browser_current_brain(new_list):
    acct = new_list()
    c, account = acct["client"], acct["list_id"]
    first, second = brain.first_brain(account), add_brain(account)
    other = lists.create_list()["list_id"]
    page = brain.write_page(first, "one", "First")
    brain.write_page(second, "two", "Second")
    assert c.get("/api/app/brain").json()["pages"][0]["path"] == "one"
    headers = {"X-Brain": str(second)}
    assert c.get("/api/app/brain", headers=headers).json()["pages"][0]["path"] == "two"
    assert c.get(f"/api/app/brain/pages/{page['id']}", headers=headers).status_code == 404
    assert c.put(f"/api/app/brain/pages/{page['id']}", headers=headers, json={"body": "bad"}).status_code == 404
    with db.transaction() as conn:
        conn.execute("UPDATE brains SET status = 'archived' WHERE id = ?", (second,))
    for value in (str(second), str(brain.first_brain(other)), "garbage", "99999"):
        response = c.get("/api/app/brain", headers={"X-Brain": value})
        assert response.status_code == 409 and response.json()["detail"] == {"brain_gone": True}
        assert response.headers["cache-control"] == "no-store"


def test_old_shape_migration_preserves_rows_fts_and_sequences(L, store):
    other = lists.create_list()["list_id"]
    for account in (L, other):
        bid = brain.first_brain(account)
        confirm_list(account)
        brain.remember(bid, ["Migration memory"], by="Claude")
        brain.write_page(bid, "migration", "Migration needle")
        brain.search(bid, "unfindableword", by="Claude")
        files.reserve(bid, [item("file.pdf", b"x")])
    with db.transaction() as conn:
        for table in TABLES:
            if table != "brain_ais":
                conn.execute("UPDATE sqlite_sequence SET seq = 900 WHERE name = ?", (table,))
    before = {t: [dict(r) for r in db.get_db().execute(f"SELECT * FROM {t}")] for t in TABLES}
    path = db.db_path()
    db.close_db()
    old_shape(path)
    db.init_db()
    db.init_db()  # idempotence, including _SCHEMA before _migrate
    conn = db.get_db()
    for table in TABLES:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
        for row, old in zip(rows, before[table], strict=True):
            assert row.pop("brain_id") == brain.first_brain(row["list_id"])
            old.pop("brain_id")
            assert row == old
        if table != "brain_ais":
            assert conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()[0] == 900
    for account in (L, other):
        assert [b["id"] for b in brain.main_brains(account)] == [brain.first_brain(account)]
        assert len(brain.search(brain.first_brain(account), "migration")["pages"]) == 1
        assert len(brain.search(brain.first_brain(account), "migration")["memories"]) == 1
    second = add_brain(L)
    assert brain.write_page(second, "migration", "Different brain")["id"] == 901
    for table in TABLES:
        old = before[table][0]
        columns = ", ".join(old)
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL constraint failed: .*brain_id"):
            with db.transaction() as tx:
                tx.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({', '.join('?' for _ in old)})", tuple(old.values())
                )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("legacy", [False, True])
def test_restore_preserves_settings_files_and_keys(L, store, tmp_path, legacy):
    first = brain.first_brain(L)
    confirm_list(L)
    brain.write_page(first, "saved", "Before")
    snapshot_only = None
    if not legacy:
        snapshot_only = add_brain(L, "snapshot-only")
        brain.write_page(snapshot_only, "lost", "Snapshot-only content")
    snapshot = tmp_path / "snapshot.db"
    copy_db(snapshot)
    if legacy:
        old_shape(snapshot)
    else:
        # A snapshot from a divergent history has a brain that is not live here.
        with db.transaction() as conn:
            for table in reversed(TABLES):
                conn.execute(f"DELETE FROM {table} WHERE brain_id = ?", (snapshot_only,))
            conn.execute("DELETE FROM brains WHERE id = ?", (snapshot_only,))
    later = add_brain(L, "later")
    reserved = files.reserve(later, [item("live.pdf", b"live")])["files"][0]
    store.put(reserved["upload"], b"live")
    files.done(later, reserved["id"])
    key = keys.create(L, "reader", app="brain", access="read")
    brain.write_page(first, "saved", "After")
    with db.transaction() as conn:
        conn.execute(
            "UPDATE brains SET name = 'Changed', status = 'archived', ai_access = 'inbox', rules = '[\"Keep\"]', settled_at = 'now' WHERE id = ?",
            (first,),
        )
    settings_before = brain.brains(L)
    keys_before = [dict(r) for r in db.get_db().execute("SELECT * FROM api_keys")]
    files_before = [dict(r) for r in db.get_db().execute("SELECT * FROM brain_files")]
    restore_list.restore(snapshot, L, db.db_path())
    assert brain.get_page(first, path="saved")["body"] == "Before"
    assert brain.brains(L)[:2] == settings_before
    assert [dict(r) for r in db.get_db().execute("SELECT * FROM api_keys")] == keys_before
    assert key
    assert [dict(r) for r in db.get_db().execute("SELECT * FROM brain_files")] == files_before
    if not legacy:
        restored = brain.brains(L)[-1]
        assert restored["name"].startswith("Restored ")
        assert restored["status"] == "archived" and restored["ai_access"] == "read"
        assert brain.get_page(restored["id"], path="lost")["body"] == "Snapshot-only content"
    assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_import_scopes_preview_writes_and_archive(two, tmp_path):
    account, first, second, _ = two
    confirm_list(account)
    brain.write_page(first, "same", "Other brain")
    brain.write_page(first, "keep", "Keep this")
    brain.write_page(second, "old", "Archive this")
    path = tmp_path / "import.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("same.md", "Imported")
    preview = brain_import.plan(second, path, brain.YOU)
    assert preview["entries"][0]["planned"] == "add"
    result = brain_import.run(second, path, "Brain import", brain.YOU, archive_missing=True)
    assert result["complete"] and result["written"] == 1 and result["archived"] == 1
    assert brain.get_page(first, path="same")["body"] == "Other brain"
    assert brain.get_page(first, path="keep")["status"] == "active"
    assert brain.get_page(second, path="same")["body"] == "Imported"
    assert brain.get_page(second, path="old")["status"] == "archived"


def test_grants_are_ordered_owned_distinct_and_never_fall_back(two):
    account, first, second, other = two
    alien = brain.first_brain(other)
    for invalid in ([first, first], [alien], [None], "bad", [True]):
        with pytest.raises(ValidationError):
            brain.set_link_brains(account, invalid)
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET link_brains = ? WHERE id = ?", (json.dumps(invalid), account))
        assert brain.main_brains(account) == []
    brain.set_link_brains(account, [second, first])
    assert [b["id"] for b in brain.main_brains(account)] == [second, first]
    with pytest.raises(ValidationError):
        keys.create(account, "multi-folder", brains=[first, second], folders=["inbox"])
    key = keys.create(account, "one", brains=[second])
    brain.brain_status(account, second, "archived")
    assert keys.resolve(key["key"])["active_brains"] == []
    assert [b["id"] for b in brain.main_brains(account)] == [first]
    brain.set_link_brains(account, [])
    assert brain.main_brains(account) == []
    db.init_db()
    assert brain.main_brains(account) == []


def test_grant_migration_backfills_once_and_preserves_tokens(L):
    key = keys.create(L, "old")
    with db.transaction() as conn:
        conn.execute("ALTER TABLE lists DROP COLUMN link_brains")
        conn.execute("ALTER TABLE api_keys DROP COLUMN brains")
        conn.execute("ALTER TABLE api_keys DROP COLUMN kind")
    db.init_db()
    got = keys.resolve(key["key"])
    assert got["brains"] == [brain.first_brain(L)] and got["kind"] == "key"
    assert [b["id"] for b in brain.main_brains(L)] == got["brains"]
    with db.transaction() as conn:
        conn.execute("UPDATE api_keys SET brains = '[]'")
    db.init_db()
    assert keys.resolve(key["key"])["active_brains"] == []


@pytest.mark.parametrize("access", ["read", "inbox"])
def test_policy_covers_content_but_allows_read_bookkeeping(two, store, tmp_path, access):
    account, first, second, _ = two
    confirm_list(account)
    page = brain.write_page(first, "private/page", "before")
    brain.write_page(first, "private/page", "after", move_to="inbox/page")
    memory = brain.remember(first, ["before"])["added"][0]
    reserved = files.reserve(first, [item("private/file.pdf", b"x")], "AI")["files"][0]
    store.put(reserved["upload"], b"x")
    brain.update_brain(account, first, ai_access=access)
    for mutate in (
        lambda: brain.remember(first, ["bad"], by="AI"),
        lambda: brain.update_memory(first, memory["id"], text="bad", by="AI"),
        lambda: brain.update_memory(first, memory["id"], locked=True, by="AI"),
        lambda: brain.write_page(first, "outside/page", "bad", by="AI"),
        lambda: brain.write_page(first, "inbox/page", move_to="outside/page", by="AI"),
        lambda: brain.append_page(first, "outside/page", "bad", by="AI"),
        lambda: brain.restore(first, "page", page["id"], 1, by="AI"),
        lambda: brain.restore(first, "memory", memory["id"], 1, by="AI"),
        lambda: files.reserve(first, [item("private/new.pdf", b"x")], "AI"),
        lambda: files.done(first, reserved["id"]),
    ):
        with pytest.raises(ValidationError):
            mutate()
    if access == "read":
        for mutate in (
            lambda: brain.write_page(first, "inbox/page", by="AI"),
            lambda: brain.append_page(first, "inbox/page", "more", by="AI"),
            lambda: brain.edit_page(first, "inbox/page", "after", "changed", by="AI"),
        ):
            with pytest.raises(ValidationError, match="read-only"):
                mutate()
    else:
        assert brain.append_page(first, "inbox/page", "Allowed", by="AI")["body"].endswith("Allowed")
        with pytest.raises(ValidationError):
            brain.write_page(first, "outside/page", "bad", move_to="inbox/moved", by="AI")
    brain.start(first, "Reader", ["brain"])
    brain.search(first, "notfoundhere", by="Reader")
    brain.onboarded(first, "Reader")
    assert any(a["name"] == "Reader" and a["onboarded_at"] for a in brain.ais(first))
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_misses WHERE brain_id = ?", (first,)).fetchone()[0] == 1
    assert brain.update_memory(first, memory["id"], text="Owner change")["text"] == "Owner change"
    assert brain.write_page(first, "outside/owner", "Owner change")["body"] == "Owner change"
    zip_path = tmp_path / "policy.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("outside/new.md", "must not land")
    report = brain_import.run(first, zip_path, "policy", "AI")
    assert not report["complete"]
    with pytest.raises(NotFoundError):
        brain.get_page(first, path="outside/new")
    with pytest.raises(ValidationError):
        brain_import._archive_missing(first, [], "policy.zip", "AI", "policy", {"archived": 0})


def test_file_final_commit_rechecks_policy(two, store):
    account, first, _, _ = two
    confirm_list(account)
    upload = files.reserve(first, [item("inbox/race.pdf", b"x")], "AI")["files"][0]
    store.put(upload["upload"], b"x")
    store.hooks["PUT"] = lambda: brain.update_brain(account, first, ai_access="read")
    with pytest.raises(ValidationError, match="read-only"):
        files.done(first, upload["id"])
    assert files.listing(first) == []


@pytest.mark.parametrize("refusal", ["multiple", "todo", "projects", "notes", "sites", "disabled", "all", "grant"])
def test_merge_refusals_are_atomic(L, refusal):
    from backend import boards, notes, sites
    from scripts import admin

    target = lists.create_list()["list_id"]
    if refusal == "multiple":
        add_brain(L)
    elif refusal == "todo":
        service.create_todo(L, "real content")
    elif refusal == "projects":
        boards.create_board(L, "real content")
    elif refusal == "notes":
        notes.create(L, "real content")
    elif refusal == "sites":
        sites.publish(L, "body", title="real content")
    elif refusal == "disabled":
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET disabled_at = 'now' WHERE id = ?", (L,))
    elif refusal == "all":
        keys.create(L, "all-apps", app="all")
    else:
        keys.create(L, "empty", brains=[])
    for yes in (False, True):
        with pytest.raises(ValidationError):
            admin.merge_brain(L, target, "Moved", "moved", yes=yes)
    assert len(brain.brains(target)) == 1


def test_blended_search_demotes_each_brain_separately_and_misses_go_first(two):
    _, first, second, _ = two
    brain.write_page(first, "curator/rules", "---\ndemote: [archive]\n---")
    brain.write_page(second, "curator/rules", "---\ndemote: [other]\n---")
    one = brain.write_page(first, "archive/hit", "needle")
    two_page = brain.write_page(second, "archive/hit", "needle")
    found = brain.search([first, second], "needle")["pages"]
    assert [(p["brain_id"], p["id"]) for p in found] == [(second, two_page["id"]), (first, one["id"])]
    brain.search([second, first], "no-such-word", by="Reader")
    assert [r["brain_id"] for r in db.get_db().execute("SELECT brain_id FROM brain_misses")] == [second]


def test_ai_cap_nudge_does_not_disclose_other_brains_members(two):
    _, first, second, _ = two
    brain.remember(first, ["Personal knowledge"], by="Private AI name")
    started = brain.start(second, "Work AI", ["brain"])
    assert "read_only" in started and started["other_ais"] == []
    assert "Private AI name" not in json.dumps(started)
