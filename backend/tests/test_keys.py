"""Program keys (keys.py): made in the browser, used as a Bearer on /mcp and on the REST
API (api_v1.py), scoped by app, access and folders, and kept off confidential pages."""

import pytest
from fastmcp.exceptions import ToolError

from backend import api_v1, brain, db, keys, lists, mcp_server, ratelimit
from backend.common import NotFoundError, ValidationError
from backend.tests.conftest import confirm_list, only, turn_on
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    MCP_HEADERS,
    anyio_backend,
    app,
    call,
    connect,
    http,
)

BRAIN_URL = "https://brain.example"
SECRET = "---\nconfidential: true\n---\n# Pay plan\n\nThe raises for next year."


@pytest.fixture()
def acct(app, monkeypatch):
    """An account with Todo and Brain on and a confirmed email (so several AIs may write)."""
    monkeypatch.setenv("BRAIN_BASE_URL", BRAIN_URL)
    made = lists.create_list("UTC")
    only(made["list_id"], "todo", "brain")
    confirm_list(made["list_id"])
    return made


def new_key(list_id: int, name="example-agents", app="brain", access="write", folders=None) -> str:
    return keys.create(list_id, name, app, access, folders)["key"]


def bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def by_key(connect, key: str):
    return connect("http://testserver/mcp", headers=bearer(key))


async def rest(http, key: str, tool: str, **args):
    return await http.post(f"/api/v1/tools/{tool}", json=args, headers=bearer(key))


# ── Making, showing and revoking ──────────────────────────────────────────────


def test_a_key_is_shown_once_stored_hashed_and_revoked_not_deleted(client, new_list):
    made = new_list()
    c, list_id = made["client"], made["list_id"]
    res = c.post("/api/app/keys", json={"name": "vm-jobs", "access": "write"})
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    key = res.json()["key"]
    assert key.startswith("cb_") and len(key) == 46 and res.json()["last4"] == key[-4:]
    listed = c.get("/api/app/keys").json()["keys"]
    assert [(k["name"], k["apps"], k["access"], k["folders"]) for k in listed] == [("vm-jobs", "brain", "write", [])]
    assert "key" not in listed[0] and key not in str(listed)
    row = db.get_db().execute("SELECT * FROM api_keys").fetchone()
    assert row["key_hash"] == lists.hash_token(key) and key not in str(dict(row))
    assert keys.resolve(key)["list_id"] == list_id

    assert c.post(f"/api/app/keys/{listed[0]['id']}/revoke").json() == {"ok": True}
    assert keys.resolve(key) is None and c.get("/api/app/keys").json()["keys"] == []
    assert db.get_db().execute("SELECT revoked_at FROM api_keys").fetchone()[0]  # still there
    assert c.post(f"/api/app/keys/{listed[0]['id']}/revoke").status_code == 404
    # The name is free again once its key is revoked.
    assert c.post("/api/app/keys", json={"name": "VM-jobs"}).status_code == 200


