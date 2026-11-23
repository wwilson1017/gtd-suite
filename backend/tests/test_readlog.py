"""The read log (readlog.py): Common Brain reads by AI tools, written only while the account's
Enhanced security switch is on, shown to the person in Settings › Security and to nobody else."""

import json
import logging

import pytest
from fastmcp.exceptions import ToolError

from backend import api_v1, apps, brain, cleanup, common, db, files, keys, lists, mcp_server, readlog
from backend.tests import test_keys, test_mcp
from backend.tests.conftest import turn_on
from backend.tests.test_files import item
from scripts import admin

pytestmark = pytest.mark.anyio

# Other suites' fixtures, under their own names: pytest looks a fixture up in the module that asks for it.
anyio_backend, app, connect, http = test_mcp.anyio_backend, test_mcp.app, test_mcp.connect, test_mcp.http
acct, multi, store = test_keys.acct, test_keys.multi, test_keys.multi_store
bearer, call, rest = test_keys.bearer, test_mcp.call, test_keys.rest
PATH = "/api/app/security/reads"

# What each Brain tool leaves in the log: (operation, kind of item), or None for a tool whose
# answer carries no existing item's content. A new Brain tool must be given a line here.
LEAVES = {
    "brain_start": ("start", None),
    "brain_search": ("search", None),
    "brain_remember": None,  # what it returns is what the caller sent
    "brain_memory_update": ("get", "memory"),
    "brain_page_list": ("list", None),
    "brain_page_get": ("get", "page"),
    "brain_page_write": ("get", "page"),
    "brain_page_append": ("get", "page"),
    "brain_page_edit": ("get", "page"),
    "brain_file_link": ("link", "file"),
    "brain_history": ("history", "page"),
    "brain_restore": ("get", "page"),
    "brain_changes": ("changes", None),
    "brain_onboard": ("start", None),
    "brain_onboard_done": None,
    "brain_curate": ("curate", None),
    "brain_forget_link": ("get", "page"),
    "brain_eval": ("get", "page"),
    "brain_export_link": None,  # a link to the app, which grants nothing
    "brain_setup": None,  # refused here: the brain is already named
}
# Words only the seeded brain holds: an answer carrying one is a read, whatever LEAVES says.
SEEDED = ("needle", "Public memory", "Allowed correction", "inbox/public")


def rows(list_id: int) -> list[dict]:
    return [dict(r) for r in db.get_db().execute("SELECT * FROM brain_reads WHERE list_id = ? ORDER BY id", (list_id,))]


def switch_on(list_id: int) -> None:
    lists.set_enhanced_security(list_id, True)


def main_link(made: dict) -> str:
    return f"http://testserver/link/{made['agent_token']}"


def put_file(store, brain_id: int, path: str, body: bytes = b"x") -> dict:
    upload = files.reserve(brain_id, [item(path, body)])["files"][0]
    assert store.put(upload["upload"], body) == 200
    return files.done(brain_id, upload["id"])


def read(list_id: int, brain_id: int, kind: str = "get", item_kind=None, item_id=None, target: str = "") -> None:
    readlog.log(list_id, [brain_id], "Claude", None, kind, item_kind, item_id, target)


def items(list_id: int) -> list[tuple]:
    return [(r["kind"], r["item_kind"], r["item_id"], r["target"]) for r in rows(list_id)]


# ── Off, and every tool ───────────────────────────────────────────────────────


