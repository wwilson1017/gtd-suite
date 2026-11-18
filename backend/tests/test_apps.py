"""The suite registry (apps.py): the host picks the app, links start with that
app's own address, and account-wide code knows every app's tables."""

import datetime
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from backend import apps, cleanup, common, db, lists, notes, pages, signin
from backend.tests.conftest import turn_on
from backend.tests.test_mcp import anyio_backend, app, connect, http, link  # noqa: F401 (fixtures)
from backend.tests.test_pages import built  # noqa: F401  (fixture)

NOTES = "https://notes.example"


@pytest.fixture()
def suite(todo_db, monkeypatch):
    """A second app on its own address: Notes GTD."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    monkeypatch.setenv("NOTES_BASE_URL", NOTES)


def test_the_host_picks_the_app_and_its_links(suite, client, built):
    on_notes = {"Host": "notes.example"}
    assert client.get("/api/config", headers=on_notes).json()["app"] == "notes"
    assert client.get("/api/config").json()["app"] == "todo"
    page = client.get("/", headers=on_notes).text
    assert '<meta name="gtd-app" content="notes">' in page
    assert "<title>Notes GTD</title>" in page
    assert '<html lang="en" data-app="notes">' in page  # its colours from the first paint
    # The anchor's pages are as they were.
    assert "gtd-app" not in client.get("/").text


def test_each_app_has_its_own_icons(suite, client, built, new_list):
    on_notes = {"Host": "notes.example"}
    page = client.get("/", headers=on_notes).text
    assert 'href="/icon-notes.svg"' in page and 'href="/apple-touch-icon-notes.png"' in page
    assert 'href="/icon.svg"' in client.get("/").text
    manifest = client.get("/app/manifest.webmanifest", headers=on_notes).json()
    assert {i["src"] for i in manifest["icons"]} == {"/icon-notes-192.png", "/icon-notes-512.png"}
    assert manifest["theme_color"] == pages._THEME_COLORS["notes"] != pages._THEME_COLORS["todo"]
    token = new_list()["capture_token"]
    icons = client.get(f"/c/{token}/manifest.webmanifest", headers=on_notes).json()["icons"]
    assert {i["src"] for i in icons} == {"/icon-notes-192.png", "/icon-notes-512.png"}
    # Every app's files ship: a new app in apps.py needs its mark in frontend/public.
    public = Path(__file__).resolve().parents[2] / "frontend" / "public"
    assert set(pages._THEME_COLORS) == set(apps.APPS)
    for key in apps.APPS:
        part = "" if key == apps.ANCHOR else f"-{key}"
        for name in (f"icon{part}.svg", f"icon{part}-192.png", f"icon{part}-512.png", f"apple-touch-icon{part}.png"):
            assert (public / name).is_file(), name


def test_a_host_with_no_configured_address_is_the_anchor(suite, client, monkeypatch):
    monkeypatch.delenv("NOTES_BASE_URL")
    assert client.get("/api/config", headers={"Host": "notes.example"}).json()["app"] == "todo"


def test_config_lists_every_app_with_its_reachable_address(suite, client):
    assert client.get("/api/config").json()["apps"] == {
        "todo": {"title": "Todo GTD", "url": "https://todo.example"},
        "notes": {"title": "Notes GTD", "url": NOTES},
        "projects": {"title": "Projects GTD", "url": "https://todo.example/projects"},
        "sites": {"title": "Simple Sites", "url": "https://todo.example/sites"},
        "brain": {"title": "Common Brain", "url": "https://todo.example/brain"},
    }


def test_a_signin_link_can_be_for_another_app(suite, new_list):
    c = new_list()["client"]
    assert c.post("/api/app/signin-link?app=notes").json()["url"].startswith(f"{NOTES}/signin/")
    assert c.post("/api/app/signin-link").json()["url"].startswith("https://todo.example/signin/")
    assert c.post("/api/app/signin-link?app=nope").status_code == 404


def test_the_agent_link_starts_with_the_hosts_address(suite, new_list):
    c = new_list()["client"]
    assert c.get("/api/app/agent-link", headers={"Host": "notes.example"}).json()["url"].startswith(f"{NOTES}/link/")


def test_cleanup_keeps_a_list_used_only_in_another_app(suite):
    old = common.utcnow() - datetime.timedelta(days=40)
    made = [lists.create_list("UTC")["list_id"] for _ in range(2)]
    with db.transaction() as conn:
        conn.executemany("UPDATE lists SET created_at = ? WHERE id = ?", [(common.to_iso(old), i) for i in made])
    notes.create(made[0], body="Only a note")
    assert cleanup.delete_unused_lists() == 1
    assert lists.get_list(made[0]) is not None


# ── The per-account switch: one link, the apps turned on ─────────────────────

BOARD_TOOLS = {
    "board_list",
    "board_get",
    "board_create",
    "card_get",
    "card_create",
    "card_update",
    "card_move",
    "card_archive",
    "project_open",
    "item_list",
    "item_get",
    "item_create",
    "item_update",
    "item_archive",
    "todo_complete",
    "comment_add",
    "activity_list",
    "calendar_list",
    "report_get",
    "project_search",
    "item_move",
    "chat_read",
    "chat_post",
    "todos_import",
}


@pytest.fixture()
def two(app, monkeypatch):
    """Two lists on a server that serves Projects: one with only Todo on (every list
    before the switch, and a new one made on todo's host), one with Projects on too."""
    monkeypatch.setenv("PROJECTS_BASE_URL", "https://projects.example")
    todo_only, both = lists.create_list("UTC"), lists.create_list("UTC")
    turn_on(both["list_id"], "projects")
    return todo_only, both


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_the_link_offers_only_the_apps_turned_on(connect, two, mode):
    todo_only, both = two
    async with connect(link(todo_only), mode=mode) as c:
        tools = {t.name for t in await c.list_tools()}
        instructions = c.instructions
        # "auto" negotiates with server/discover; "legacy" with initialize.
        assert (c.initialize_result is None) == (mode == "auto")
        # A client that kept an older tool list is refused, with the way to turn it on.
        with pytest.raises(ToolError, match="Projects GTD is off for this account"):
            await c.call_tool("board_list", {})
    assert "todo_create" in tools and not tools & BOARD_TOOLS
    assert "GTD (Getting Things Done) partner" in instructions and "board_" not in instructions
    async with connect(link(both), mode=mode) as c:
        tools = {t.name for t in await c.list_tools()}
        instructions = c.instructions
        assert (await c.call_tool("board_list", {})).data == {"projects": []}
    assert BOARD_TOOLS <= tools and "todo_create" in tools
    assert "partner" in instructions and "board_ and card_ tools" in instructions


@pytest.mark.anyio
async def test_an_off_apps_commands_answer_400_with_how_to_turn_it_on(http, two):
    todo_only, both = two
    guide = (await http.get(f"/link/{todo_only['agent_token']}")).json()
    assert "BOARDS" not in guide["commands"] and "project_boards" not in guide["reads"]
    assert not {line.split(":")[0] for line in guide["mcp"]["tools"]} & BOARD_TOOLS
    assert guide["app"] == "Todo GTD" and "board" not in guide["start_here"]
    res = await http.get(f"/link/{todo_only['agent_token']}?cmd=BOARDS")
    assert res.status_code == 400 and res.json()["error"] == apps.off_message("projects")
    res = await http.get(f"/link/{todo_only['agent_token']}?cmd=NOPE")
    assert "BOARDS" not in res.json()["error"]
    assert (await http.get(f"/link/{both['agent_token']}?cmd=BOARDS")).json()["ok"] is True


@pytest.mark.anyio
async def test_a_list_with_only_another_app_on_gets_only_that_app(connect, http, two):
    _, both = two
    with db.transaction() as conn:
        lists.set_app_in(conn, both["list_id"], "todo", False)
    guide = (await http.get(f"/link/{both['agent_token']}")).json()
    assert [k for k in guide["commands"] if k.isupper()][:2] == ["HELP", "BOARDS"]
    assert "LIST" not in guide["commands"] and set(guide["reads"]) == {"project_boards", "activity", "people"}
    assert "statuses" not in guide and "LINK?cmd=BOARDS" in guide["start_here"]
    async with connect(link(both)) as c:
        assert {t.name for t in await c.list_tools()} == BOARD_TOOLS
        with pytest.raises(ToolError, match="Todo GTD is off"):
            await c.call_tool("todo_list", {})
    # Every app off: the guide still answers, and says what to do.
    with db.transaction() as conn:
        lists.set_app_in(conn, both["list_id"], "projects", False)
    guide = (await http.get(f"/link/{both['agent_token']}")).json()
    assert guide["ok"] is True and "no app turned on" in guide["start_here"]
    assert "the reads" not in guide["start_here"] and "reads, adds" not in guide["about"]
    async with connect(link(both), mode="auto") as c:  # "auto" asks server/discover
        assert await c.list_tools() == [] and c.instructions.startswith("No app is turned on")


@pytest.mark.anyio
async def test_an_app_without_an_address_stays_on_the_link(connect, two, monkeypatch):
    _, both = two
    monkeypatch.delenv("PROJECTS_BASE_URL")
    assert lists.apps_on(both["list_id"]) == ["todo", "projects"]
    async with connect(link(both)) as c:
        assert BOARD_TOOLS <= {t.name for t in await c.list_tools()}


# ── Turning apps on: where a list is made, where it signs in, and Apps ────────


def made_on(create, host: str | None = None) -> list[str]:
    """The apps on for a list made by POST /api/lists on ``host``."""
    res = create(headers={"Host": host} if host else {})
    return lists.apps_on(lists.resolve_agent(res.json()["agent_token"]))


def test_a_list_made_on_an_apps_host_starts_with_that_app_on(suite, create):
    assert made_on(create, "notes.example") == ["notes"]
    assert made_on(create) == ["todo"]


def test_a_list_made_on_an_unknown_or_unconfigured_host_has_the_anchor_on(suite, create, monkeypatch):
    assert made_on(create, "elsewhere.example") == ["todo"]
    monkeypatch.delenv("NOTES_BASE_URL")
    assert made_on(create, "notes.example") == ["todo"]


def test_signing_in_on_an_apps_host_turns_it_on(suite, new_list, client):
    made = new_list()
    url = made["client"].post("/api/app/signin-link?app=notes").json()["url"]
    client.cookies.clear()
    res = client.post(f"/api/signin/{url.rsplit('/', 1)[1]}", headers={"Host": "notes.example"})
    assert res.status_code == 200
    assert lists.apps_on(made["list_id"]) == ["todo", "notes"]


def test_apps_turns_an_app_on_and_off(suite, new_list, monkeypatch):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    assert c.put("/api/app/apps/notes", json={"on": True}).json() == {"apps": ["todo", "notes"]}
    assert c.get("/api/app/session").json()["apps"] == ["todo", "notes"]
    assert c.put("/api/app/apps/todo", json={"on": False}).json() == {"apps": ["notes"]}
    # Off keeps the data: the browser API is not gated, and todo comes back as it was.
    assert c.post("/api/app/todos", json={"title": "kept"}).status_code == 200
    assert c.put("/api/app/apps/todo", json={"on": True}).json() == {"apps": ["todo", "notes"]}
    # Unknown apps are 404; removing a configured address keeps the app served at its path.
    assert c.put("/api/app/apps/nope", json={"on": True}).status_code == 404
    monkeypatch.delenv("NOTES_BASE_URL")
    assert c.put("/api/app/apps/notes", json={"on": True}).json() == {"apps": ["todo", "notes"]}
    assert lists.apps_on(lid) == ["todo", "notes"]
    # Like every account route: same-origin, and the list this tab shows.
    assert c.put("/api/app/apps/todo", json={"on": False}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.put("/api/app/apps/todo", json={"on": False}, headers={"X-List": str(lid + 1)}).status_code == 409
    assert lists.apps_on(lid) == ["todo", "notes"]


def test_sign_in_mail_names_the_app_it_was_asked_from(suite, new_list, client, monkeypatch):
    sent = []
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Todo GTD <signin@todo.example>")
    monkeypatch.setattr(signin, "_send", lambda to, subject, text: sent.append((subject, text)))
    made = new_list()
    made["client"].put("/api/app/email", json={"email": "me@example.com"}, headers={"Host": "notes.example"})
    assert sent[0][0] == "Confirm your email for Notes GTD" and "a Notes GTD list" in sent[0][1]


def test_startup_gives_existing_lists_todo_and_projects_where_they_have_a_board(todo_db, tmp_path, monkeypatch):
    import sqlite3

    from backend import boards

    monkeypatch.setenv("PROJECTS_BASE_URL", "https://projects.example")
    plain, with_board = (lists.create_list("UTC")["list_id"] for _ in range(2))
    boards.create_board(with_board, "Kitchen")
    db.close_db()
    raw = sqlite3.connect(tmp_path / "todo.db")
    # As if the column never existed (SQLite cannot drop a last column with a comment before it).
    raw.execute("ALTER TABLE lists RENAME COLUMN apps TO apps_before")
    raw.commit()
    raw.close()
    db.init_db()
    assert lists.apps_on(plain) == ["todo"] and lists.apps_on(with_board) == ["todo", "projects"]
    turn_on(plain, "projects")
    db.close_db()
    db.init_db()  # a second start changes nothing
    assert lists.apps_on(plain) == ["todo", "projects"]