def test_browser_staff_link_has_full_url_only_when_created(client, new_list, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    made = new_list()
    c = made["client"]
    res = c.post("/api/app/keys", json={"name": "Staff", "kind": "link"})
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    row = res.json()
    assert row["link"] == f"https://todo.example/link/{row['key']}"
    listed = c.get("/api/app/keys").json()["keys"]
    assert "link" not in listed[0] and "key" not in listed[0]
    assert row["key"] not in str(listed)


def test_the_key_routes_are_the_signed_in_browsers_own(client, new_list):
    mine, theirs = new_list(), new_list()
    k = mine["client"].post("/api/app/keys", json={"name": "a"}).json()
    assert theirs["client"].post(f"/api/app/keys/{k['id']}/revoke").status_code == 404
    assert theirs["client"].get("/api/app/keys").json()["keys"] == []
    cross = mine["client"].post("/api/app/keys", json={"name": "b"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    client.cookies.clear()
    assert client.get("/api/app/keys").status_code == 401


@pytest.mark.parametrize("name", ["you", "You", " YOU ", "y o u", "Y\tou"])
def test_a_key_cannot_be_called_you(L, name):
    with pytest.raises(ValidationError, match="that is you"):
        keys.create(L, name)


def test_a_keys_shape_is_checked(L):
    for kwargs, why in (
        ({"name": ""}, "needs a name"),
        ({"name": "x" * 61}, "needs a name"),
        ({"name": "a", "app": "todo"}, "apps must"),
        ({"name": "a", "access": "admin"}, "access must"),
        ({"name": "a", "app": "all", "folders": ["acme"]}, "Brain only"),
        ({"name": "a", "folders": ["Bad Path!"]}, "Invalid page path"),
    ):
        with pytest.raises(ValidationError, match=why):
            keys.create(L, **kwargs)
    keys.create(L, "dup")
    with pytest.raises(ValidationError, match="already a key"):
        keys.create(L, "DUP")
    assert keys.create(L, "f", folders=["ACME/Inbox/", "acme/inbox"])["folders"] == ["acme/inbox"]


def test_a_new_key_defaults_to_an_active_brain(L):
    oldest = brain.first_brain(L)
    with db.transaction() as conn:  # past the free cap of one brain, as test_brains.add_brain does
        second = conn.execute(
            "INSERT INTO brains (list_id, folder, created_at, updated_at) VALUES (?, 'second', '', '')", (L,)
        ).lastrowid
    brain.brain_status(L, oldest, "archived")
    assert keys.create(L, "after")["brains"] == [second]


def test_an_account_holds_twenty_live_keys(L):
    made = [keys.create(L, f"k{i}") for i in range(keys.MAX_PER_LIST)]
    with pytest.raises(ValidationError, match="at most 20"):
        keys.create(L, "one more")
    keys.revoke(L, made[0]["id"])
    keys.create(L, "one more")


def test_a_disabled_or_removed_list_refuses_its_keys(L, monkeypatch, freeze):
    key = new_key(L)
    assert keys.resolve(key)
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = '2026-01-01' WHERE id = ?", (L,))
    assert keys.resolve(key) is None


def test_the_self_host_reset_revokes_every_key(L):
    """The operator taking the deployment back replaces every way in, keys included."""
    key = new_key(L)
    assert lists.reset_single() and keys.resolve(key) is None and keys.list_keys(L) == []


def test_using_a_key_stamps_it_hourly_and_touches_the_list(L, freeze):
    key = new_key(L)
    freeze("2026-10-30T10:00:00")
    keys.resolve(key)
    stamp = lambda: (
        db.get_db()
        .execute(  # noqa: E731
            "SELECT k.last_used_at, l.last_used_at FROM api_keys k JOIN lists l ON l.id = k.list_id"
        )
        .fetchone()
    )
    assert tuple(stamp()) == ("2026-10-30T10:00:00.000Z",) * 2
    freeze("2026-10-30T10:30:00")
    keys.resolve(key)
    assert stamp()[0] == "2026-10-30T10:00:00.000Z"
    freeze("2026-10-30T11:01:00")
    keys.resolve(key)
    assert stamp()[0] == "2026-10-30T11:01:00.000Z"


def test_admin_delete_and_cleanup_take_a_lists_keys_with_it(todo_db):
    from backend import cleanup
    from scripts import admin

    gone, kept = (lists.create_list("UTC")["list_id"] for _ in range(2))
    new_key(gone)
    new_key(kept)
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = '2020-01-01T00:00:00.000Z' WHERE id = ?", (gone,))
    assert "api_keys" in admin._LIST_TABLES
    assert cleanup.delete_unused_lists() == 1
    assert [r[0] for r in db.get_db().execute("SELECT list_id FROM api_keys")] == [kept]


# ── On /mcp ───────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_a_brain_key_on_mcp_lists_only_the_brain_tools(connect, acct):
    async with by_key(connect, new_key(acct["list_id"])) as c:
        names = {t.name for t in await c.list_tools()}
        assert names == {n for n, a in mcp_server._TOOL_APPS.items() if a == "brain" and n != "brain_setup"}
        with pytest.raises(ToolError, match="Common Brain only"):
            await call(c, "todo_create", title="x")
    async with by_key(connect, new_key(acct["list_id"], "all", app="all")) as c:
        assert "todo_create" in {t.name for t in await c.list_tools()}


@pytest.mark.anyio
async def test_a_read_key_cannot_see_or_call_a_write_tool(connect, acct):
    async with by_key(connect, new_key(acct["list_id"], access="read")) as c:
        names = {t.name for t in await c.list_tools()}
        assert "brain_search" in names and "brain_page_write" not in names
        assert all(mcp_server._TOOL_READONLY[n] for n in names)
        with pytest.raises(ToolError, match="only reads"):
            await call(c, "brain_page_write", path="inbox/x", body="hi")
    assert brain.pages(brain.first_brain(acct["list_id"])) == []


@pytest.mark.anyio
async def test_a_key_only_works_as_the_bearer(http, acct):
    key = new_key(acct["list_id"])
    ok = await http.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={**MCP_HEADERS, **bearer(key)}
    )
    assert ok.status_code == 200
    for path in (f"/mcp/{key}", f"/link/{key}", f"/{key}/mcp"):
        res = await http.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=MCP_HEADERS)
        assert res.status_code == 404 and "www-authenticate" not in res.headers, path
    # A key skips Agent Commands: a plain GET is MCP's, not the guide.
    guide = await http.get("/mcp", headers=bearer(key))
    assert guide.status_code != 200 or "Agent Commands" not in guide.text
    keys.revoke(acct["list_id"], keys.list_keys(acct["list_id"])[0]["id"])
    res = await http.post("/mcp", json={}, headers={**MCP_HEADERS, **bearer(key)})
    assert res.status_code == 401 and res.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_an_old_agent_token_that_looks_like_a_key_still_works(http, acct):
    # Tokens minted before 2026-10-12 were urlsafe, so one can start with the key prefix.
    old = "cb_" + lists.mint_token()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET agent_token = ?, agent_token_hash = ? WHERE id = ?",
            (old, lists.hash_token(old), acct["list_id"]),
        )
    listing = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    for path, headers in ((f"/mcp/{old}", MCP_HEADERS), ("/mcp", {**MCP_HEADERS, **bearer(old)})):
        assert (await http.post(path, json=listing, headers=headers)).status_code == 200, path


@pytest.mark.anyio
async def test_a_keys_name_labels_its_writes_and_grants_nothing(connect, acct):
    list_id = acct["list_id"]
    m = brain.remember(brain.first_brain(list_id), ["Call me Will"])["added"][0]
    brain.update_memory(brain.first_brain(list_id), m["id"], locked=True)
    # A name that slipped past the check (made before it, say) still is not the person.
    for name in ("you-bot", "you"):
        key = new_key(list_id, "placeholder-" + name)
        with db.transaction() as conn:
            conn.execute("UPDATE api_keys SET name = ? WHERE key_hash = ?", (name, lists.hash_token(key)))
        async with by_key(connect, key) as c:
            with pytest.raises(ToolError, match="locked"):
                await call(c, "brain_memory_update", id=m["id"], text="Call me Bill")
            page = (await call(c, "brain_page_write", path=f"inbox/{name}", body="hello"))["page"]
            assert page["updated_by"] == (brain.UNKNOWN_AI if name == "you" else name)
    assert brain.get_memory(brain.first_brain(list_id), m["id"])["text"] == "Call me Will"


# ── Folder-limited keys ───────────────────────────────────────────────────────


@pytest.fixture()
def acme(acct):
    """The ACME shape: an inbox key, a confidential note, and an ordinary page."""
    list_id = acct["list_id"]
    secret = brain.write_page(brain.first_brain(list_id), "acme/hr/pay", SECRET)
    brain.write_page(brain.first_brain(list_id), "acme/now", "# Now\n\nShip the holiday menu.")
    return {"list_id": list_id, "key": new_key(list_id, folders=["acme/inbox"]), "secret": secret}