async def test_with_the_switch_off_nothing_is_written(connect, http, multi, store):
    key = keys.create(multi["list_id"], "Reader", access="write", brains=[multi["first"]])["key"]
    put_file(store, multi["first"], "inbox/public.pdf")
    for mode in test_mcp.MODES:
        async with connect(main_link(multi), mode=mode) as c:
            await call(c, "brain_start")
            await call(c, "brain_page_get", path="inbox/public")
            await call(c, "brain_file_link", path="inbox/public.pdf")
    assert (await rest(http, key, "brain_search", query="needle")).status_code == 200
    assert (await http.get("/api/v1/files?path=inbox/public.pdf", headers=bearer(key))).status_code == 302
    assert (await http.get("/api/v1/export", headers=bearer(key))).status_code == 200
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_reads").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["legacy", "auto", "2026-07-28"])
async def test_initialize_discovery_and_every_brain_tool_leave_their_row(connect, multi, store, mode):
    account, first = multi["list_id"], multi["first"]
    put_file(store, first, "inbox/public.pdf")
    switch_on(account)
    args = test_keys.gate_arguments(multi)
    # A new Brain tool fails here until it says what it leaves in the log.
    assert set(LEAVES) == set(args) == {n for n, a in mcp_server._TOOL_APPS.items() if a == "brain"}
    async with connect(main_link(multi), mode=mode) as c:
        # The handshake ("legacy": initialize; "auto": server/discover) sends the locked memories.
        # On 2026-07-28 a client that already knows the server sends none.
        shook = [] if mode == "2026-07-28" else [("connect", first, None)]
        assert [(r["kind"], r["brain_id"], r["item_kind"]) for r in rows(account)] == shook
        await c.list_tools()
        assert len(rows(account)) == len(shook)  # the list of tools carries nothing of the brain
        for name, arguments in args.items():
            before = len(rows(account))
            try:
                answer = json.dumps(await call(c, name, **arguments))
            except ToolError:
                assert name == "brain_setup"
                answer = ""
            new = rows(account)[before:]
            assert [(r["kind"], r["item_kind"]) for r in new] == ([LEAVES[name]] if LEAVES[name] else []), name
            # Whatever the table above says, an answer that carries the brain's content left a row.
            assert new or not any(word in answer for word in SEEDED), name
            for r in new:
                assert (r["brain_id"], r["key_id"], r["key_kind"]) == (first, None, None), name
                assert r["by"] and (r["item_id"] is None) == (r["item_kind"] is None), name
    by_tool = {r["kind"]: r for r in rows(account)}
    assert by_tool["search"]["target"] == "needle"
    assert (by_tool["link"]["target"], by_tool["history"]["target"]) == ("inbox/public.pdf", "inbox/public")
    # Never a token, and the other brain was not touched.
    assert multi["agent_token"] not in json.dumps(rows(account))
    assert {r["brain_id"] for r in rows(account)} == {first}


async def test_a_write_tool_that_hands_back_what_is_there_leaves_a_row(connect, multi):
    account, page, memory = multi["list_id"], multi["public"]["id"], multi["memory"]["id"]
    switch_on(account)
    async with connect(main_link(multi)) as c:
        start = len(rows(account))
        versions = db.get_db().execute("SELECT COUNT(*) FROM brain_versions").fetchone()[0]
        # Nothing to change: the whole page, or the memory's text, comes back and no history is written.
        assert (await call(c, "brain_page_write", path="inbox/public"))["page"]["body"] == "Public needle"
        assert (await call(c, "brain_memory_update", id=memory))["memory"]["text"] == "Public memory"
        # Restoring the version an item already has returns the item.
        assert (await call(c, "brain_restore", kind="page", id=page, version=1))["restored"]["body"] == "Public needle"
        assert (await call(c, "brain_restore", kind="memory", id=memory, version=1))["restored"]["text"]
        assert db.get_db().execute("SELECT COUNT(*) FROM brain_versions").fetchone()[0] == versions
        assert "Public needle" in (await call(c, "brain_page_append", path="inbox/public", text="More"))["page"]["body"]
    assert items(account)[start:] == [
        ("get", "page", page, "inbox/public"),
        ("get", "memory", memory, ""),
        ("get", "page", page, "inbox/public"),
        ("get", "memory", memory, ""),
        ("get", "page", page, "inbox/public"),
    ]
    # Making a page hands back only the caller's own words: a write, not a read.
    async with connect(main_link(multi)) as c:
        start = len(rows(account))
        await call(c, "brain_page_write", path="inbox/fresh", body="Mine")
        await call(c, "brain_page_append", path="inbox/journal", text="Mine too")
    assert items(account)[start:] == []
    # The same name asking for it back is a read: the name is a claim, not proof of authorship.
    async with connect(main_link(multi)) as c:
        fresh = (await call(c, "brain_page_write", path="inbox/fresh"))["page"]["id"]
    assert items(account)[start:] == [("get", "page", fresh, "inbox/fresh")]


