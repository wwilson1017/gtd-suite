"""Agent Commands: the agent link's guide and its twelve commands, beside MCP on the
same addresses, against the real app and a real SQLite file."""

import json

import pytest

from backend import agent_cmd, common, db, lists, logscrub, mcp_server, ratelimit, service
from backend.tests.conftest import confirm_list
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    INIT,
    MCP_HEADERS,
    TOOLS,
    anyio_backend,
    app,
    browser,
    call,
    connect,
    http,
    link,
    made,
)

pytestmark = pytest.mark.anyio

ALL = [
    "HELP",
    "LIST",
    "GET",
    "ADD",
    "UPDATE",
    "BULK_UPDATE",
    "COMPLETE",
    "ARCHIVE",
    "IMPORT",
    "EXPORT",
    "CHANGES",
    "CHANGES_COUNT",
    "BOARDS",
    "BOARD",
    "CARD",
    "CREATE_BOARD",
    "ADD_CARD",
    "UPDATE_CARD",
    "MOVE_CARD",
    "ARCHIVE_CARD",
    "RESTORE_CARD",
    "PROJECT",
    "ITEMS",
    "ITEM",
    "ADD_ITEM",
    "UPDATE_ITEM",
    "COMPLETE_TODO",
    "REOPEN_TODO",
    "COMMENT",
    "MOVE_ITEM",
    "COPY_ITEM",
    "ARCHIVE_ITEM",
    "RESTORE_ITEM",
    "ACTIVITY",
    "CALENDAR",
    "CHAT",
    "CHAT_POST",
    "IMPORT_TODOS",
    "FIND",
    "REPORT",
    "PEOPLE",
    "NOTES",
    "NOTE",
    "EXPORT_NOTES",
    "ADD_NOTE",
    "APPEND_NOTE",
    "EDIT_NOTE",
    "UPDATE_NOTE",
    "ARCHIVE_NOTE",
]
WRITES = [
    "ADD",
    "UPDATE",
    "BULK_UPDATE",
    "COMPLETE",
    "ARCHIVE",
    "IMPORT",
    "CREATE_BOARD",
    "ADD_CARD",
    "UPDATE_CARD",
    "MOVE_CARD",
    "ARCHIVE_CARD",
    "RESTORE_CARD",
    "ADD_ITEM",
    "UPDATE_ITEM",
    "COMPLETE_TODO",
    "REOPEN_TODO",
    "COMMENT",
    "ARCHIVE_ITEM",
    "RESTORE_ITEM",
    "MOVE_ITEM",
    "COPY_ITEM",
    "CHAT_POST",
    "IMPORT_TODOS",
    "ADD_NOTE",
    "APPEND_NOTE",
    "EDIT_NOTE",
    "UPDATE_NOTE",
    "ARCHIVE_NOTE",
]


def shapes(made) -> dict:
    """The four addresses of one agent link: (path, headers)."""
    token = made["agent_token"]
    return {
        "link/token": (f"/link/{token}", {}),
        "mcp/token": (f"/mcp/{token}", {}),
        "token/mcp": (f"/{token}/mcp", {}),
        "bearer": ("/mcp", {"Authorization": f"Bearer {token}"}),
    }


def path(made) -> str:
    return f"/link/{made['agent_token']}"


def titles(list_id) -> list[str]:
    return [t["title"] for t in service.list_todos(list_id, limit=500)]


# ── The guide ─────────────────────────────────────────────────────────────────


