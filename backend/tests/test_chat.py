"""Projects GTD's Chat (Basecamp's Campfire) and External links (Doors)
(recordings.chat, the chat_line and door types, inbox grouping)."""

import pytest

from backend import boards, inbox, recordings
from backend.common import ValidationError
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    anyio_backend,
    app,
    call,
    connect,
    http,
    link,
    made,
)


@pytest.fixture()
def B(L) -> int:
    return boards.create_board(L, "Kitchen")["id"]


def say(L, B, text, **who):
    return recordings.create(L, B, "chat_line", {"body": text}, **who)


def test_the_chat_reads_oldest_first_and_polls_since(L, B, monkeypatch):
    first = say(L, B, "Morning!")
    say(L, B, "Tiler at 10", source="agent", client="Claude")
    room = recordings.chat(L, B)
    assert [x["body"] for x in room["lines"]] == ["Morning!", "Tiler at 10"]
    assert room["lines"][1]["creator"]["name"] == "Claude" and room["latest"] == room["lines"][1]["id"]
    assert recordings.chat(L, B, since=room["latest"])["lines"] == []
    say(L, B, "Running late")
    assert [x["body"] for x in recordings.chat(L, B, since=room["latest"])["lines"]] == ["Running late"]
    # Earlier pages, newest page first.
    monkeypatch.setattr(recordings, "CHAT_PAGE", 2)
    page = recordings.chat(L, B)
    assert [x["body"] for x in page["lines"]] == ["Tiler at 10", "Running late"] and page["earlier"] is True
    older = recordings.chat(L, B, before=page["lines"][0]["id"])
    assert [x["body"] for x in older["lines"]] == ["Morning!"] and older["earlier"] is False
    # Lines can be boosted, not commented on; an empty one is refused.
    recordings.boost(L, "👍", rec_id=first["id"])
    assert [b["content"] for b in recordings.chat(L, B, before=page["lines"][0]["id"])["lines"][0]["boosts"]] == ["👍"]
    with pytest.raises(ValidationError, match="can't take comments"):
        recordings.comment(L, "hm", rec_id=first["id"])
    with pytest.raises(ValidationError, match="needs some text"):
        say(L, B, "   ")
    # A poll never says there is more above; a line put away leaves the room.
    assert recordings.chat(L, B, since=first["id"])["earlier"] is False
    recordings.update(L, first["id"], {"status": "trashed"})
    assert "Morning!" not in [x["body"] for x in recordings.chat(L, B, before=10**9)["lines"]]
    for bad in ({"since": -1}, {"before": 2**70}, {"since": "x"}):
        with pytest.raises(ValidationError, match="line id"):
            recordings.chat(L, B, **bad)


def test_a_reader_far_behind_catches_up_without_skipping(L, B, monkeypatch):
    monkeypatch.setattr(recordings, "CHAT_PAGE", 1)  # a poll returns at most 4 lines
    start = recordings.chat(L, B)["latest"]
    for n in range(6):
        say(L, B, f"line {n}")
    first = recordings.chat(L, B, since=start)
    assert [x["body"] for x in first["lines"]] == ["line 0", "line 1", "line 2", "line 3"]
    rest = recordings.chat(L, B, since=first["latest"])
    assert [x["body"] for x in rest["lines"]] == ["line 4", "line 5"]


def test_a_busy_chat_is_one_entry_in_new_for_you(L, B):
    for text in ("one", "two", "three"):
        say(L, B, text, source="agent", client="Claude")
    entries = inbox.sidebar(L)["unread"]
    assert len(entries) == 1 and entries[0]["type"] == "project"
    assert entries[0]["last"]["verb"] == "chatted in" and entries[0]["last"]["detail"] == "three"
    assert entries[0]["unread_count"] == 3


def test_external_links_need_a_url(L, B):
    door = recordings.create(L, B, "door", {"title": "Figma", "url": "https://figma.com/file/x"})
    assert door["url"] == "https://figma.com/file/x"
    with pytest.raises(ValidationError, match="needs a url"):
        recordings.create(L, B, "door", {"title": "Nowhere"})
    with pytest.raises(ValidationError, match="http"):
        recordings.create(L, B, "door", {"title": "Bad", "url": "javascript:alert(1)"})
    recordings.set_dock(L, B, [{"tool": t} for t in recordings.TOOLS])
    page = recordings.project(L, B)
    assert [d["title"] for d in page["previews"]["doors"]] == ["Figma"]
    say(L, B, "hi")
    assert [x["body"] for x in recordings.project(L, B)["previews"]["chat"]] == ["hi"]


def test_the_chat_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K", "tools": ["chat"]}).json()["id"]
    assert c.post(f"{api}/projects/{pid}/items", json={"type": "chat_line", "body": "hello"}).status_code == 200
    room = c.get(f"{api}/projects/{pid}/chat").json()
    assert [x["body"] for x in room["lines"]] == ["hello"]
    assert c.get(f"{api}/projects/{pid}/chat?since={room['latest']}").json()["lines"] == []


@pytest.mark.anyio
async def test_an_agent_chats(connect, made, http):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Garage")
        said = (await call(c, "chat_post", project="Garage", text="Starting the clear-out"))["line"]
        assert said["body"] == "Starting the clear-out"
        room = await call(c, "chat_read", project="Garage")
        assert [x["body"] for x in room["lines"]] == ["Starting the clear-out"]
        assert (await call(c, "chat_read", project="Garage", since=room["latest"]))["lines"] == []
    base, ua = f"/mcp/{made['agent_token']}", {"User-Agent": "Claude/1.0"}
    posted = await http.post(f"{base}?cmd=CHAT_POST&project=Garage", json={"text": "Done"}, headers=ua)
    assert posted.json()["line"]["body"] == "Done"
    read = (await http.get(f"{base}?cmd=CHAT&project=Garage", headers=ua)).json()
    assert [x["body"] for x in read["lines"]] == ["Starting the clear-out", "Done"]
    assert (await http.get(f"{base}?cmd=CHAT_POST&project=Garage", headers=ua)).status_code == 405
    for body in ({}, {"text": "   "}):
        assert (await http.post(f"{base}?cmd=CHAT_POST&project=Garage", json=body, headers=ua)).status_code == 400
    assert (await http.get(f"{base}?cmd=CHAT&project=Nowhere", headers=ua)).status_code in (400, 404)