@pytest.mark.anyio
async def test_a_folder_key_writes_pages_only_inside_its_folders(connect, acme):
    async with by_key(connect, acme["key"]) as c:
        made = await call(c, "brain_page_write", path="acme/inbox/order-123", body="A note")
        assert made["page"]["updated_by"] == "example-agents"
        await call(c, "brain_page_append", path="acme/inbox/order-123", text="More")
        for tool, args in (
            ("brain_page_write", {"path": "acme/now", "body": "x"}),
            ("brain_page_write", {"path": "acme/inbox/order-123", "move_to": "acme/x"}),
            ("brain_page_write", {"path": "acme/inboxer/x", "body": "x"}),
            ("brain_page_append", {"path": "acme/now", "text": "x"}),
            ("brain_page_edit", {"path": "acme/now", "old_str": "Ship", "new_str": "Sell"}),
        ):
            with pytest.raises(ToolError, match="only inside acme/inbox/"):
                await call(c, tool, **args)
        for tool, args in (
            ("brain_remember", {"memories": ["x"]}),
            ("brain_memory_update", {"id": 1, "text": "x"}),
            ("brain_restore", {"kind": "page", "id": acme["secret"]["id"], "version": 1}),
            ("brain_history", {"kind": "page", "id": acme["secret"]["id"]}),
            ("brain_changes", {}),
            ("brain_curate", {}),
            ("brain_onboard", {}),
            ("brain_forget_link", {"kind": "page", "id": acme["secret"]["id"]}),
        ):
            with pytest.raises(ToolError, match="limited to folders"):
                await call(c, tool, **args)
        listed = {t.name for t in await c.list_tools()}
        assert listed == mcp_server.FOLDER_KEY_TOOLS
    assert brain.get_page(brain.first_brain(acme["list_id"]), path="acme/now")["body"].endswith("holiday menu.")


@pytest.mark.anyio
async def test_a_folder_keys_page_tools_refuse_a_confidential_page_inside_its_folder(connect, acme):
    """The tools pass `restricted` through: a confidential page in the key's own folder is
    neither read, rewritten (which would strip its flag), appended to nor edited."""
    hidden = brain.write_page(brain.first_brain(acme["list_id"]), "acme/inbox/hr-note", SECRET)
    async with by_key(connect, acme["key"]) as c:
        for tool, args in (
            ("brain_page_get", {}),
            ("brain_page_write", {}),
            ("brain_page_write", {"body": "# Pay"}),
            ("brain_page_append", {"text": "more"}),
            ("brain_page_edit", {"old_str": "raises", "new_str": "cuts"}),
        ):
            with pytest.raises(ToolError, match="Page not found"):
                await call(c, tool, path="acme/inbox/hr-note", **args)
        with pytest.raises(ToolError, match="Page not found"):
            await call(c, "brain_page_write", path="acme/inbox/order-123", body="x", move_to="acme/inbox/hr-note")
    assert brain.get_page(brain.first_brain(acme["list_id"]), hidden["id"])["version"] == 1


@pytest.mark.anyio
async def test_a_folder_key_never_sees_a_confidential_page(connect, acme):
    list_id = acme["list_id"]
    async with by_key(connect, acme["key"]) as c:
        found = await call(c, "brain_search", query="raises")
        assert found["pages"] == [] and "miss" in found
        assert [p["path"] for p in (await call(c, "brain_search", query="holiday"))["pages"]] == ["acme/now"]
        listed = await call(c, "brain_page_list")
        assert [p["path"] for p in listed["pages"]] == ["acme/now"]
        assert "acme/hr" not in {f["folder"] for f in listed["folders"]}
        with pytest.raises(ToolError, match="Page not found"):
            await call(c, "brain_page_get", path="acme/hr/pay")
        started = await call(c, "brain_start")
        assert [p["path"] for p in started["pages"]["recent"]] == ["acme/now"]
        assert started["pages"]["count"] == 1 and "since_you_were_last_here" not in started
        # A second visit has no catch-up either: it reads old versions.
        brain.write_page(brain.first_brain(list_id), "acme/hr/pay", SECRET + "\nMore.")
        assert "since_you_were_last_here" not in await call(c, "brain_start")

        # Flipping a page to confidential hides it at once.
        brain.write_page(brain.first_brain(list_id), "acme/now", "---\nconfidential: yes\n---\n# Now")
        assert (await call(c, "brain_page_list"))["pages"] == []
        with pytest.raises(ToolError, match="Page not found"):
            await call(c, "brain_page_get", path="acme/now")
    # The agent link, and an unlimited key, still see everything.
    async with by_key(connect, new_key(list_id, "curator")) as c:
        assert len((await call(c, "brain_page_list"))["pages"]) == 2


@pytest.mark.anyio
async def test_a_restricted_write_refuses_a_confidential_page_as_not_found(acme):
    list_id, secret = acme["list_id"], acme["secret"]
    brain.write_page(brain.first_brain(list_id), "acme/inbox/open", "# Open")
    for write in (
        lambda: brain.write_page(brain.first_brain(list_id), "acme/hr/pay", None, restricted=True),  # a no-op read
        lambda: brain.write_page(brain.first_brain(list_id), "acme/hr/pay", "# Pay", restricted=True),  # strip the flag
        lambda: brain.write_page(
            brain.first_brain(list_id), "acme/inbox/open", None, move_to="acme/hr/pay", restricted=True
        ),
        lambda: brain.append_page(brain.first_brain(list_id), "acme/hr/pay", "x", restricted=True),
        lambda: brain.edit_page(brain.first_brain(list_id), "acme/hr/pay", "raises", "cuts", restricted=True),
    ):
        with pytest.raises(NotFoundError, match="Page not found"):
            write()
    assert brain.get_page(brain.first_brain(list_id), secret["id"])["version"] == 1


# ── The confidential flag ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body, flag",
    [
        (SECRET, True),
        ("---\nConfidential: YES\n---\n", True),
        ("---\r\nconfidential: true\r\n---\r\n", True),
        ('---\nconfidential: "true"\n---\n', True),
        ("---\nconfidential: yes # HR only\n---\n", True),
        ("\ufeff---\nconfidential: true\n---\n", True),
        ("\n\n---\nconfidential: true\n---\n", True),
        ("---\nconfidential: false\n---\n", False),
        ("---\nconfidential: maybe\n---\n", False),
        ("# Title\n---\nconfidential: true\n---\n", False),
        ("confidential: true", False),
        ("", False),
    ],
)
def test_the_flag_follows_the_frontmatter(body, flag):
    assert brain.confidential(body) is flag