# ── Who read ──────────────────────────────────────────────────────────────────


async def test_a_row_names_the_link_or_key_that_read(connect, http, multi, store, monkeypatch):
    account, first = multi["list_id"], multi["first"]
    put_file(store, first, "inbox/public.pdf")
    file_id = files.listing(first)[0]["id"]
    switch_on(account)
    key = keys.create(account, "Nightly job", access="write", brains=[first], days=30)
    staff = keys.create(account, "Reception", kind="link", brains=[first], days=30)
    async with connect(main_link(multi), "auto", name="Claude") as c:
        await call(c, "brain_page_get", path="inbox/public")
    async with connect("http://testserver/mcp", "legacy", headers=bearer(key["key"])) as c:
        await call(c, "brain_page_get", path="inbox/public")
    async with connect(f"http://testserver/link/{staff['key']}", "auto") as c:
        await call(c, "brain_page_get", path="inbox/public")
    assert (await rest(http, key["key"], "brain_page_get", path="inbox/public")).status_code == 200
    got = [(r["by"], r["key_id"], r["key_kind"]) for r in rows(account) if r["kind"] == "get"]
    assert got == [
        ("Claude", None, None),
        ("Nightly job", key["id"], "key"),
        ("Reception", staff["id"], "link"),
        ("Nightly job", key["id"], "key"),
    ]
    # The handshake's row carries the same name as the calls after it.
    assert {(r["by"], r["key_kind"]) for r in rows(account) if r["kind"] == "connect"} == {
        ("Claude", None),
        ("Nightly job", "key"),
        ("Reception", "link"),
    }

    # REST's own reads run outside the tools: each is the key's, with the file it named.
    start = len(rows(account))
    assert (await http.get("/api/v1/files?path=inbox/public.pdf", headers=bearer(key["key"]))).status_code == 302
    assert (await http.get(f"/api/v1/files/{file_id}", headers=bearer(key["key"]))).status_code == 302
    assert (await http.get("/api/v1/export?since=2026-01-01", headers=bearer(key["key"]))).status_code == 200
    new = rows(account)[start:]
    assert [(r["kind"], r["item_kind"], r["item_id"], r["target"]) for r in new] == [
        ("link", "file", file_id, "inbox/public.pdf"),
        ("link", "file", file_id, "inbox/public.pdf"),
        ("export", None, None, "2026-01-01"),
    ]
    assert {(r["by"], r["key_id"], r["key_kind"], r["brain_id"]) for r in new} == {
        ("Nightly job", key["id"], "key", first)
    }
    # The log uses the brain the read used: asking again after the read (the brain archived
    # meanwhile) would refuse an export already made.
    asked = []

    def once(k, real=api_v1._brain_id):
        asked.append(k)
        if len(asked) > 2:  # _authorize asks once, the route once
            raise api_v1.Refused(403, "archived meanwhile")
        return real(k)

    with monkeypatch.context() as patch:
        patch.setattr(api_v1, "_brain_id", once)
        assert (await http.get("/api/v1/export", headers=bearer(key["key"]))).status_code == 200
    assert rows(account)[-1]["kind"] == "export"
    # A refused read is not a read.
    assert (await http.get("/api/v1/files?path=inbox/none.pdf", headers=bearer(key["key"]))).status_code == 404
    assert len(rows(account)) == start + 4
    # No key or token is kept, only which one.
    assert key["key"] not in json.dumps(rows(account)) and staff["key"] not in json.dumps(rows(account))
    shown = readlog.recent(account)
    assert (shown[0]["key_name"], shown[0]["key_kind"], shown[0]["brain"]) == ("Nightly job", "key", "Work")
    assert (shown[-1]["key_name"], shown[-1]["key_kind"], shown[-1]["by"]) == (None, None, "Claude")


