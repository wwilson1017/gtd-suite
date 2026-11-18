"""Notes GTD: notes (notes.py), the web app's notes API, and the same notes through
the agent link (MCP tools and Agent Commands)."""

import pytest
from fastmcp.exceptions import ToolError

from backend import common, db, lists, notes
from backend.common import ConflictError, NotFoundError, ValidationError
from backend.tests.conftest import confirm_list, turn_on
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    anyio_backend,
    app,
    call,
    connect,
    http,
    link,
    made,
)


def ids(found: dict) -> list[int]:
    return [n["id"] for n in found["notes"]]


# ── Tags ──────────────────────────────────────────────────────────────────────


def test_tags_come_from_the_body_outside_code_and_headings():
    body = (
        "# Heading\n## Another #Work item\nBuy milk #home #Home #a/b #trip-2026.\n"
        "Issue #42, url http://x.com/#frag, e-mail a#b\n"
        "`#inline` code\n```\n#fenced\n```\n~~~py\n#tilde\n~~~\n#after"
    )
    assert notes.tags_of(body) == ["work", "home", "a/b", "trip-2026", "after"]
    assert notes.tags_of("```\n#unclosed fence runs to the end") == []


# ── The service ───────────────────────────────────────────────────────────────


def test_a_note_needs_a_title_or_a_body_and_a_known_colour(L):
    for title, body in (("", ""), ("  ", " \n ")):
        with pytest.raises(ValidationError, match="title or a body"):
            notes.create(L, title, body)
    with pytest.raises(ValidationError, match="Invalid color"):
        notes.create(L, "x", color="mauve")
    note = notes.create(L, body="Hello #there", color="Teal", pinned=True)
    assert (
        note["title"],
        note["tags"],
        note["color"],
        note["pinned"],
        note["version"],
        note["source"],
        note["edited_by"],
    ) == ("", ["there"], "teal", True, 1, "ui", None)


def test_rewriting_needs_the_version_and_a_stale_one_is_refused(L):
    note = notes.create(L, "List", "a")
    with pytest.raises(ValidationError, match="needs the note's version"):
        notes.update(L, note["id"], {"body": "b"})
    notes.append(L, note["id"], "agent was here", by="Claude")
    with pytest.raises(ConflictError, match="version 1; it is now version 2"):
        notes.update(L, note["id"], {"body": "browser text"}, version=1)
    assert notes.get(L, note["id"])["body"] == "a\n\nagent was here"
    # Pin, colour and status need no version; with one, it is checked too.
    pinned = notes.update(L, note["id"], {"pinned": True, "color": "blue"})
    assert (pinned["pinned"], pinned["color"], pinned["version"], pinned["edited_by"]) == (True, "blue", 3, None)
    with pytest.raises(ConflictError):
        notes.update(L, note["id"], {"status": "archived"}, version=2)
    done = notes.update(L, note["id"], {"body": "#new", "title": ""}, version=3, by="Cursor")
    assert (done["body"], done["tags"], done["edited_by"]) == ("#new", ["new"], "Cursor")
    with pytest.raises(ValidationError, match="title or a body"):
        notes.update(L, note["id"], {"body": " "}, version=4)


def test_edit_replaces_text_that_occurs_exactly_once(L):
    note = notes.create(L, body="- [ ] milk\n- [ ] eggs\n- [ ] milk chocolate")
    with pytest.raises(ValidationError, match="not found"):
        notes.edit(L, note["id"], "bread", "x")
    with pytest.raises(ValidationError, match="found 2 times"):
        notes.edit(L, note["id"], "- [ ] milk", "- [x] milk")
    out = notes.edit(L, note["id"], "- [ ] eggs", "- [x] eggs #done", by="Claude")
    assert out["body"] == "- [ ] milk\n- [x] eggs #done\n- [ ] milk chocolate"
    assert (out["tags"], out["version"], out["edited_by"]) == (["done"], 2, "Claude")


def test_append_joins_a_list_item_to_a_list_and_anything_else_after_a_blank_line(L):
    note = notes.create(L, body="- [ ] milk\n\n")
    assert notes.append(L, note["id"], "- [ ] eggs")["body"] == "- [ ] milk\n- [ ] eggs"
    assert notes.append(L, note["id"], "---")["body"] == "- [ ] milk\n- [ ] eggs\n\n---"
    titled = notes.create(L, "Empty")
    assert notes.append(L, titled["id"], "\nfirst\n")["body"] == "first"
    with pytest.raises(ValidationError, match="Nothing to append"):
        notes.append(L, titled["id"], "  \n")