def test_frontmatter_values_are_strings_booleans_and_lists():
    assert brain._front(
        "---\ntags: [a, b]\nrequired:\n  - summary\n  - owner\nsummary: UNKNOWN: who\n"
        "archived: no\nnested:\n  key: x\n---\nbody"
    ) == {
        "tags": ["a", "b"],
        "required": ["summary", "owner"],
        "summary": "UNKNOWN: who",
        "archived": False,
        "nested": "",
    }


def test_every_write_sets_the_flag_and_an_old_database_is_backfilled(L, tmp_path):
    page = brain.write_page(brain.first_brain(L), "hr/pay", SECRET)
    assert page["confidential"] == 1
    assert brain.write_page(brain.first_brain(L), "hr/pay", "# Pay")["confidential"] == 0
    assert brain.restore(brain.first_brain(L), "page", page["id"], 1)["confidential"] == 1
    # A database from before the column: it is added and each page's flag read from its body.
    conn = db.get_db()
    with db.transaction() as tx:
        tx.execute("ALTER TABLE brain_pages DROP COLUMN confidential")
    db._migrate(conn)
    assert conn.execute("SELECT confidential FROM brain_pages WHERE id = ?", (page["id"],)).fetchone()[0] == 1


# ── REST ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_rest_round_trip(http, acct):
    key = new_key(acct["list_id"], "vm-jobs", app="all", access="write")
    about = await http.get("/api/v1", headers=bearer(key))
    assert about.status_code == 200 and about.headers["cache-control"] == "no-store"
    body = about.json()
    assert body["key"] == {"name": "vm-jobs", "apps": "all", "access": "write", "folders": []}
    assert body["apps_on"] == ["todo", "brain"] and "account_no" in body
    tools = {t["name"]: t for t in body["tools"]}
    assert tools["brain_page_write"]["read_only"] is False and tools["brain_search"]["read_only"]
    assert tools["brain_page_write"]["input_schema"]["required"] == ["path"]

    res = await rest(http, key, "brain_page_write", path="inbox/hello", body="# Hello")
    assert res.status_code == 200 and res.json()["page"]["updated_by"] == "vm-jobs"
    assert (await rest(http, key, "todo_create", title="Ring the bakery")).json()["todo"]["source_client"] == "vm-jobs"
    found = (await rest(http, key, "brain_search", query="hello")).json()
    assert [p["path"] for p in found["pages"]] == ["inbox/hello"]


@pytest.mark.anyio
async def test_rest_decides_its_status_before_the_call(http, acct):
    list_id = acct["list_id"]
    read, brain_only = new_key(list_id, "r", access="read"), new_key(list_id, "b")
    folder = new_key(list_id, "f", folders=["inbox"])
    assert (await rest(http, read, "nope")).status_code == 404
    for key, tool in ((read, "brain_page_write"), (brain_only, "todo_create"), (folder, "brain_history")):
        res = await rest(http, key, tool, path="inbox/x", body="x", title="x", kind="page", id=1)
        assert res.status_code == 403 and res.json()["error"], tool
    bad = await rest(http, brain_only, "brain_page_get", path="nowhere/at-all")
    assert bad.status_code == 400 and "Page not found" in bad.json()["error"]
    wrong = await rest(http, brain_only, "brain_search")  # query is required
    assert wrong.status_code == 400 and "query" in wrong.json()["error"]
    for body in (b"[1]", b"{not json"):
        res = await http.post("/api/v1/tools/brain_search", content=body, headers=bearer(brain_only))
        assert res.status_code == 400 and "JSON object" in res.json()["error"]
    big = await http.post(
        "/api/v1/tools/brain_search",
        headers=bearer(brain_only),
        content=b"{" + b" " * (mcp_server._MAX_BODY_BYTES + 1) + b"}",
    )
    assert big.status_code == 413


@pytest.mark.anyio
async def test_a_bad_key_is_a_403_and_charged_to_the_address(http, acct):
    good = new_key(acct["list_id"])
    for headers in ({}, bearer("cb_" + "x" * 43), bearer(acct["agent_token"]), {"Authorization": f"Basic {good}"}):
        res = await http.get("/api/v1", headers=headers)
        assert res.status_code == 403 and res.json() == {"error": "unknown or revoked key"}
        assert "www-authenticate" not in res.headers
    for _ in range(60):
        await http.get("/api/v1", headers=bearer("cb_wrong"))
    res = await http.get("/api/v1", headers=bearer("cb_wrong"))
    assert res.status_code == 429 and res.headers["retry-after"] == "600"
    # A valid key is always served, however many misses its address made.
    assert (await http.get("/api/v1", headers=bearer(good))).status_code == 200
    assert (await http.get("/api/v1")).status_code == 403  # no key at all is not a guess


@pytest.mark.anyio
async def test_rest_shares_the_accounts_call_budget(http, acct, monkeypatch):
    monkeypatch.setattr(mcp_server.call_limiter, "max_hits", 3)
    key = new_key(acct["list_id"])
    assert [(await http.get("/api/v1", headers=bearer(key))).status_code for _ in range(4)] == [200, 200, 200, 429]
    ratelimit.clear_all()


# The routes of their own that later PRs add (files, import, export) all pass _authorize.
MATRIX = [  # key shape, need, path, open_folders, allowed
    ({"access": "read"}, "read", "inbox/x", False, True),
    ({"access": "read"}, "write", "inbox/x", False, False),
    ({"access": "write"}, "write", "inbox/x", False, True),
    ({"access": "write", "folders": ["inbox"]}, "write", "inbox/x", False, True),
    ({"access": "write", "folders": ["inbox"]}, "write", "acme/x", False, False),
    ({"access": "write", "folders": ["inbox"]}, "read", "inbox/x", True, False),
    ({"access": "write", "folders": ["inbox"]}, "read", None, False, False),
    ({"access": "write", "app": "all"}, "write", "inbox/x", True, True),
]


@pytest.mark.anyio
@pytest.mark.parametrize("shape, need, path, open_folders, allowed", MATRIX)
async def test_authorize_matrix(acct, shape, need, path, open_folders, allowed):
    from starlette.requests import Request

    key = new_key(acct["list_id"], **shape)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1",
            "query_string": b"",
            "client": ("1.2.3.4", 1),
            "headers": [(b"authorization", f"Bearer {key}".encode())],
        }
    )
    if allowed:
        assert (await api_v1._authorize(request, need, path, open_folders))["list_id"] == acct["list_id"]
    else:
        with pytest.raises(api_v1.Refused) as refused:
            await api_v1._authorize(request, need, path, open_folders)
        assert refused.value.status == 403