async def test_a_search_across_brains_leaves_a_row_for_each(connect, multi):
    account, first, second = multi["list_id"], multi["first"], multi["second"]
    brain.set_link_brains(account, [first, second])
    switch_on(account)
    async with connect(main_link(multi), "auto") as c:
        await call(c, "brain_search", query="needle")
        await call(c, "brain_page_get", path="personal/private/unique")
        await call(c, "brain_page_list")  # the brains themselves, by name and folder
    got = [(r["kind"], r["brain_id"], r["target"]) for r in rows(account) if r["kind"] != "connect"]
    assert got == [
        ("search", first, "needle"),
        ("search", second, "needle"),
        ("get", second, "private/unique"),
        ("list", first, ""),
        ("list", second, ""),
    ]
    assert sorted(r["brain_id"] for r in rows(account) if r["kind"] == "connect") == [first, second]


async def test_a_client_called_you_is_not_logged_as_the_person(connect, multi):
    switch_on(multi["list_id"])
    async with connect(main_link(multi), "legacy", name="You") as c:
        await call(c, "brain_start")
    assert {r["by"] for r in rows(multi["list_id"])} == {brain.UNKNOWN_AI}


# ── Best effort ───────────────────────────────────────────────────────────────


async def test_a_log_that_fails_never_fails_the_read(connect, multi, caplog):
    switch_on(multi["list_id"])
    with db.transaction() as conn:
        conn.execute("DROP TABLE brain_reads")
    with caplog.at_level(logging.WARNING, logger="backend.readlog"):
        async with connect(main_link(multi)) as c:
            assert (await call(c, "brain_page_get", path="inbox/public"))["page"]["body"] == "Public needle"
    said = [r.getMessage() for r in caplog.records if r.name == "backend.readlog"]
    # The kind of failure only: no path, name or content.
    assert said and set(said) == {"a Brain read was not logged: OperationalError"}


async def test_a_read_that_finishes_after_forget_leaves_no_row(connect, multi, store, monkeypatch):
    account, first, page = multi["list_id"], multi["first"], multi["public"]["id"]
    file_id = put_file(store, first, "inbox/public.pdf")["id"]
    switch_on(account)
    real, forgets = readlog.log, []

    def paused(*args, **kwargs):
        # The person's Forget lands between the read and its row.
        forgets.pop(0)()
        real(*args, **kwargs)

    async with connect(main_link(multi)) as c:
        await call(c, "brain_search", query="needle")
        monkeypatch.setattr(readlog, "log", paused)
        forgets += [lambda: brain.forget(first, "page", page), lambda: files.forget(first, file_id)]
        assert (await call(c, "brain_page_get", path="inbox/public"))["page"]["id"] == page
        assert (await call(c, "brain_file_link", path="inbox/public.pdf"))["link"]
    assert not forgets
    assert [r["kind"] for r in rows(account)] == ["search"]
    assert "inbox/public" not in json.dumps([r for r in rows(account) if r["kind"] != "search"])


# ── Forget ────────────────────────────────────────────────────────────────────


async def test_forget_takes_the_rows_of_that_item_only(multi):
    account, first = multi["list_id"], multi["first"]
    page, memory = multi["public"]["id"], multi["memory"]["id"]
    assert page == memory  # pages and memories number separately: the id alone names neither
    switch_on(account)
    for kind in ("page", "memory"):
        read(account, first, "history", kind, page, "inbox/public" if kind == "page" else "")
        read(account, first, "get", kind, page)
    read(account, first, "search", target="public")
    brain.forget(first, "memory", memory)
    assert items(account) == [
        ("history", "page", page, "inbox/public"),
        ("get", "page", page, ""),
        ("search", None, None, "public"),
    ]
    brain.forget(first, "page", page)
    # A search's words are not scrubbed: they age out.
    assert items(account) == [("search", None, None, "public")]