def test_search_orders_pinned_then_title_hits_then_newest(L, freeze):
    freeze("2026-10-01T10:00:00")
    old = notes.create(L, "Paint colours", "for the fence")["id"]
    freeze("2026-10-02T10:00:00")
    body_hit = notes.create(L, "Errands", "buy fence paint")["id"]
    pinned = notes.create(L, "Other", "paint the shed", pinned=True)["id"]
    notes.create(L, "Unrelated", "nothing here")
    assert ids(notes.search(L, "PAINT")) == [pinned, old, body_hit]
    # Every word must be in the title to count as a title hit; neither is, so newest first.
    assert ids(notes.search(L, "paint fence")) == [body_hit, old]
    found = notes.search(L, "", limit=2)
    assert found["count"] == 2 and found["next_offset"] == 2 and found["notes"][0]["id"] == pinned
    # LIKE's wildcards are literal text here.
    notes.create(L, "100% done", "a_b")
    assert len(ids(notes.search(L, "%"))) == 1 and len(ids(notes.search(L, "_"))) == 1


def test_search_by_tag_and_status_and_tag_counts(L):
    a = notes.create(L, body="#home #Work")["id"]
    b = notes.create(L, body="#work")["id"]
    notes.update(L, b, {"status": "archived"})
    assert ids(notes.search(L, tag="#WORK")) == [a]
    assert ids(notes.search(L, tag="work", status="archived")) == [b]
    assert sorted(ids(notes.search(L, status="all"))) == [a, b]
    assert notes.tag_counts(L) == [{"tag": "home", "count": 1}, {"tag": "work", "count": 1}]
    for bad in ({"status": "dropped"}, {"limit": 0}, {"limit": notes.PAGE + 1}, {"offset": -1}):
        with pytest.raises(ValidationError):
            notes.search(L, **bad)


def test_a_snippet_is_one_line_around_the_first_hit():
    body = "x" * 200 + "\nthe needle\nis here" + "y" * 300
    snip = notes.snippet({"body": body}, "NEEDLE")
    assert snip.startswith("…") and snip.endswith("…") and "the needle is here" in snip
    assert notes.snippet({"body": "short\nbody"}, "") == "short body"


def test_the_cap_counts_archived_notes_and_names_the_way_up(L, monkeypatch):
    monkeypatch.setattr(common, "NOTE_ANON_CAP", 2)
    first = notes.create(L, "one")["id"]
    notes.update(L, first, {"status": "archived"})
    notes.create(L, "two")
    with pytest.raises(ValidationError, match="until an email is confirmed"):
        notes.create(L, "three")


def test_a_confirmed_list_and_a_self_host_have_their_own_note_caps(L, monkeypatch):
    monkeypatch.setattr(common, "NOTE_ANON_CAP", 1)
    monkeypatch.setattr(common, "NOTE_VERIFIED_CAP", 2)
    monkeypatch.setattr(common, "NOTE_SELF_HOST_CAP", 3)
    confirm_list(L)
    notes.create(L, "one")
    notes.create(L, "two")
    with pytest.raises(ValidationError, match="at most 2 notes"):
        notes.create(L, "three")
    monkeypatch.delenv("OPEN_SIGNUP")
    notes.create(L, "three")
    with pytest.raises(ValidationError, match="at most 3 notes"):
        notes.create(L, "four")


def test_a_note_is_only_its_own_lists(L):
    note = notes.create(L, "mine")["id"]
    other = lists.create_list("UTC")["list_id"]
    for attempt in (
        lambda: notes.get(other, note),
        lambda: notes.update(other, note, {"pinned": True}),
        lambda: notes.edit(other, note, "mine", "theirs"),
        lambda: notes.append(other, note, "theirs"),
    ):
        with pytest.raises(NotFoundError):
            attempt()
    assert notes.search(other)["notes"] == []


# ── The web app's API ─────────────────────────────────────────────────────────


