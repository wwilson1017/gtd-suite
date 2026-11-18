"""The record of AI tools (lists.seen_ai): which have called an account's agent link and
when each last did, kept for the person's Your AI page. A call counts when it succeeds at
starting an MCP session, running a tool or running a named command; nothing else does, and
a request from a web page never does."""

import pytest
from fastmcp.exceptions import ToolError

from backend import apps, boards, brain, cleanup, db, keys, lists, mcp_server, notes, samples, service
from backend.tests import test_mcp
from backend.tests.conftest import only, turn_on
from scripts import admin

pytestmark = pytest.mark.anyio

# The MCP suite's fixtures, under their own names: pytest looks a fixture up in the module that asks for it.
anyio_backend, app, http, connect, made = (
    test_mcp.anyio_backend,
    test_mcp.app,
    test_mcp.http,
    test_mcp.connect,
    test_mcp.made,
)
INIT, MCP_HEADERS = test_mcp.INIT, test_mcp.MCP_HEADERS


def seen(list_id: int) -> list[tuple]:
    rows = db.get_db().execute(
        "SELECT name, last_seen_at FROM ai_tools WHERE list_id = ? ORDER BY first_seen_at, name", (list_id,)
    )
    return [tuple(r) for r in rows]


def names(list_id: int) -> list[str]:
    return [name for name, _ in seen(list_id)]


def link(made: dict) -> str:
    return f"/link/{made['agent_token']}"


# ── lists.seen_ai ─────────────────────────────────────────────────────────────


def test_a_new_tool_is_written_at_once_and_then_stamped_at_most_hourly(L, freeze):
    freeze("2026-11-02T10:00:00")
    lists.seen_ai(L, "Claude")
    assert seen(L) == [("Claude", "2026-11-02T10:00:00.000Z")]
    freeze("2026-11-02T10:59:59")
    lists.seen_ai(L, "Claude")  # within the hour: no write
    lists.seen_ai(L, "Codex")  # a new name does not wait
    assert seen(L) == [("Claude", "2026-11-02T10:00:00.000Z"), ("Codex", "2026-11-02T10:59:59.000Z")]
    freeze("2026-11-02T11:00:01")
    lists.seen_ai(L, "Claude")
    assert seen(L) == [("Claude", "2026-11-02T11:00:01.000Z"), ("Codex", "2026-11-02T10:59:59.000Z")]
    # One account's tools are its own.
    assert seen(lists.create_list("UTC")["list_id"]) == []


def test_a_name_is_cleaned_and_a_tool_that_gives_none_is_stored_empty(L):
    for name in ("  Claude  ", "x" * 300, None, "", "   "):
        lists.seen_ai(L, name)
    assert sorted(names(L)) == ["", "Claude", "x" * 100]


def test_at_the_cap_only_the_tools_already_known_are_stamped(L, freeze, monkeypatch):
    monkeypatch.setattr(lists, "MAX_AI_TOOLS", 2)
    freeze("2026-11-02T10:00:00")
    for name in ("Claude", "Codex", "Grok"):
        lists.seen_ai(L, name)
    assert names(L) == ["Claude", "Codex"]
    freeze("2026-11-02T12:00:00")
    lists.seen_ai(L, "Grok")
    lists.seen_ai(L, "Codex")
    assert seen(L) == [("Claude", "2026-11-02T10:00:00.000Z"), ("Codex", "2026-11-02T12:00:00.000Z")]


def test_the_page_gets_each_tools_last_day_in_the_lists_own_zone_newest_first(L, freeze):
    # L keeps Chicago time: 03:00 UTC on the 3rd is still the evening of the 2nd there.
    with db.transaction() as conn:
        conn.execute("INSERT INTO ai_tools (list_id, name, first_seen_at) VALUES (?, 'Grok', '2026-01-01')", (L,))
    freeze("2026-10-20T15:00:00")
    lists.seen_ai(L, "Codex")
    freeze("2026-11-03T03:00:00")
    lists.seen_ai(L, "Claude")
    assert lists.ai_tools(L) == [
        {"name": "Claude", "last_used": "2026-11-02", "days_ago": 0},
        {"name": "Codex", "last_used": "2026-10-20", "days_ago": 13},
        # Known only from what it wrote before the record began: no day.
        {"name": "Grok", "last_used": None, "days_ago": None},
    ]
    freeze("2026-11-03T07:00:00")  # past midnight in Chicago
    assert lists.ai_tools(L)[0] == {"name": "Claude", "last_used": "2026-11-02", "days_ago": 1}


def test_the_browser_reads_the_tools_with_its_session_and_again_on_request(client, new_list):
    mine, theirs = new_list(), new_list()
    assert mine["client"].get("/api/app/session").json()["ai_tools"] == []
    lists.seen_ai(mine["list_id"], "Claude")
    tools = mine["client"].get("/api/app/session").json()["ai_tools"]
    assert [t["name"] for t in tools] == ["Claude"] and tools[0]["days_ago"] == 0
    again = mine["client"].get("/api/app/ai-tools")
    assert again.json() == {"ai_tools": tools} and again.headers["cache-control"] == "no-store"
    assert theirs["client"].get("/api/app/ai-tools").json() == {"ai_tools": []}
    client.cookies.clear()
    assert client.get("/api/app/ai-tools", headers={"X-List": str(mine["list_id"])}).status_code == 401