async def test_forget_finds_the_rows_after_a_rename_and_after_a_move_to_another_brain(multi):
    account, first, second = multi["list_id"], multi["first"], multi["second"]
    page, memory = multi["public"]["id"], multi["memory"]["id"]
    switch_on(account)
    read(account, first, "get", "page", page, "inbox/public")
    brain.write_page(first, "inbox/public", move_to="archive/renamed")
    read(account, first, "get", "page", page, "archive/renamed")
    read(account, first, "get", "memory", memory)
    read(account, first, "history", "memory", memory)
    with db.transaction() as conn:
        brain.move_to_brain_in(conn, "page", page, second, None, brain.YOU, None)
        brain.move_to_brain_in(conn, "memory", memory, second, None, brain.YOU, None)
    read(account, second, "get", "page", page, "archive/renamed")
    # The rows keep the brain they were read in; Forget, in the brain the item is in now, takes them all.
    assert [r["brain_id"] for r in rows(account)] == [first, first, first, first, second]
    brain.forget(second, "page", page)
    assert items(account) == [("get", "memory", memory, ""), ("history", "memory", memory, "")]
    brain.forget(second, "memory", memory)
    assert rows(account) == []


async def test_forgetting_a_file_takes_the_rows_of_every_version(multi, store):
    account, first = multi["list_id"], multi["first"]
    switch_on(account)
    old = put_file(store, first, "inbox/scan.pdf", b"one")["id"]
    read(account, first, "link", "file", old, "inbox/scan.pdf")
    new = put_file(store, first, "inbox/scan.pdf", b"two")["id"]
    other = put_file(store, first, "inbox/other.pdf")["id"]
    for file_id, path in ((new, "inbox/scan.pdf"), (old, "inbox/scan.pdf"), (other, "inbox/other.pdf")):
        read(account, first, "link", "file", file_id, path)
    assert old != new and len(rows(account)) == 4
    files.forget(first, new)
    assert items(account) == [("link", "file", other, "inbox/other.pdf")]
    # A forgotten file is a tombstone until the sweeper deletes it: no row can name it again.
    read(account, first, "link", "file", new, "inbox/scan.pdf")
    read(account, first, "link", "file", 10**9, "inbox/never.pdf")
    assert len(rows(account)) == 1


# ── Ninety days, and the person's page ────────────────────────────────────────


async def test_rows_show_for_ninety_days_and_then_go(multi, freeze):
    account, first = multi["list_id"], multi["first"]
    switch_on(account)
    freeze("2026-01-01T00:00:00")
    read(account, first, "start")
    freeze("2026-01-02T00:00:00")
    read(account, first, "changes")
    # Turning the switch off stops new rows and keeps the old ones until they are 90 days old.
    lists.set_enhanced_security(account, False)
    read(account, first, "curate")
    assert [r["kind"] for r in readlog.recent(account)] == ["changes", "start"]
    now = freeze("2026-04-01T00:00:00")  # 90 days after the first
    # Before the daily sweep has run, the page already leaves the old row out.
    assert [r["kind"] for r in readlog.recent(account)] == ["changes"] and len(rows(account)) == 2
    assert readlog.expire(now) == 1 and [r["kind"] for r in rows(account)] == ["changes"]
    assert readlog.expire(now) == 0


def test_the_log_is_the_signed_in_browsers_own_a_page_at_a_time(client, new_list):
    assert client.get(PATH).status_code == 401
    mine, theirs = new_list(), new_list()
    c, account = mine["client"], mine["list_id"]
    turn_on(account, "brain")
    first = brain.first_brain(account)
    switch_on(account)
    for n in range(readlog.PAGE + 5):
        read(account, first, "search", target=f"words {n}")
    response = c.get(PATH)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    page = response.json()["reads"]
    assert len(page) == readlog.PAGE and page[0]["target"] == f"words {readlog.PAGE + 4}"
    assert set(page[0]) == {"id", "at", "by", "kind", "item_kind", "target", "brain", "key_kind", "key_name"}
    older = c.get(PATH, params={"before": page[-1]["id"]}).json()["reads"]
    assert [r["target"] for r in older] == [f"words {n}" for n in range(4, -1, -1)]
    assert c.get(PATH, params={"before": older[-1]["id"]}).json() == {"reads": []}
    assert c.get(PATH, headers={"X-List": str(theirs["list_id"])}).status_code == 409
    assert theirs["client"].get(PATH).json() == {"reads": []}