@pytest.mark.anyio
async def test_authorize_refuses_brain_off_and_reaches_only_the_keys_own_account(http, acct, monkeypatch):
    other = lists.create_list("UTC")["list_id"]
    turn_on(other, "brain")
    theirs = brain.write_page(brain.first_brain(other), "inbox/theirs", "Not yours")
    key = new_key(acct["list_id"], app="all")
    res = await rest(http, key, "brain_history", kind="page", id=theirs["id"])
    assert res.status_code == 400 and "not found" in res.json()["error"].lower()
    monkeypatch.delenv("BRAIN_BASE_URL")  # Brain is still served at its path.
    assert "brain" in lists.apps_on(acct["list_id"])
    with db.transaction() as conn:
        lists.set_app_in(conn, acct["list_id"], "brain", False)
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1",
            "query_string": b"",
            "client": ("1.2.3.4", 1),
            "headers": [(b"authorization", f"Bearer {key}".encode())],
        }
    )
    with pytest.raises(api_v1.Refused, match="off for this account"):
        await api_v1._authorize(request, "read", "inbox/x")
    assert (await rest(http, key, "brain_search", query="x")).status_code == 403


def test_a_key_never_reaches_a_log_line(caplog):
    import logging
    from backend import logscrub

    key = "cb_" + lists.mint_token()
    record = logging.LogRecord("x", logging.WARNING, "", 0, "refused %s at /mcp/%s, /%s/mcp", (key, key, key), None)
    logscrub.ScrubTokens().filter(record)
    assert key not in record.getMessage() and key[3:13] not in record.getMessage()


@pytest.fixture()
def multi(acct):
    from backend.tests.test_brains import add_brain

    account = acct["list_id"]
    first = brain.first_brain(account)
    brain.update_brain(account, first, name="Work", rules=["Work only"])
    second = add_brain(account, "personal")
    public = brain.write_page(first, "inbox/public", "Public needle")
    brain.write_page(first, "curator/golden", "- probe: public => inbox/public")
    memory = brain.remember(first, ["Public memory"])["added"][0]
    hidden = brain.write_page(second, "private/unique", "PRIVATE_SENTINEL needle")
    hidden_memory = brain.remember(second, ["PRIVATE_SENTINEL memory"])["added"][0]
    brain.update_memory(second, hidden_memory["id"], locked=True)
    return {
        **acct,
        "first": first,
        "second": second,
        "public": public,
        "memory": memory,
        "hidden": hidden,
        "hidden_memory": hidden_memory,
    }


@pytest.fixture()
def multi_store(monkeypatch):
    from backend import objectstore
    from backend.tests.test_files import CFG, FakeStore

    for name, value in CFG.items():
        monkeypatch.setenv(f"FILES_S3_{name}", value)
    fake = FakeStore()
    monkeypatch.setattr(objectstore.httpx, "request", fake.request)
    return fake


def gate_arguments(multi):
    return {
        "brain_start": {},
        "brain_search": {"query": "needle"},
        "brain_remember": {"memories": ["Allowed memory"]},
        "brain_memory_update": {"id": multi["memory"]["id"], "text": "Allowed correction"},
        "brain_page_list": {},
        "brain_page_get": {"path": "inbox/public"},
        "brain_page_write": {"path": "inbox/public", "body": "Public needle revised"},
        "brain_page_append": {"path": "inbox/public", "text": "Extra"},
        "brain_page_edit": {"path": "inbox/public", "old_str": "Extra", "new_str": "Edited"},
        "brain_file_link": {"path": "inbox/public.pdf"},
        "brain_history": {"kind": "page", "id": multi["public"]["id"]},
        "brain_restore": {"kind": "page", "id": multi["public"]["id"], "version": 1},
        "brain_changes": {},
        "brain_onboard": {},
        "brain_onboard_done": {},
        "brain_curate": {},
        "brain_forget_link": {"kind": "page", "id": multi["public"]["id"]},
        "brain_eval": {},
        "brain_export_link": {},
        "brain_setup": {"name": "Work", "description": "Work only", "rules": ["Work only"]},
    }