# ── What counts as a call ─────────────────────────────────────────────────────


async def test_starting_a_session_records_the_name_the_client_gives_in_its_handshake(http, made):
    # The User-Agent is an HTTP library's, so the handshake is the only place this client names itself.
    assert (await http.post(link(made), json=INIT, headers=MCP_HEADERS)).status_code == 200
    assert names(made["list_id"]) == ["raw-probe"]
    titled = {
        **INIT,
        "params": {**INIT["params"], "clientInfo": {"name": "claude-ai", "title": "Claude", "version": "1"}},
    }
    assert (await http.post(link(made), json=titled, headers=MCP_HEADERS)).status_code == 200
    assert names(made["list_id"]) == ["raw-probe", "Claude"]


async def test_a_program_keys_name_comes_before_the_handshakes(http, made):
    key = keys.create(made["list_id"], "vm-jobs", "all", "write")["key"]
    res = await http.post("/mcp", json=INIT, headers={**MCP_HEADERS, "Authorization": f"Bearer {key}"})
    assert res.status_code == 200 and names(made["list_id"]) == ["vm-jobs"]


async def test_a_tool_call_records_once_and_listing_the_tools_does_not(connect, http, made):
    list_id = made["list_id"]
    # "auto" asks server/discover and then names the client on every request: no handshake.
    async with connect(f"http://testserver{link(made)}", mode="auto", name="Codex") as c:
        assert await c.list_tools() and c.instructions and c.initialize_result is None
        assert seen(list_id) == []
        await c.call_tool("todo_list", {})
        await c.call_tool("todo_create", {"title": "x"})
    assert names(list_id) == ["Codex"]
    discover = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    assert (await http.post(link(made), json=discover, headers=MCP_HEADERS)).status_code == 200
    assert names(list_id) == ["Codex"]


async def test_an_older_client_named_only_in_its_handshake_leaves_one_unnamed_row(connect, made):
    async with connect(f"http://testserver{link(made)}", mode="legacy", name="Codex") as c:
        assert names(made["list_id"]) == ["Codex"]
        await c.call_tool("todo_list", {})
        await c.call_tool("todo_list", {})
    assert names(made["list_id"]) == ["Codex", ""]


async def test_a_rest_tool_call_records_under_its_keys_name(http, made):
    key = keys.create(made["list_id"], "vm-jobs", "all", "write")["key"]
    auth = {"Authorization": f"Bearer {key}"}
    assert (await http.get("/api/v1", headers=auth)).status_code == 200
    assert (await http.post("/api/v1/tools/todo_nope", json={}, headers=auth)).status_code == 404
    assert (await http.post("/api/v1/tools/todo_get", json={"id": 999}, headers=auth)).status_code == 400
    assert seen(made["list_id"]) == []
    assert (await http.post("/api/v1/tools/todo_list", json={}, headers=auth)).status_code == 200
    assert names(made["list_id"]) == ["vm-jobs"]


async def test_a_named_command_records_and_the_bare_guide_does_not(http, made):
    list_id = made["list_id"]
    assert (await http.get(link(made))).status_code == 200  # a browser opening the link
    assert (await http.get(link(made), headers={"Accept": "text/html"})).status_code == 200
    assert seen(list_id) == []
    assert (await http.get(f"{link(made)}?cmd=HELP")).status_code == 200
    assert names(list_id) == [""]  # an HTTP library's User-Agent names no tool
    claude = {"User-Agent": "Claude-User/1.0"}
    assert (await http.get(f"{link(made)}?cmd=LIST", headers=claude)).status_code == 200
    assert (await http.post(f"{link(made)}?cmd=ADD", json={"title": "x"}, headers=claude)).status_code == 200
    assert names(list_id) == ["", "Claude"]


async def test_a_call_that_is_refused_or_fails_is_not_recorded(connect, http, made):
    list_id = made["list_id"]
    turn_on(list_id, "brain")
    only(list_id, "todo", "brain")
    brain.update_brain(list_id, brain.first_brain(list_id), ai_access="read")
    async with connect(f"http://testserver{link(made)}") as c:
        for tool, args, why in (
            ("board_list", {}, "is off for this account"),  # an app that is off
            ("todo_nope", {}, "Unknown tool"),
            ("todo_list", {"limit": "many"}, "validation error"),  # arguments FastMCP refuses
            ("todo_list", {"limit": 0}, "limit must be"),  # arguments the tool refuses
            ("todo_get", {"id": 999}, "not found"),
            ("brain_remember", {"memories": ["x"]}, "read-only"),  # the brain's own policy
        ):
            with pytest.raises(ToolError, match=why):
                await c.call_tool(tool, args)
    assert (await http.get(f"{link(made)}?cmd=NOPE")).status_code == 400
    assert (await http.get(f"{link(made)}?cmd=BOARDS")).status_code == 400  # an app that is off
    assert (await http.get(f"{link(made)}?cmd=ADD&title=x")).status_code == 405  # a write sent by GET
    assert (await http.get(f"{link(made)}?cmd=GET&id=999")).status_code == 404
    assert (await http.get("/link/not-a-link?cmd=LIST")).status_code == 404
    assert seen(list_id) == []