async def test_no_ai_tool_or_key_reads_the_log(connect, http, multi):
    switch_on(multi["list_id"])
    key = keys.create(multi["list_id"], "Reader", app="all", brains=[multi["first"]], days=30)["key"]
    async with connect(main_link(multi)) as c:
        names = {t.name for t in await c.list_tools()}
    assert not [n for n in names if "read_log" in n or "reads" in n or "security" in n]
    assert (await http.get(PATH, headers=bearer(key))).status_code == 401  # the browser's session only
    assert (await http.get("/api/v1/security/reads", headers=bearer(key))).status_code == 404


# ── Bookkeeping, not content ──────────────────────────────────────────────────


def test_the_log_is_not_content_and_goes_with_its_list(todo_db):
    assert "brain_reads" not in apps.content_tables()
    # Before `brains`, which its rows point at.
    assert admin._LIST_TABLES.index("brain_reads") < admin._LIST_TABLES.index("brains")
    unused, deleted, kept = (lists.create_list("UTC")["list_id"] for _ in range(3))
    for list_id in (unused, deleted, kept):
        turn_on(list_id, "brain")
        switch_on(list_id)
        read(list_id, brain.first_brain(list_id), "connect")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = '2020-01-01T00:00:00.000Z' WHERE id IN (?, ?)", (unused, kept))
    brain.remember(brain.first_brain(kept), ["Kept"])
    # An AI that connected and read nothing does not make a list look used.
    assert cleanup.delete_unused_lists() == 1 and lists.get_list(unused) is None
    assert admin.main(["delete", str(deleted), f"--yes-delete-list-{deleted}", "--no-snapshot"]) == 0
    assert [r[0] for r in db.get_db().execute("SELECT list_id FROM brain_reads")] == [kept]


def test_a_version_that_does_not_know_the_table_can_still_delete_a_list(todo_db, monkeypatch):
    # After a rollback the older code deletes a list without this table in its own list of them.
    monkeypatch.setattr(admin, "_LIST_TABLES", tuple(t for t in admin._LIST_TABLES if t != "brain_reads"))
    gone = lists.create_list("UTC")["list_id"]
    turn_on(gone, "brain")
    switch_on(gone)
    read(gone, brain.first_brain(gone), "connect")
    assert len(rows(gone)) == 1
    assert admin.main(["delete", str(gone), f"--yes-delete-list-{gone}", "--no-snapshot"]) == 0
    assert lists.get_list(gone) is None and rows(gone) == []


def test_merging_a_brain_moves_its_rows(L, monkeypatch):
    turn_on(L, "brain")
    switch_on(L)
    page = brain.write_page(brain.first_brain(L), "inbox/moved", "x")["id"]
    read(L, brain.first_brain(L), "get", "page", page, "inbox/moved")
    target = lists.create_list("UTC")["list_id"]
    monkeypatch.setattr(common, "brains_cap_for", lambda *_: 2)  # room for the brain that moves in
    moved = admin.merge_brain(L, target, "Moved", "moved", yes=True)["to_brain"]
    assert rows(L) == [] and [(r["brain_id"], r["item_id"]) for r in rows(target)] == [(moved, page)]
    # Forget in the new account still finds them.
    brain.forget(moved, "page", page)
    assert rows(target) == []


def test_the_table_is_made_once_and_left_alone(L):
    turn_on(L, "brain")
    switch_on(L)
    read(L, brain.first_brain(L), "start")
    db.init_db()
    assert [r["kind"] for r in rows(L)] == ["start"]
    assert common.to_iso(common.utcnow()) >= rows(L)[0]["at"]