def test_the_notes_api_round_trip(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    note = c.post(f"{api}/notes", json={"title": "Trip", "body": "- [ ] tickets #travel"}).json()
    assert c.post(f"{api}/notes", json={}).status_code == 400
    assert c.put(f"{api}/notes/{note['id']}", json={"body": "x"}).status_code == 400
    notes.append(made["list_id"], note["id"], "- [ ] hotel", by="Claude")
    stale = c.put(f"{api}/notes/{note['id']}", json={"body": "x", "version": note["version"]})
    assert stale.status_code == 409 and stale.headers["cache-control"] == "no-store"
    fresh = c.get(f"{api}/notes/{note['id']}").json()
    assert fresh["edited_by"] == "Claude" and fresh["body"].endswith("- [ ] hotel")
    ticked = c.put(
        f"{api}/notes/{note['id']}", json={"body": fresh["body"].replace("[ ] hotel", "[x] hotel"), "version": 2}
    )
    assert ticked.status_code == 200 and ticked.json()["edited_by"] is None
    assert c.put(f"{api}/notes/{note['id']}", json={"pinned": True}).json()["pinned"] is True
    listed = c.get(f"{api}/notes?q=tickets").json()
    assert ids(listed) == [note["id"]] and listed["notes"][0]["body"]  # whole notes here
    assert c.get(f"{api}/notes/tags").json() == {"tags": [{"tag": "travel", "count": 1}]}
    assert c.get(f"{api}/notes?limit=0").status_code == 422
    # Another list's browser cannot see it; a browser on another list is refused.
    other = new_list()
    assert other["client"].get(f"{api}/notes/{note['id']}").status_code == 404
    assert c.get(f"{api}/notes", headers={"X-List": "999"}).status_code == 409
    cross = c.post(f"{api}/notes", json={"title": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403


# ── The agent link ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_an_agent_works_notes_over_mcp(connect, made):
    lid = made["list_id"]
    async with connect(link(made)) as c:
        note = (await call(c, "note_create", title="Groceries", body="- [ ] milk\n\n#home"))["note"]
        assert (note["source"], note["source_client"], note["edited_by"]) == ("agent", "pytest-client", "pytest-client")
        found = await call(c, "note_search", query="milk")
        assert found["count"] == 1 and "body" not in found["notes"][0]
        assert found["notes"][0]["snippet"] == "- [ ] milk #home"
        await call(c, "note_append", id=note["id"], text="- [ ] eggs")
        await call(c, "note_edit", id=note["id"], old_str="[ ] milk", new_str="[x] milk")
        assert notes.get(lid, note["id"])["body"] == "- [x] milk\n\n#home\n\n- [ ] eggs"
        with pytest.raises(ToolError, match="it is now version 3"):
            await call(c, "note_update", id=note["id"], expected_version=1, body="gone")
        with pytest.raises(ToolError, match="needs the note's version"):
            await call(c, "note_update", id=note["id"], body="gone")
        read = (await call(c, "note_get", id=note["id"]))["note"]
        await call(
            c, "note_update", id=note["id"], expected_version=read["version"], body="#home all bought", archived=True
        )
        assert (await call(c, "note_search"))["notes"] == []
        archived = await call(c, "note_search", status="archived")
        assert archived["notes"][0]["tags"] == ["home"]
        with pytest.raises(ToolError, match="Note not found"):
            await call(c, "note_get", id=999)


@pytest.mark.anyio
async def test_note_commands_read_by_get_and_write_by_post(http, made):
    base = f"/link/{made['agent_token']}"
    agent = {"User-Agent": "n8n/1.73"}

    async def ok(method, query, body=None):
        res = await http.request(method, f"{base}?{query}", json=body, headers=agent)
        assert res.status_code == 200, (query, res.text)
        return res.json()

    note = (await ok("POST", "cmd=ADD_NOTE", {"title": "Ideas", "body": "one #idea"}))["note"]
    assert (note["source_client"], note["edited_by"]) == ("n8n", "n8n")
    assert (await http.get(f"{base}?cmd=ADD_NOTE")).status_code == 405
    await ok("POST", f"cmd=APPEND_NOTE&id={note['id']}", {"text": "two"})
    await ok("POST", f"cmd=EDIT_NOTE&id={note['id']}", {"old_str": "one", "new_str": "1"})
    assert (await ok("GET", f"cmd=NOTE&id={note['id']}"))["note"]["body"] == "1 #idea\n\ntwo"
    stale = await http.post(f"{base}?cmd=UPDATE_NOTE&id={note['id']}", json={"version": 1, "body": "x"}, headers=agent)
    assert stale.status_code == 400 and "it is now version 3" in stale.json()["error"]
    unknown = await http.post(f"{base}?cmd=EDIT_NOTE&id={note['id']}", json={"old": "1"})
    assert unknown.status_code == 400 and "Unknown fields" in unknown.json()["error"]
    found = await ok("GET", "cmd=NOTES&tag=idea")
    assert found["notes"][0]["snippet"] == "1 #idea two" and "body" not in found["notes"][0]
    assert (await ok("POST", f"cmd=ARCHIVE_NOTE&id={note['id']}"))["note"]["status"] == "archived"
    assert (await ok("GET", "cmd=NOTES"))["notes"] == []
    exported = await ok("GET", "cmd=EXPORT_NOTES")
    assert exported["notes"][0]["body"] == "1 #idea\n\ntwo" and exported["next_offset"] is None
    restored = await ok("POST", f"cmd=UPDATE_NOTE&id={note['id']}", {"status": "active"})
    assert restored["note"]["status"] == "active"


@pytest.mark.anyio
async def test_notes_off_means_no_note_tools_or_commands(connect, http, app, monkeypatch):
    monkeypatch.setenv("NOTES_BASE_URL", "https://notes.example")
    todo_only = lists.create_list("UTC")
    async with connect(link(todo_only)) as c:
        assert not [t.name for t in await c.list_tools() if t.name.startswith("note_")]
    res = await http.get(f"/link/{todo_only['agent_token']}?cmd=NOTES")
    assert res.status_code == 400 and "Notes GTD is off" in res.json()["error"]
    turn_on(todo_only["list_id"], "notes")
    async with connect(link(todo_only)) as c:
        assert (await call(c, "note_search"))["notes"] == []
    # Off again: the notes stay, out of reach of the link.
    notes.create(todo_only["list_id"], "kept")
    with db.transaction() as conn:
        lists.set_app_in(conn, todo_only["list_id"], "notes", False)
    assert notes.search(todo_only["list_id"])["count"] == 1
    assert (await http.get(f"/link/{todo_only['agent_token']}?cmd=NOTES")).status_code == 400