async def test_a_request_from_a_web_page_is_never_an_ai_tool(http, made, monkeypatch):
    list_id = made["list_id"]
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    # The app's own origin, which the commands allow, and a foreign one, which they refuse.
    own = await http.get(f"{link(made)}?cmd=LIST", headers={"Origin": "https://todo.example"})
    foreign = await http.get(f"{link(made)}?cmd=LIST", headers={"Origin": "https://evil.example"})
    assert (own.status_code, foreign.status_code) == (200, 403)
    # MCP lets a page through only from the same origin on this machine.
    local = {**MCP_HEADERS, "Origin": "http://localhost"}
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "todo_list", "arguments": {}}}
    for message in (INIT, call):
        assert (await http.post(f"http://localhost{link(made)}", json=message, headers=local)).status_code == 200
    assert seen(list_id) == []
    assert (await http.post(f"http://localhost{link(made)}", json=call, headers=MCP_HEADERS)).status_code == 200
    assert names(list_id) == [""]


# ── The one fill, when the table is made ──────────────────────────────────────


def test_the_step_that_makes_the_table_fills_it_from_what_tools_already_left(todo_db, monkeypatch):
    monkeypatch.setenv("BRAIN_BASE_URL", "https://brain.example")
    wrote, edited, quiet = (lists.create_list("UTC")["list_id"] for _ in range(3))
    # One tool across four apps, another in one, and one that never gave a name.
    service.create_todo(wrote, "x", source="agent", source_client="Claude")
    notes.create(wrote, body="n", source="agent", source_client="Claude")
    board = boards.create_board(wrote, "Plan", source="agent", client="Claude")
    boards.create_card(wrote, board["id"], "c", source="agent", source_client="Codex")
    brain.remember(brain.first_brain(wrote), ["Likes tea"], by="Claude")
    service.create_todo(wrote, "y", source="agent")
    service.create_todo(wrote, "mine", source="ui", source_client="made in the app, so not a tool")
    # An account whose only trace is an AI's edit to a note the person made.
    notes.append(edited, notes.create(edited, body="mine")["id"], "more", by="Grok")
    notes.create(quiet, body="mine")
    with db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_tools").fetchone()[0] == 0  # none of that was a call
        conn.execute("DROP TABLE ai_tools")

    db.init_db()
    assert {a: sorted(names(a)) for a in (wrote, edited, quiet)} == {
        wrote: ["", "Claude", "Codex"],
        edited: ["Grok"],
        quiet: [],
    }
    assert {last for a in (wrote, edited) for _, last in seen(a)} == {None}
    assert lists.ai_tools(edited) == [{"name": "Grok", "last_used": None, "days_ago": None}]
    # A filled tool's next call gives it a day.
    lists.seen_ai(edited, "Grok")
    assert lists.ai_tools(edited)[0]["days_ago"] == 0

    # Only that step fills: a later start leaves the table as it is.
    with db.transaction() as conn:
        conn.execute("DELETE FROM ai_tools WHERE list_id = ?", (wrote,))
    db.init_db()
    assert names(wrote) == [] and names(edited) == ["Grok"]


# ── Bookkeeping, not content ──────────────────────────────────────────────────


def test_the_record_is_not_content_and_goes_with_its_list(todo_db, capsys):
    assert "ai_tools" not in apps.content_tables() and "ai_tools" in admin._LIST_TABLES
    unused, deleted, kept = (lists.create_list("UTC")["list_id"] for _ in range(3))
    for list_id in (unused, deleted, kept):
        lists.seen_ai(list_id, "Claude")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = '2020-01-01T00:00:00.000Z' WHERE id IN (?, ?)", (unused, kept))
    service.create_todo(kept, "x")
    # An AI that connected and wrote nothing does not make a list look used.
    assert cleanup.delete_unused_lists() == 1 and lists.get_list(unused) is None
    assert admin.main(["delete", str(deleted), f"--yes-delete-list-{deleted}", "--no-snapshot"]) == 0
    assert "1 ai tools" in capsys.readouterr().out
    assert [r[0] for r in db.get_db().execute("SELECT list_id FROM ai_tools")] == [kept]


# ── The words that point at the new pages ─────────────────────────────────────


async def test_the_agent_links_own_words_point_at_settings_and_your_ai(http, made):
    assert apps.off_message("notes") == (
        "Notes GTD is off for this account. The person can turn it on under Settings, in Apps, "
        "in any app on their account."
    )
    only(made["list_id"])  # every app off
    assert (await http.get(link(made))).json()["about"].endswith("can turn one on under Settings, in Apps.")
    assert mcp_server._instructions([]).endswith("can turn one on under Settings, in Apps.")
    assert "under [Connect your AI](/app/ai)." in str(samples._PROJECTS)