@pytest.mark.anyio
@pytest.mark.parametrize("credential", ["main", "link", "key", "rest", "folder"])
async def test_every_brain_tool_obeys_the_grant(connect, http, multi, multi_store, credential):
    import contextlib
    import json
    from backend import files
    from backend.tests.test_files import item
    from backend.tests.test_mcp import INIT

    first, second = multi["first"], multi["second"]
    for bid, path in ((first, "inbox/public.pdf"), (second, "private/hidden.pdf")):
        upload = files.reserve(bid, [item(path, b"x")])["files"][0]
        multi_store.put(upload["upload"], b"x")
        files.done(bid, upload["id"])
    secret = brain.write_page(first, "inbox/confidential", SECRET)
    before = {
        t: [dict(r) for r in db.get_db().execute(f"SELECT * FROM {t} WHERE brain_id = ?", (second,))]
        for t in ("brain_pages", "brain_memories", "brain_versions", "brain_files")
    }
    grant = None
    if credential == "main":
        url, headers = f"http://testserver/link/{multi['agent_token']}", {}
    else:
        grant = keys.create(
            multi["list_id"],
            "Staff",
            kind="link" if credential == "link" else "key",
            access="write",
            brains=[first],
            folders=["inbox"] if credential == "folder" else None,
        )
        url = f"http://testserver/link/{grant['key']}" if credential == "link" else "http://testserver/mcp"
        headers = {} if credential == "link" else bearer(grant["key"])
    initialized = await http.post(url, json=INIT, headers={**MCP_HEADERS, **headers})
    assert initialized.status_code == 200
    assert "PRIVATE_SENTINEL" not in initialized.text
    args = gate_arguments(multi)
    # This assertion deliberately fails when a new brain tool lacks a boundary probe.
    assert set(args) == {n for n, app in mcp_server._TOOL_APPS.items() if app == "brain"}
    async with contextlib.AsyncExitStack() as stack:
        c = await stack.enter_async_context(connect(url, headers=headers)) if credential != "rest" else None

        async def invoke(name, arguments, refused=False):
            if credential == "rest":
                response = await rest(http, grant["key"], name, **arguments)
                assert response.status_code in ((400, 403) if refused else (200,))
                result = response.json()
            elif refused:
                with pytest.raises(ToolError) as exc:
                    await call(c, name, **arguments)
                result = str(exc.value)
            else:
                result = await call(c, name, **arguments)
            assert "PRIVATE_SENTINEL" not in json.dumps(result)
            if credential == "folder":
                assert "raises for next year" not in json.dumps(result)
            return result

        for name, arguments in args.items():
            denied = name == "brain_setup" or (credential == "folder" and name not in mcp_server.FOLDER_KEY_TOOLS)
            await invoke(name, arguments, refused=denied)
        for name, arguments in {
            "brain_history": {"kind": "page", "id": multi["hidden"]["id"]},
            "brain_restore": {"kind": "page", "id": multi["hidden"]["id"], "version": 1},
            "brain_forget_link": {"kind": "memory", "id": multi["hidden_memory"]["id"]},
            "brain_memory_update": {"id": multi["hidden_memory"]["id"], "text": "Stolen"},
            "brain_page_get": {"path": "private/unique"},
            "brain_page_write": {"path": "private/unique", "expected_id": multi["hidden"]["id"], "body": "Stolen"},
            "brain_file_link": {"path": "private/hidden.pdf"},
            "brain_remember": {"brain": "personal", "memories": ["Stolen"]},
            "brain_changes": {"brain": "personal"},
            "brain_onboard": {"brain": "personal"},
            "brain_onboard_done": {"brain": "personal"},
            "brain_curate": {"brain": "personal"},
            "brain_eval": {"brain": "personal"},
            "brain_export_link": {"brain": "personal"},
        }.items():
            await invoke(name, arguments, refused=True)
        if credential == "folder":
            await invoke("brain_page_get", {"path": secret["path"]}, refused=True)
            await invoke("brain_page_write", {"path": secret["path"], "body": "Stripped"}, refused=True)
        else:
            # A single-brain link treats even a foreign-looking prefix as its OWN path.
            await invoke("brain_page_write", {"path": "personal/attempt", "body": "Own brain only"})
            assert brain.get_page(first, path="personal/attempt")["body"] == "Own brain only"
    for table, rows in before.items():
        assert [dict(r) for r in db.get_db().execute(f"SELECT * FROM {table} WHERE brain_id = ?", (second,))] == rows


@pytest.mark.anyio
async def test_rest_own_routes_select_only_carried_brains(http, multi, multi_store):
    import io
    import zipfile
    from backend import files
    from backend.tests.test_files import item

    key = keys.create(multi["list_id"], "REST", access="write", brains=[multi["first"]])["key"]
    hidden_file = files.reserve(multi["second"], [item("hidden.pdf", b"x")])["files"][0]
    multi_store.put(hidden_file["upload"], b"x")
    files.done(multi["second"], hidden_file["id"])
    for method, path, kwargs in [
        ("get", "/export", {}),
        ("post", "/import", {"content": b"invalid"}),
        ("get", "/files?path=hidden.pdf", {}),
        ("post", "/files", {"json": item("new.pdf", b"x")}),
        ("get", f"/files/{hidden_file['id']}", {}),
        ("post", f"/files/{hidden_file['id']}/done", {}),
    ]:
        sep = "&" if "?" in path else "?"
        response = await getattr(http, method)(f"/api/v1{path}{sep}brain=personal", headers=bearer(key), **kwargs)
        assert response.status_code == 403
    for method, path in [
        ("get", f"/files/{hidden_file['id']}"),
        ("post", f"/files/{hidden_file['id']}/done"),
        ("get", "/files?path=hidden.pdf"),
    ]:
        assert (await getattr(http, method)("/api/v1" + path, headers=bearer(key))).status_code == 404
    exported = await http.get("/api/v1/export", headers=bearer(key))
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert all(b"PRIVATE_SENTINEL" not in archive.read(n) for n in archive.namelist())
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as archive:
        archive.writestr("imported.md", "REST import")
    imported = await http.post("/api/v1/import?brain=work", content=zipped.getvalue(), headers=bearer(key))
    assert imported.status_code == 200 and imported.json()["complete"]
    assert brain.get_page(multi["first"], path="imported")["body"] == "REST import"
    assert brain.pages(multi["second"])[0]["path"] == "private/unique"
    folder = keys.create(multi["list_id"], "Folder", access="write", brains=[multi["first"]], folders=["inbox"])["key"]
    assert (await http.get("/api/v1/export", headers=bearer(folder))).status_code == 403
    assert (await http.post("/api/v1/import", content=zipped.getvalue(), headers=bearer(folder))).status_code == 403
    # The same own routes work with a selected second brain on a blended key.
    blended = keys.create(multi["list_id"], "Both", access="write", brains=[multi["first"], multi["second"]])["key"]
    assert (
        await http.get(f"/api/v1/files/{hidden_file['id']}?brain=personal", headers=bearer(blended))
    ).status_code == 302
    assert (await http.get(f"/api/v1/files/{hidden_file['id']}", headers=bearer(blended))).status_code == 404


@pytest.mark.anyio
async def test_staff_links_path_only_default_read_revoke_provenance_and_logs(connect, http, multi, caplog):
    import logging
    from backend import logscrub
    from backend.tests.test_mcp import INIT

    staff = keys.create(multi["list_id"], "Reception", kind="link", brains=[multi["first"]])
    token = staff["key"]
    assert not token.startswith(keys.PREFIX) and staff["access"] == "read"
    assert keys.resolve(token) is None and keys.resolve_link(token)["id"] == staff["id"]
    assert (await http.post("/mcp", headers={**MCP_HEADERS, **bearer(token)}, json=INIT)).status_code == 401
    async with connect(f"http://testserver/link/{token}") as c:
        assert "brain_page_get" in {t.name for t in await c.list_tools()}
        with pytest.raises(ToolError, match="only reads"):
            await call(c, "brain_remember", memories=["Forbidden"])
    writer = keys.create(multi["list_id"], "Curator", kind="link", access="write", brains=[multi["first"]])
    async with connect(f"http://testserver/link/{writer['key']}") as c:
        result = await call(c, "brain_remember", memories=["Staff write"])
        assert result["added"][0]["created_by"] == "Curator"
    assert keys.resolve_link(token)["last_used_at"]
    keys.revoke(multi["list_id"], staff["id"])
    assert (await http.post(f"/link/{token}", json=INIT, headers=MCP_HEADERS)).status_code == 404
    # Real log-record formatting, including each supported token path.
    for path in (f"/link/{writer['key']}", f"/mcp/{writer['key']}", f"/{writer['key']}/mcp"):
        record = logging.LogRecord("probe", logging.INFO, "", 0, "POST %s", (path,), None)
        logscrub.ScrubTokens().filter(record)
        assert writer["key"] not in record.getMessage()