async def test_a_plain_get_answers_with_the_guide(http, made, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    lists.set_name(made["list_id"], "Home")
    res = await http.get(path(made))
    assert res.status_code == 200 and res.headers["content-type"] == "application/json"
    assert res.headers["cache-control"] == "no-store"
    guide = res.json()
    the_link = f"https://todo.example/link/{made['agent_token']}"
    assert (guide["ok"], guide["protocol"], guide["version"], guide["app"], guide["list"]) == (
        True,
        "Agent Commands",
        2,
        "Todo GTD and Projects GTD and Notes GTD",
        "Home",
    )
    assert guide["mcp"]["url"] == the_link and guide["mcp"]["transport"] == "streamable-http"
    assert {line.split(":")[0] for line in guide["mcp"]["tools"]} == set(TOOLS)
    commands = guide["commands"]
    assert commands["url"] == f"{the_link}?cmd=NAME"
    assert [k for k in commands if k.isupper()] == ALL
    for name in WRITES:
        assert commands[name]["method"] == "POST", name
    for name in set(ALL) - set(WRITES):
        assert commands[name]["method"] == "GET", name
    for name in ALL:
        assert {"request", "response"} <= set(commands[name]["example"]), name
    assert guide["statuses"] == ["inbox", "next_action", "waiting_for", "delegated", "someday_maybe", "done", "dropped"]
    # Tests run hosted (OPEN_SIGNUP) with no confirmed email: the small caps.
    assert guide["limits"]["todos_per_list"] == common.ANON_CAPS[0]
    assert (
        guide["limits"]["todos_per_import"],
        guide["limits"]["todos_per_page"],
        guide["limits"]["ids_per_bulk_update"],
    ) == (100, 500, 500)
    today = str(common.business_today("America/Chicago"))
    assert "America/Chicago" in guide["rules"][0] and today in guide["rules"][0]
    assert "ARCHIVE" in guide["howto"]["archive"]
    # It opens by telling the AI that reads it what to do, and hands it the common
    # reads as complete addresses: a fetch tool that follows only an address it has
    # already seen (Claude's) can then read without building one.
    keys = list(guide)
    assert keys.index("start_here") < keys.index("app") < keys.index("commands")
    assert guide["start_here"].startswith("You are an AI assistant")
    assert "POST" in guide["start_here"] and "MCP is optional" in guide["start_here"]
    # The syntax is in the paragraph itself: a summarising fetch layer withholds the
    # token-bearing addresses as "a secret", and the model must still learn ?cmd=.
    assert "LINK?cmd=LIST" in guide["start_here"]
    assert set(guide["reads"]) == {
        "next_actions",
        "inbox",
        "starred",
        "waiting_for",
        "next_actions_due_or_overdue",
        "everything",
        "project_boards",
        "activity",
        "people",
        "notes",
    }
    assert today in guide["reads"]["next_actions_due_or_overdue"]
    for url in guide["reads"].values():
        assert url.startswith(f"{the_link}?cmd="), url
        res = await http.get(url.removeprefix("https://todo.example"))
        assert res.status_code == 200 and res.json()["ok"] is True, url
    assert {"400", "404", "405", "429"} <= set(guide["errors"])
    # It echoes the caller's own link and nothing else of the list's.
    for secret in (made["session_token"], made["capture_token"]):
        assert secret not in res.text
    # Bearer callers and the other path shape get the same guide.
    for url, headers in shapes(made).values():
        assert (await http.get(url, headers=headers)).json() == guide


async def test_a_paged_answer_carries_the_next_page_as_an_address(http, made, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    for n in range(3):
        service.create_todo(made["list_id"], f"todo {n}")
    first = (await http.get(f"{path(made)}?cmd=LIST&limit=2")).json()
    link = f"https://todo.example{path(made)}"
    assert first["count"] == 2 and first["next_offset"] == 2
    assert first["next_url"] == f"{link}?cmd=LIST&limit=2&offset=2"
    last = (await http.get(first["next_url"].removeprefix("https://todo.example"))).json()
    assert last["count"] == 1 and last["next_offset"] is None and "next_url" not in last


async def test_a_browser_gets_a_page_with_the_guide_in_it(http, made):
    lists.set_name(made["list_id"], "<b>Mine</b>")
    res = await http.get(
        path(made), headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    )
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/html")
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-robots-tag"] == "noindex, nofollow"
    assert "This is a GTD agent link" in res.text and "Do not share it" in res.text
    # The AI reader first, and the reads as real links (html-escaped & in the href).
    assert res.text.index("If you are an AI assistant") < res.text.index("If you are a person")
    assert f'href="http://testserver{path(made)}?cmd=LIST&amp;status=next_action&amp;limit=500"' in res.text
    assert "<b>Mine</b>" not in res.text and "&lt;b&gt;Mine&lt;/b&gt;" in res.text
    assert "BULK_UPDATE" in res.text and "next_offset" in res.text
    # An explicit JSON preference still gets JSON.
    res = await http.get(path(made), headers={"Accept": "application/json, text/html"})
    assert res.json()["protocol"] == "Agent Commands"


async def test_mcp_traffic_still_reaches_fastmcp(http, connect, made, monkeypatch):
    # Today FastMCP refuses every GET (stateless, JSON responses): its own 405.
    res = await http.get(path(made), headers={"Accept": "text/event-stream"})
    assert res.status_code == 405 and set(res.headers["allow"].split(", ")) == {"DELETE", "POST"}
    assert res.headers["content-type"].startswith("text/plain")
    # A real MCP client: initialize and a tool call.
    assert (await http.post(path(made), json=INIT, headers=MCP_HEADERS)).status_code == 200
    async with connect(link(made)) as c:
        assert (await call(c, "todo_create", title="via MCP"))["todo"]["source"] == "agent"
    # Which requests the MCP app gets: no cmd, and not a plain GET/HEAD.
    seen = []

    async def recorder(scope, receive, send):
        seen.append(scope["method"])
        await send({"type": "http.response.start", "status": 299, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    monkeypatch.setattr(mcp_server, "mcp_app", recorder)
    for method, accept in (
        ("GET", "text/event-stream"),
        ("GET", MCP_HEADERS["Accept"]),
        ("POST", MCP_HEADERS["Accept"]),
        ("DELETE", ""),
    ):
        res = await http.request(method, path(made), headers={"Accept": accept})
        assert res.status_code == 299, (method, accept)
    assert seen == ["GET", "GET", "POST", "DELETE"]
    for method, url in (("GET", path(made)), ("HEAD", path(made)), ("POST", f"{path(made)}?cmd=LIST")):
        assert (await http.request(method, url)).status_code != 299, (method, url)
    assert seen == ["GET", "GET", "POST", "DELETE"]


# ── Every command, on every address ───────────────────────────────────────────


@pytest.mark.parametrize("shape", ["link/token", "mcp/token", "token/mcp", "bearer"])
async def test_every_command_works_on_every_address(http, made, shape):
    url, headers = shapes(made)[shape]
    lid = made["list_id"]

    async def run(name, body=None, **args):
        query = "&".join(f"{k}={v}" for k, v in {"cmd": name, **args}.items())
        res = await http.request(
            "POST" if name.upper() in WRITES else "GET",
            f"{url}?{query}",
            json=body,
            headers={**headers, "User-Agent": "n8n/1.73"},
        )
        assert res.status_code == 200, (name, res.text)
        assert res.headers["cache-control"] == "no-store"
        out = res.json()
        assert out["ok"] is True
        return out

    assert (await run("HELP"))["protocol"] == "Agent Commands"
    added = (await run("ADD", {"title": "Buy paint", "project": "Fence", "tags": ["diy"], "due_date": "2026-10-20"}))[
        "todo"
    ]
    assert (added["project_name"], added["tags"], added["status"]) == ("Fence", ["diy"], "inbox")
    assert (added["source"], added["source_client"]) == ("agent", "n8n")
    assert (await run("get", id=added["id"]))["todo"]["title"] == "Buy paint"
    updated = (await run("UPDATE", {"status": "next_action", "due_date": ""}, id=added["id"]))["todo"]
    assert (updated["status"], updated["due_date"], updated["tags"]) == ("next_action", None, ["diy"])
    listed = await run("List", status="next_action", project="Fence")
    assert [t["id"] for t in listed["todos"]] == [added["id"]]
    assert (listed["count"], listed["next_offset"]) == (1, None)
    imported = await run(
        "IMPORT",
        {"todos": [{"title": "Call Sam", "people": ["Sam"]}, {"title": "Old idea", "status": "someday_maybe"}]},
    )
    assert imported["created"] == 2 and len(imported["ids"]) == 2
    for todo_id in imported["ids"]:  # the bulk path carries provenance too
        row = service.get_todo(lid, todo_id)
        assert (row["source"], row["source_client"]) == ("agent", "n8n")
    bulk = await run("BULK_UPDATE", {"ids": imported["ids"], "fields": {"star": True}})
    assert bulk == {"ok": True, "updated": sorted(imported["ids"])}
    assert (await run("COMPLETE", id=added["id"]))["todo"]["status"] == "done"
    assert (await run("ARCHIVE", id=imported["ids"][1]))["todo"]["status"] == "dropped"
    exported = await run("EXPORT")
    assert {t["title"] for t in exported["todos"]} == {"Buy paint", "Call Sam", "Old idea"}
    assert exported["next_offset"] is None
    counted = await run("CHANGES_COUNT")
    assert counted == {"ok": True, **service.changes_count(lid)} and counted["count"] > 0
    # It all landed in this list; archiving kept the row.
    assert sorted(titles(lid)) == ["Buy paint", "Call Sam", "Old idea"]
    assert service.get_todo(lid, imported["ids"][1])["status"] == "dropped"


# ── The method rule ───────────────────────────────────────────────────────────


async def test_a_write_sent_as_get_or_head_is_405_and_changes_nothing(http, made):
    lid = made["list_id"]
    todo = service.create_todo(lid, "untouched")
    for name in WRITES:
        for method in ("GET", "HEAD"):
            res = await http.request(method, f"{path(made)}?cmd={name}&id={todo['id']}")
            assert res.status_code == 405, (name, method)
            assert res.headers["allow"] == "POST"
            if method == "GET":
                assert res.json() == {"ok": False, "error": f"{name} is a write: send it as POST. Nothing was changed."}
    assert service.get_todo(lid, todo["id"]) == todo and titles(lid) == ["untouched"]
    # A read sent as POST is pointed back at GET.
    res = await http.post(f"{path(made)}?cmd=LIST", json={"status": "inbox"})
    assert res.status_code == 405 and res.headers["allow"] == "GET, HEAD"
    # PUT and DELETE are no command's method.
    assert (await http.put(f"{path(made)}?cmd=ADD", json={"title": "x"})).status_code == 405
    assert (await http.delete(f"{path(made)}?cmd=ARCHIVE&id={todo['id']}")).status_code == 405
    assert titles(lid) == ["untouched"]


async def test_an_unknown_command_or_argument_is_400_and_names_the_right_ones(http, made):
    res = await http.get(f"{path(made)}?cmd=DELETE&id=1")
    assert res.status_code == 400
    assert res.json()["error"] == ("Unknown command 'DELETE'. Commands: " + ", ".join(ALL))
    res = await http.get(f"{path(made)}?cmd=LIST&stauts=inbox")
    assert res.status_code == 400 and "Unknown arguments for LIST: stauts" in res.json()["error"]
    for query, message in (
        ("cmd=LIST&limit=501", "limit must be between 1 and 500"),
        ("cmd=LIST&offset=-1", "offset must be 0 or more"),
        ("cmd=LIST&starred=maybe", "starred must be true or false"),
        ("cmd=GET", "id is required"),
        ("cmd=GET&id=abc", "id must be an integer"),
        ("cmd=GET&id=--5", "id must be an integer"),
        ("cmd=GET&id=" + "9" * 30, "Number out of range"),
        ("cmd=LIST&status=soon", "Invalid status 'soon'"),
    ):
        res = await http.get(f"{path(made)}?{query}")
        assert res.status_code == 400 and message in res.json()["error"], query
    for body, message in (
        (b"{not json", "The body must be JSON"),
        (b"[1, 2]", "The body must be a JSON object"),
        (b'{"title": "x", "source": "ui"}', "Unknown fields: source"),
        (b'{"notes": "no title"}', "title: Field required"),
    ):
        res = await http.post(f"{path(made)}?cmd=ADD", content=body)
        assert res.status_code == 400 and message in res.json()["error"], body
    assert service.list_todos(made["list_id"]) == []


# ── IMPORT and BULK_UPDATE are all or nothing ─────────────────────────────────


async def test_import_is_capped_and_all_or_nothing(http, made):
    lid = made["list_id"]
    url = f"{path(made)}?cmd=IMPORT"
    res = await http.post(url, json={"todos": [{"title": "x"}] * 101})
    assert res.status_code == 400 and "max 100 per call" in res.json()["error"]
    res = await http.post(
        url, json={"todos": [{"title": "fine", "project": "New"}, {"title": "bad", "due_date": "tomorrow"}]}
    )
    assert res.status_code == 400
    assert res.json()["error"].startswith("todos[1]: due_date must be YYYY-MM-DD")
    res = await http.post(url, json={"items": []})
    assert res.status_code == 400 and "Unknown fields: items" in res.json()["error"]
    assert service.list_todos(lid) == [] and service.list_projects(lid) == []
    assert (await http.post(url, json={"todos": [{"title": "x"}] * 100})).json()["created"] == 100


async def test_bulk_update_is_capped_and_all_or_nothing(http, made):
    lid = made["list_id"]
    mine = [service.create_todo(lid, f"mine {i}")["id"] for i in range(2)]
    theirs = service.create_todo(lists.create_list()["list_id"], "not yours")
    url = f"{path(made)}?cmd=BULK_UPDATE"
    res = await http.post(url, json={"ids": list(range(1, 502)), "fields": {"star": True}})
    assert res.status_code == 400 and "at most 500" in res.json()["error"]
    res = await http.post(url, json={"ids": [*mine, theirs["id"]], "fields": {"star": True}})
    assert res.status_code == 404
    assert res.json()["error"] == f"Todo not found: {theirs['id']} (nothing was changed)"
    assert [service.get_todo(lid, i)["star"] for i in mine] == [False, False]
    assert service.get_todo(theirs["list_id"], theirs["id"])["star"] is False
    res = await http.post(url, json={"ids": mine, "fields": {"source": "ui"}})
    assert res.status_code == 400 and "Unknown fields: source" in res.json()["error"]


# ── Paging ────────────────────────────────────────────────────────────────────


async def test_export_and_list_page_through_everything_without_gaps_or_repeats(http, made):
    confirm_list(made["list_id"])  # 1,200 todos need the confirmed-email caps
    lid = made["list_id"]
    for batch in range(12):
        service.bulk_create(
            lid, [{"title": f"t{batch * 100 + i}", "status": "done" if i % 4 == 0 else "inbox"} for i in range(100)]
        )

    async def walk(query) -> list:
        seen, offset, pages = [], 0, []
        while offset is not None:
            out = (await http.get(f"{path(made)}?{query}&offset={offset}")).json()
            seen += [t["id"] for t in out["todos"]]
            pages.append(out["count"])
            offset = out["next_offset"]
        return seen, pages

    every, pages = await walk("cmd=EXPORT")
    assert pages == [500, 500, 200] and len(every) == len(set(every)) == 1200
    assert set(every) == {t["id"] for b in range(3) for t in service.list_todos(lid, limit=500, offset=b * 500)}
    inbox, pages = await walk("cmd=LIST&status=inbox&limit=400")
    assert pages == [400, 400, 100] and len(inbox) == len(set(inbox)) == 900
    done, pages = await walk("cmd=LIST&status=done&limit=250")
    assert pages == [250, 50] and len(done) == len(set(done)) == 300
    # The web API pages the same way.
    second = (await http.get("/api/app/todos?limit=2&offset=1", headers=browser(made))).json()["todos"]
    assert [t["id"] for t in second] == every[1:3]


# ── The link and the list ─────────────────────────────────────────────────────


async def test_another_lists_ids_are_not_found(http, made):
    theirs = service.create_todo(lists.create_list()["list_id"], "not yours")
    for name in ("GET", "UPDATE", "COMPLETE", "ARCHIVE"):
        res = await http.request(
            "GET" if name == "GET" else "POST",
            f"{path(made)}?cmd={name}&id={theirs['id']}",
            json=None if name == "GET" else {"title": "mine now"},
        )
        assert res.status_code == 404, name
        assert res.json() == {"ok": False, "error": f"Todo not found: {theirs['id']}"}
    assert service.get_todo(theirs["list_id"], theirs["id"]) == theirs


async def test_unknown_replaced_or_disabled_links_are_404_and_count_as_misses(http, made, monkeypatch):
    other = lists.create_list()
    old = other["agent_token"]
    lists.rotate_agent(other["list_id"])
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = '2026-10-01T00:00:00.000Z' WHERE id = ?", (made["list_id"],))
    for token in ("nope", old, made["agent_token"], made["session_token"], made["capture_token"]):
        for url in (f"/link/{token}", f"/mcp/{token}", f"/{token}/mcp"):
            for query in ("", "?cmd=LIST", "?cmd=ADD"):
                res = await http.get(url + query)
                assert res.status_code == 404, (url, query)
                assert "www-authenticate" not in res.headers
                assert "Agent Commands" not in res.text
    res = await http.get("/mcp?cmd=LIST", headers={"Authorization": f"Bearer {old}"})
    assert res.status_code == 401 and res.headers["www-authenticate"] == "Bearer"
    # Misses fill the address's wrong-link bucket, as on the MCP side.
    ratelimit.clear_all()
    monkeypatch.setattr(ratelimit.bad_token_limiter, "max_hits", 2)
    codes = [(await http.get(f"/mcp/{old}?cmd=LIST")).status_code for _ in range(3)]
    assert codes == [404, 404, 429]


async def test_a_full_list_is_400_with_the_full_list_message(http, made, monkeypatch):
    monkeypatch.setattr(common, "ANON_CAPS", (1, 20, 10))
    service.create_todo(made["list_id"], "the one")
    for url, body in (
        (f"{path(made)}?cmd=ADD", {"title": "x"}),
        (f"{path(made)}?cmd=IMPORT", {"todos": [{"title": "x"}]}),
    ):
        res = await http.post(url, json=body)
        assert res.status_code == 400
        assert "This list holds 1 todos until an email is confirmed" in res.json()["error"]
    assert (await http.get(path(made))).json()["limits"]["todos_per_list"] == 1
    assert titles(made["list_id"]) == ["the one"]


async def test_commands_and_mcp_calls_share_the_lists_budget(http, made, monkeypatch):
    other = lists.create_list()
    monkeypatch.setattr(mcp_server.call_limiter, "max_hits", 3)
    assert (await http.post(path(made), json=INIT, headers=MCP_HEADERS)).status_code == 200
    assert (await http.get(f"{path(made)}?cmd=LIST")).status_code == 200
    assert (await http.get(path(made))).status_code == 200
    for res in (await http.get(f"{path(made)}?cmd=LIST"), await http.post(path(made), json=INIT, headers=MCP_HEADERS)):
        assert res.status_code == 429 and res.headers["retry-after"] == "60"
    assert (await http.get(f"/mcp/{other['agent_token']}?cmd=LIST")).status_code == 200


async def test_a_web_page_cannot_drive_the_commands(http, made, monkeypatch):
    evil = {"Origin": "https://evil.example"}
    res = await http.post(f"{path(made)}?cmd=ADD", json={"title": "x"}, headers=evil)
    assert res.status_code == 403 and res.json()["ok"] is False
    assert (await http.get(path(made), headers=evil)).status_code == 403
    assert service.list_todos(made["list_id"]) == []
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    same = {"Origin": "https://todo.example"}
    assert (await http.post(f"{path(made)}?cmd=ADD", json={"title": "x"}, headers=same)).status_code == 200


async def test_an_oversized_body_is_refused_however_it_is_sent(http, made):
    big = json.dumps({"title": "x", "notes": "y" * agent_cmd.MAX_BODY_BYTES}).encode()
    res = await http.post(f"{path(made)}?cmd=ADD", content=big)
    assert res.status_code == 413  # the declared length, checked before anything else

    async def chunks():
        for start in range(0, len(big), 65536):
            yield big[start : start + 65536]

    res = await http.post(f"{path(made)}?cmd=ADD", content=chunks())
    assert "content-length" not in res.request.headers
    assert res.status_code == 413 and res.json() == {"ok": False, "error": "The body is over 24 MB"}
    assert service.list_todos(made["list_id"]) == []


async def test_provenance_comes_from_the_user_agent_never_the_caller(http, made):
    for agent, client in (
        ("Zapier/2.0", "Zapier"),
        ("claude-code/2.1.0 (cli)", "Claude Code"),
        ("curl/8.5.0", None),
        ("python-httpx/0.28", None),
    ):
        res = await http.post(f"{path(made)}?cmd=ADD", json={"title": agent}, headers={"User-Agent": agent})
        assert (res.json()["todo"]["source"], res.json()["todo"]["source_client"]) == ("agent", client), agent


def test_the_token_in_a_command_address_is_scrubbed_from_logs():
    token = lists.mint_token()
    for address in (
        f"/link/{token}?cmd=LIST&starred=true",
        f"/mcp/{token}?cmd=LIST",
        f"/{token}/mcp?cmd=LIST&status=inbox",
    ):
        clean = logscrub.scrub(address)
        assert token not in clean and clean.replace("***", token) == address
    assert logscrub.scrub(f"/mcp/{token}?cmd=LIST") == "/mcp/***?cmd=LIST"
    assert logscrub.scrub(f"https://todogtd.com/link/{token}") == "https://todogtd.com/link/***"


# ── Hostile input ──────────────────────────────────────


async def test_a_long_user_agent_cannot_stall_the_server(http, made):
    """The product-name regex backtracks quadratically on a run of spaces; the
    input is capped, so a 20 KB User-Agent answers in milliseconds, not seconds."""
    import time

    ua = "a" + " " * 20_000 + "!"
    t = time.perf_counter()
    res = await http.get(f"{path(made)}?cmd=LIST", headers={"User-Agent": ua})
    assert res.status_code == 200
    assert time.perf_counter() - t < 0.5


async def test_a_body_nested_past_the_recursion_limit_is_bad_json_not_a_500(http, made):
    res = await http.post(f"{path(made)}?cmd=ADD", content="[" * 100_000, headers={"content-type": "application/json"})
    assert res.status_code == 400
    assert res.json() == {"ok": False, "error": "The body must be JSON"}
    assert titles(made["list_id"]) == []


# ── LIST narrows by every argument ─────────────────────


async def test_every_list_filter_narrows_and_the_default_page_is_100(http, made):
    lid = made["list_id"]
    area = service.create_area(lid, "Garden")
    a = service.create_todo(
        lid, "Call the vet", status="next_action", context="@calls", star=True, due_date="2026-10-20", people=["Sam"]
    )
    b = service.create_todo(
        lid,
        "Mow the lawn",
        status="next_action",
        context="@home",
        tags=["chores"],
        due_date="2026-10-28",
        area_id=area["id"],
    )
    c = service.create_todo(lid, "Read about soil", status="someday_maybe", notes="loam vs clay")

    async def ids(**args):
        query = "&".join(f"{k}={v}" for k, v in {"cmd": "LIST", **args}.items())
        res = await http.get(f"{path(made)}?{query}")
        assert res.status_code == 200, res.text
        return sorted(t["id"] for t in res.json()["todos"])

    assert await ids(context="@calls") == [a["id"]]
    assert await ids(tag="chores") == [b["id"]]
    assert await ids(person="Sam") == [a["id"]]
    assert await ids(area="Garden") == [b["id"]]
    assert await ids(area=area["id"]) == [b["id"]]
    assert await ids(search="soil") == [c["id"]]
    assert await ids(due_before="2026-10-21") == [a["id"]]
    assert await ids(due_after="2026-10-21") == [b["id"]]
    assert await ids(starred="true") == [a["id"]]
    assert await ids(starred="1") == [a["id"]]
    assert await ids(starred="false") == sorted([b["id"], c["id"]])
    assert await ids(starred="0") == sorted([b["id"], c["id"]])
    assert await ids(status="next_action", context="@home") == [b["id"]]
    # The documented default page: 100, and next_offset says where to continue.
    for n in range(98):
        service.create_todo(lid, f"Filler {n:03d}")
    res = await http.get(f"{path(made)}?cmd=LIST")
    out = res.json()
    assert (out["count"], out["next_offset"]) == (100, 100)
    rest = (await http.get(f"{path(made)}?cmd=LIST&offset=100")).json()
    assert (rest["count"], rest["next_offset"]) == (1, None)