def test_staff_link_cap_is_separate_from_keys(L):
    for i in range(3):
        keys.create(L, f"staff-{i}", kind="link")
    with pytest.raises(ValidationError, match="3 staff links"):
        keys.create(L, "one-too-many", kind="link")
    for i in range(20):
        keys.create(L, f"key-{i}")
    with pytest.raises(ValidationError, match="20 keys"):
        keys.create(L, "last")
    keys.revoke(L, keys.list_keys(L)[-1]["id"])
    assert keys.create(L, "replacement", kind="link")["kind"] == "link"


@pytest.mark.anyio
async def test_blended_round_trip_search_defaults_and_moves(connect, multi, multi_store):
    from backend import files
    from backend.tests.test_files import item

    first, second = multi["first"], multi["second"]
    brain.set_link_brains(multi["list_id"], [first, second])
    # Both search and prose paths must use the brain folder, including curator queues.
    brain.write_page(second, "curator/golden", "- p: sentinel => private/unique")
    brain.write_page(second, "inbox/note", "Personal inbox needle")
    upload = files.reserve(second, [item("inbox/file.pdf", b"x")])["files"][0]
    multi_store.put(upload["upload"], b"x")
    files.done(second, upload["id"])
    async with connect(f"http://testserver/link/{multi['agent_token']}") as c:
        onboard = await call(c, "brain_onboard", brain="personal")
        assert "brain=personal" in onboard["script"][0]
        root = await call(c, "brain_page_list")
        assert [f["folder"] for f in root["folders"]] == ["work", "personal"]
        found = await call(c, "brain_search", query="needle")
        assert {p["brain"] for p in found["pages"]} == {"work", "personal"}
        assert all(p["path"].startswith(p["brain"] + "/") for p in found["pages"])
        with pytest.raises(ToolError, match="work/.*personal/"):
            await call(c, "brain_page_get", path="inbox/public")
        with pytest.raises(ToolError, match="different brains"):
            await call(c, "brain_curate", folder="personal/curator", brain="work")
        memory = (await call(c, "brain_remember", memories=["Default memory"]))["added"][0]
        assert brain.get_memory(first, memory["id"])["text"] == "Default memory"
        replies = [root, found, await call(c, "brain_start")]
        for prefix, page in (("work", multi["public"]), ("personal", multi["hidden"])):
            replies += [
                await call(c, "brain_page_list", folder=prefix),
                await call(c, "brain_page_get", path=prefix + "/" + page["path"]),
                await call(c, "brain_page_write", path=prefix + "/" + page["path"], title="Retitled"),
                await call(c, "brain_page_append", path=prefix + "/" + page["path"], text="Extra"),
                await call(c, "brain_page_edit", path=prefix + "/" + page["path"], old_str="Extra", new_str="Edited"),
                await call(c, "brain_history", kind="page", id=page["id"]),
                await call(c, "brain_restore", kind="page", id=page["id"], version=1),
                await call(c, "brain_changes", brain=prefix),
                await call(c, "brain_curate", brain=prefix, unattended=True),
                await call(c, "brain_eval", brain=prefix),
            ]
        linked = await call(c, "brain_file_link", path="personal/inbox/file.pdf")
        assert linked["file"]["path"] == "personal/inbox/file.pdf"
        curated = await call(c, "brain_curate", brain="personal", unattended=True)
        assert curated["folder"] == "personal/curator" and curated["queue"]["inbox"] == ["personal/inbox/note"]
        assert "personal/curator/questions" in curated["steps"][0]

        async def round_trip(value, parent=""):
            if isinstance(value, dict):
                for key, child in value.items():
                    # Brain identity metadata isn't a content path.
                    if key in ("brains", "brain", "guidance"):
                        continue
                    if key in ("path", "folder") and isinstance(child, str) and child:
                        assert child.split("/")[0] in ("work", "personal"), (key, child)
                        if child.endswith(".pdf"):
                            await call(c, "brain_file_link", path=child)
                        elif key == "folder" or child in ("work", "personal"):
                            await call(c, "brain_page_list", folder=child)
                        else:
                            await call(c, "brain_page_get", path=child)
                    else:
                        await round_trip(child, key)
            elif isinstance(value, list):
                for child in value:
                    if parent in ("inbox", "this_weeks_journal") and isinstance(child, str):
                        await call(c, "brain_page_get", path=child)
                    else:
                        await round_trip(child, parent)

        # Reset the call budget: this deliberate exhaustive walk makes many valid calls.
        ratelimit.clear_all()
        for reply in replies:
            await round_trip(reply)
        ratelimit.clear_all()
        before = brain.get_page(first, multi["public"]["id"])
        brain.write_page(second, "inbox/public", "An unrelated page at the source's old path")
        moved = (
            await call(
                c,
                "brain_page_write",
                path="work/inbox/public",
                move_to="personal/inbox/moved",
                body="Moved and edited",
                expected_version=before["version"],
            )
        )["page"]
        assert moved["path"] == "personal/inbox/moved" and moved["body"] == "Moved and edited"
        history = (await call(c, "brain_history", kind="page", id=moved["id"]))["versions"]
        assert history[0]["action"] == "moved" and history[0]["reason"] == "work → personal"
        assert any(h["body"] == "Public needle" for h in history)
        assert (
            not db.get_db()
            .execute(
                "SELECT 1 FROM brain_versions WHERE brain_id = ? AND kind = 'page' AND item_id = ?",
                (first, moved["id"]),
            )
            .fetchone()
        )
        changed = (
            await call(
                c,
                "brain_memory_update",
                id=memory["id"],
                brain="personal",
                text="Moved memory",
                pass_label="spring-clean",
                reason="Belongs here",
            )
        )["memory"]
        assert brain.get_memory(second, changed["id"])["text"] == "Moved memory"
        move_version = brain.history(second, "memory", changed["id"])[0]
        assert move_version["pass"] == "spring-clean" and move_version["reason"] == "work → personal: Belongs here"
        with pytest.raises(ToolError, match="locked"):
            await call(c, "brain_memory_update", id=multi["hidden_memory"]["id"], brain="work")
        # Duplicate, stale, and destination policy failures roll back the edit as well.
        for kwargs in ({"move_to": "personal/inbox/moved"}, {"move_to": "personal/new", "expected_version": 999}):
            with pytest.raises(ToolError):
                await call(c, "brain_page_write", path="work/curator/golden", body="Must roll back", **kwargs)
            assert brain.get_page(first, path="curator/golden")["body"].startswith("- probe:")
        brain.update_brain(multi["list_id"], second, ai_access="read")
        with pytest.raises(ToolError, match="read-only"):
            await call(c, "brain_page_write", path="work/curator/golden", body="Must roll back", move_to="personal/new")
        assert brain.get_page(first, path="curator/golden")["body"].startswith("- probe:")
        assert f"?brain={second}" in (await call(c, "brain_export_link", brain="personal"))["link"]
        assert f"?brain={second}" in (await call(c, "brain_forget_link", kind="page", id=moved["id"]))["link"]


@pytest.mark.anyio
async def test_concurrent_link_contexts_and_failures_are_isolated(connect, http, multi):
    import asyncio
    from backend.tests.test_mcp import INIT

    tokens = [
        keys.create(multi["list_id"], name, kind="link", access="write", brains=[bid])["key"]
        for name, bid in (("Work staff", multi["first"]), ("Personal staff", multi["second"]))
    ]

    async def run(which):
        url = f"http://testserver/link/{tokens[which]}"
        path = "private/unique" if which else "inbox/public"
        forbidden = "inbox/public" if which else "private/unique"
        initialized = await http.post(url, json=INIT, headers=MCP_HEADERS)
        assert ("PRIVATE_SENTINEL" in initialized.text) is bool(which)
        async with connect(url) as c:
            for _ in range(3):
                with pytest.raises(ToolError):
                    await call(c, "brain_page_get", path=forbidden)
                page = (await call(c, "brain_page_get", path=path))["page"]
                assert ("PRIVATE_SENTINEL" in page["body"]) is bool(which)
                await call(c, "brain_remember", memories=[f"Only brain {which}"])
                await asyncio.sleep(0)

    await asyncio.gather(run(0), run(1))
    assert any(m["text"] == "Only brain 0" for m in brain.memories(multi["first"]))
    assert not any(m["text"] == "Only brain 1" for m in brain.memories(multi["first"]))
    assert mcp_server._brains.get() == [] and mcp_server._key.get() is None


@pytest.mark.anyio
async def test_no_active_brains_are_known_tokens_and_other_apps_work(http, connect, multi, monkeypatch):
    from backend.tests.test_mcp import INIT

    only = keys.create(multi["list_id"], "Only", brains=[multi["second"]])
    staff = keys.create(multi["list_id"], "Staff", kind="link", brains=[multi["second"]])
    all_apps = keys.create(multi["list_id"], "All", app="all", access="write", brains=[multi["second"]])
    brain.set_link_brains(multi["list_id"], [multi["second"]])
    brain.brain_status(multi["list_id"], multi["second"], "archived")
    charged = []
    monkeypatch.setattr(ratelimit, "wrong_token_status", lambda request: charged.append(True) or 429)
    for url, headers in [(f"/link/{staff['key']}", {}), ("/mcp", bearer(only["key"]))]:
        response = await http.post(url, json=INIT, headers={**MCP_HEADERS, **headers})
        assert response.status_code == 403 and "This link reaches no active brain" in response.text
    assert (await http.get("/api/v1", headers=bearer(only["key"]))).status_code == 403
    for url, headers in [
        (f"http://testserver/link/{multi['agent_token']}", {}),
        ("http://testserver/mcp", bearer(all_apps["key"])),
    ]:
        initialized = await http.post(url, json=INIT, headers={**MCP_HEADERS, **headers})
        assert "Common Brain (the brain_ tools)" not in initialized.text
        async with connect(url, headers=headers) as c:
            names = {t.name for t in await c.list_tools()}
            assert "todo_create" in names and "brain_start" not in names
            await call(c, "todo_create", title="Still works")
            with pytest.raises(ToolError, match="no active brain"):
                await call(c, "brain_start")
    assert (await http.get("/api/v1/export", headers=bearer(all_apps["key"]))).status_code == 403
    assert not charged
    assert (await http.post("/link/unknown", json=INIT, headers=MCP_HEADERS)).status_code == 429
    assert charged == [True]


@pytest.mark.anyio
async def test_setup_only_once_and_only_main_link(connect, http, acct):
    first = brain.first_brain(acct["list_id"])
    key = new_key(acct["list_id"])
    arguments = {"name": "Company", "description": "Work records", "rules": ["Work only", "Keep personal details out"]}
    assert (await rest(http, key, "brain_setup", **arguments)).status_code == 403
    staff = keys.create(acct["list_id"], "Staff", kind="link", access="write")
    async with connect(f"http://testserver/link/{staff['key']}") as c:
        with pytest.raises(ToolError, match="main agent link"):
            await call(c, "brain_setup", **arguments)
    async with connect(f"http://testserver/link/{acct['agent_token']}") as c:
        script = (await call(c, "brain_onboard"))["script"]
        assert "what must stay out" in script[0] and "brain_setup" in script[0]
        settled = await call(c, "brain_setup", **arguments)
        assert settled["folder"] == "company" and settled["settled_at"] and settled["rules"] == arguments["rules"]
        with pytest.raises(ToolError, match="Only the person changes"):
            await call(c, "brain_setup", **arguments)
        start = await call(c, "brain_start")
        assert "Work only" in start["rules"] and start["brains"][0]["id"] == first
