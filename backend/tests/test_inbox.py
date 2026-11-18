"""New for you, Bubble Up, reminders, Up Next, My Drafts and My Boosts (inbox.py)."""

import datetime
import time

import pytest

from backend import boards, common, db, inbox, recordings
from backend.common import NotFoundError, ValidationError
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
    return boards.create_board(L, "Kitchen")["id"]  # by me: my own work is never new for me


def claude(L, B, kind, title="", **kw):
    fields = {"title": title, **kw} if title else kw
    return recordings.create(L, B, kind, fields, source="agent", client="Claude")


def test_what_ai_tools_did_is_new_for_me_one_entry_per_item(L, B):
    msg = recordings.create(L, B, "message", {"title": "Plan"})  # mine
    recordings.comment(L, "Looks good", rec_id=msg["id"], source="agent", client="Claude")
    recordings.comment(L, "One more thing", rec_id=msg["id"], source="agent", client="Codex")
    claude(L, B, "todo", "Call the tiler")
    side = inbox.sidebar(L)
    by_title = {i["title"]: i for i in side["unread"]}
    assert set(by_title) == {"Plan", "Call the tiler"} and side["unread_count"] == 2
    assert by_title["Plan"]["unread_count"] == 2
    assert by_title["Plan"]["people"] == ["Codex", "Claude"]  # newest first
    assert by_title["Plan"]["last"]["verb"] == "commented on"
    inbox.mark(L, True, rec_id=msg["id"])
    side = inbox.sidebar(L)
    assert [i["title"] for i in side["unread"]] == ["Call the tiler"]
    assert [i["title"] for i in side["previous"]] == ["Plan"]
    time.sleep(0.002)  # a comment in the very millisecond of the read counts as read (inbox.sidebar)
    recordings.comment(L, "And again", rec_id=msg["id"], source="agent", client="Claude")
    assert {i["title"] for i in inbox.sidebar(L)["unread"]} == {"Plan", "Call the tiler"}
    inbox.mark_all_read(L)
    assert inbox.sidebar(L)["unread"] == [] and inbox.unread_count(L) == 0
    inbox.mark(L, False, rec_id=msg["id"])
    assert [i["title"] for i in inbox.sidebar(L)["unread"]] == ["Plan"]


def test_dont_notify_me_mutes_an_item_or_a_whole_project(L, B):
    msg = recordings.create(L, B, "message", {"title": "Plan"})
    recordings.comment(L, "Looks good", rec_id=msg["id"], source="agent", client="Claude")
    claude(L, B, "todo", "Call the tiler")
    inbox.mute(L, True, rec_id=msg["id"])
    side = inbox.sidebar(L)
    assert [i["title"] for i in side["unread"]] == ["Call the tiler"]
    assert [i["title"] for i in side["previous"] if i["muted"]] == ["Plan"]
    time.sleep(0.002)
    recordings.comment(L, "Still there?", rec_id=msg["id"], source="agent", client="Claude")
    assert [i["title"] for i in inbox.sidebar(L)["unread"]] == ["Call the tiler"]  # still quiet
    assert inbox.muted(L, rec_id=msg["id"]) is True and inbox.muted(L, board_id=B) is False
    inbox.mute(L, False, rec_id=msg["id"])
    assert "Plan" not in [i["title"] for i in inbox.sidebar(L)["unread"]]  # muting read it: nothing old comes back
    time.sleep(0.002)
    recordings.comment(L, "Now?", rec_id=msg["id"], source="agent", client="Claude")
    assert {i["title"] for i in inbox.sidebar(L)["unread"]} == {"Plan", "Call the tiler"}
    # A whole project's bell; another project still speaks.
    inbox.mute(L, True, board_id=B)
    assert inbox.sidebar(L)["unread"] == [] and inbox.unread_count(L) == 0
    plan = next(i for i in inbox.sidebar(L)["previous"] if i["title"] == "Plan")
    assert plan["muted"] and plan["project_muted"]  # through its project: the bell there turns it back on
    claude(L, B, "todo", "Order grout")
    claude(L, boards.create_board(L, "Garage")["id"], "todo", "Sweep")
    assert [i["title"] for i in inbox.sidebar(L)["unread"]] == ["Sweep"]
    inbox.mute(L, False, board_id=B)  # a project unmuted: what its items had meanwhile, to catch up on
    assert "Order grout" in [i["title"] for i in inbox.sidebar(L)["unread"]]
    inbox.mute(L, True, board_id=B)
    inbox.mark(L, False, rec_id=msg["id"])  # marked unread by hand: shown, muted or not
    assert {i["title"] for i in inbox.sidebar(L)["unread"]} == {"Sweep", "Plan"}
    with pytest.raises(NotFoundError):
        inbox.mute(L, True, rec_id=10**9)
    # Bubbled up already, then muted: it leaves Bubbled up too.
    todo = claude(L, boards.create_board(L, "Shed")["id"], "todo", "Oil the hinges")
    inbox.bubble_up(L, "now", rec_id=todo["id"])
    assert [i["title"] for i in inbox.sidebar(L)["bubbled"]] == ["Oil the hinges"]
    inbox.mute(L, True, rec_id=todo["id"])
    assert inbox.sidebar(L)["bubbled"] == []


def test_step_12_adds_readings_muted(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    db.get_db().execute("ALTER TABLE readings DROP COLUMN muted")
    db.close_db()
    db.init_db()
    assert "muted" in {r["name"] for r in db.get_db().execute("PRAGMA table_info(readings)")}


def test_the_mute_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K"}).json()["id"]
    assert c.post(f"{api}/inbox/mute", json={"project_id": pid}).json() == {"muted": True}
    assert c.get(f"{api}/inbox/mute?project_id={pid}").json() == {"muted": True}
    assert c.post(f"{api}/inbox/mute", json={"project_id": pid, "muted": False}).json() == {"muted": False}
    assert c.post(f"{api}/inbox/mute", json={}).status_code == 400
    assert c.get(f"{api}/inbox/mute").status_code == 400
    card = c.post(f"{api}/boards/{pid}/cards", json={"title": "Tiles"}).json()
    assert c.post(f"{api}/inbox/mute", json={"card_id": card["id"]}).json() == {"muted": True}
    other = new_list()
    theirs = other["client"].post(f"{other['api']}/boards", json={"name": "Theirs"}).json()["id"]
    assert c.post(f"{api}/inbox/mute", json={"project_id": theirs}).status_code == 404


def test_another_accounts_activity_never_shows(L, B):
    from backend import lists

    other = lists.create_list("UTC")["list_id"]
    theirs = boards.create_board(other, "Theirs")["id"]
    recordings.create(other, theirs, "todo", {"title": "Their secret"}, source="agent", client="Claude")
    boards.create_card(other, theirs, "Their card", source="agent", source_client="Claude")
    claude(L, B, "todo", "Mine")
    side = inbox.sidebar(L)
    assert [i["title"] for i in side["unread"]] == ["Mine"]
    assert all(i["title"] not in ("Their secret", "Their card", "Theirs") for i in side["previous"])


def test_cards_and_drafts_and_trash(L, B):
    card = boards.create_card(L, B, "Cabinets", source="agent", source_client="Claude")
    boards.move_card(L, card["id"], "In progress", source="agent", client="Claude")
    draft = claude(L, B, "message", "Draft", status="drafted")
    gone = claude(L, B, "message", "Trashed")
    recordings.update(L, gone["id"], {"status": "trashed"})
    side = inbox.sidebar(L)
    assert [(i["title"], i["type"], i["unread_count"]) for i in side["unread"]] == [("Cabinets", "card", 2)]
    assert draft["id"] not in [i["recording_id"] for i in side["unread"]]
    boards.update_card(L, card["id"], {"status": "archived"}, source="agent", client="Claude")
    assert inbox.sidebar(L)["unread"] == []  # an archived card has nothing to open


def test_bubble_up_brings_an_item_back(L, B):
    todo = claude(L, B, "todo", "Measure")
    inbox.bubble_up(L, "tomorrow", rec_id=todo["id"])
    side = inbox.sidebar(L)
    assert side["bubbled"] == [] and side["unread"] == [] and side["scheduled_bubble_ups"] == 1
    later = common.utcnow() + datetime.timedelta(days=2)
    side = inbox.sidebar(L, now=later)
    assert [i["title"] for i in side["bubbled"]] == ["Measure"] and side["unread_count"] == 1
    inbox.bubble_up(L, None, rec_id=todo["id"])
    assert inbox.sidebar(L, now=later)["bubbled"] == []
    # Once its time has come, reading it (or Mark all read) lets it go.
    inbox.bubble_up(L, "now", rec_id=todo["id"])
    assert inbox.unread_count(L) == 1
    inbox.mark(L, True, rec_id=todo["id"])
    assert inbox.sidebar(L)["bubbled"] == [] and inbox.unread_count(L) == 0
    inbox.bubble_up(L, "now", rec_id=todo["id"])
    inbox.mark_all_read(L)
    assert inbox.unread_count(L) == 0
    with pytest.raises(ValidationError):
        inbox.bubble_up(L, "someday", rec_id=todo["id"])
    with pytest.raises(NotFoundError):
        inbox.mark(L, True, rec_id=999999)


def test_an_old_bubble_up_on_a_trashed_or_archived_thing_stays_away(L, B, monkeypatch):
    monkeypatch.setattr(inbox, "INBOX_EVENTS", 0)  # too old for the event window: listed from its reading
    todo = claude(L, B, "todo", "Measure")
    card = boards.create_card(L, B, "Order tile")
    inbox.bubble_up(L, "tomorrow", rec_id=todo["id"])
    inbox.bubble_up(L, "tomorrow", card_id=card["id"])
    later = common.utcnow() + datetime.timedelta(days=2)
    assert {i["title"] for i in inbox.sidebar(L, now=later)["bubbled"]} == {"Measure", "Order tile"}
    recordings.update(L, todo["id"], {"status": "trashed"})
    boards.update_card(L, card["id"], {"status": "archived"})
    side = inbox.sidebar(L, now=later)
    assert side["bubbled"] == [] and side["unread_count"] == 0


def test_my_own_work_marked_unread_shows_as_unread(L, B):
    mine = recordings.create(L, B, "todo", {"title": "Mine"})  # no one else's event on it
    inbox.mark(L, False, rec_id=mine["id"])
    side = inbox.sidebar(L)
    assert [(i["title"], i["unread_count"]) for i in side["unread"]] == [("Mine", 1)] and side["unread_count"] == 1
    inbox.mark(L, True, rec_id=mine["id"])
    assert inbox.unread_count(L) == 0


def test_bubble_up_times_land_at_nine_local():
    monday_noon = datetime.datetime(2026, 10, 12, 17, 0, tzinfo=datetime.timezone.utc)  # 12:00 in Chicago
    assert inbox.bubble_up_at("tomorrow", "America/Chicago", monday_noon) == "2026-10-13T14:00:00.000Z"
    assert inbox.bubble_up_at("this_weekend", "America/Chicago", monday_noon) == "2026-10-17T14:00:00.000Z"
    assert inbox.bubble_up_at("next_week", "America/Chicago", monday_noon) == "2026-10-19T14:00:00.000Z"
    assert inbox.bubble_up_at("later_today", "America/Chicago", monday_noon) == "2026-10-12T20:00:00.000Z"
    assert inbox.bubble_up_at("2026-11-01", "UTC", monday_noon) == "2026-11-01T09:00:00.000Z"
    assert inbox.bubble_up_at("", "UTC") is None


def test_due_lists_my_work_due_by_tomorrow(L, B):
    today = common.business_today("America/Chicago")
    soon = (today + datetime.timedelta(days=1)).isoformat()
    later = (today + datetime.timedelta(days=9)).isoformat()
    recordings.create(L, B, "todo", {"title": "Soon", "assignee_ids": ["me"], "due_on": soon})
    recordings.create(L, B, "todo", {"title": "Later", "assignee_ids": ["me"], "due_on": later})
    boards.create_card(
        L, B, "Overdue card", assignee_ids=["me"], due_date=(today - datetime.timedelta(days=2)).isoformat()
    )
    assert [d["title"] for d in inbox.due(L)] == ["Overdue card", "Soon"]


def test_up_next_keeps_my_order_and_drops_finished_work(L, B):
    a = recordings.create(L, B, "todo", {"title": "A", "assignee_ids": ["me"]})
    card = boards.create_card(L, B, "C", assignee_ids=["me"])
    assert [i["title"] for i in inbox.set_up_next(L, [["c", card["id"]], ["r", a["id"]]])] == ["C", "A"]
    recordings.complete(L, a["id"])
    assert [i["title"] for i in inbox.up_next(L)] == ["C"]
    # Work handed to someone else, or in a project put away, leaves Up Next too.
    b = recordings.create(L, B, "todo", {"title": "B", "assignee_ids": ["me"]})
    inbox.set_up_next(L, [["c", card["id"]], ["r", b["id"]]])
    boards.update_card(L, card["id"], {"assignee_ids": []})
    assert [i["title"] for i in inbox.up_next(L)] == ["B"]
    boards.update_board(L, B, {"status": "archived"})
    assert inbox.up_next(L) == []
    with pytest.raises(ValidationError):
        inbox.set_up_next(L, [["x", 1]])
    with pytest.raises(NotFoundError):
        inbox.set_up_next(L, [["r", 999999]])


def test_my_drafts_and_my_boosts(L, B):
    recordings.create(L, B, "message", {"title": "Mine", "status": "drafted"})
    claude(L, B, "message", "Claude's", status="drafted")
    assert {d["title"] for d in inbox.drafts(L)} == {"Mine", "Claude's"}
    msg = recordings.create(L, B, "message", {"title": "Posted"})
    recordings.boost(L, "🎉", rec_id=msg["id"], source="agent", client="Claude")
    recordings.boost(L, "👍", rec_id=msg["id"])  # my own boost is not for me
    assert [(b["content"], b["booster"]["name"], b["title"]) for b in inbox.my_boosts(L)] == [
        ("🎉", "Claude", "Posted")
    ]
    mine = boards.create_card(L, B, "My card")
    theirs = boards.create_card(L, B, "Claude's card", source="agent", source_client="Claude")
    recordings.boost(L, "👍", card_id=mine["id"], source="agent", client="Claude")
    recordings.boost(L, "👍", card_id=theirs["id"], source="agent", client="Codex")
    gone = recordings.boost(L, "✨", rec_id=msg["id"], source="agent", client="Codex")
    recordings.unboost(L, gone["id"])
    assert [b["title"] for b in inbox.my_boosts(L)] == ["My card", "Posted"]


def test_the_inbox_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    board = c.post(f"{api}/boards", json={"name": "K"}).json()
    item = c.post(
        f"{api}/projects/{board['id']}/items", json={"type": "todo", "title": "T", "assignee_ids": ["me"]}
    ).json()
    assert c.get(f"{api}/inbox/count").json() == {"unread": 0}
    assert c.post(f"{api}/inbox/bubble-up", json={"item_id": item["id"], "when": "now"}).status_code == 200
    assert [i["title"] for i in c.get(f"{api}/inbox").json()["bubbled"]] == ["T"]
    assert c.post(f"{api}/inbox/read", json={"item_id": item["id"], "read": False}).json() == {"read": False}
    assert c.post(f"{api}/inbox/read-all").status_code == 200
    assert c.put(f"{api}/up-next", json={"items": [["r", item["id"]]]}).json()["items"][0]["title"] == "T"
    assert c.get(f"{api}/drafts").json() == {"items": []}
    assert c.post(f"{api}/inbox/read", json={}).status_code == 400
    assert c.post(f"{api}/inbox/read", json={"item_id": item["id"], "card_id": 1}).status_code == 400
    assert c.post(f"{api}/inbox/bubble-up", json={"item_id": item["id"], "when": "someday"}).status_code == 400
    other = new_list()["client"]
    assert other.post(f"{api}/inbox/read", json={"item_id": item["id"]}).status_code == 404


def test_step_10_adds_up_next_to_an_older_database(tmp_path, monkeypatch):
    import sqlite3
    from backend import db, lists

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_SIGNUP", "true")
    db.init_db()
    list_id = lists.create_list("UTC")["list_id"]
    boards.create_board(list_id, "Old")  # makes "me"
    db.close_db()
    conn = sqlite3.connect(tmp_path / "todo.db")
    conn.execute("ALTER TABLE people DROP COLUMN up_next")
    conn.close()
    db.init_db()
    try:
        assert inbox.up_next(list_id) == []
    finally:
        db.close_db()


@pytest.mark.anyio
async def test_activity_command_takes_since_and_lists_your_assignments(http, made):
    base = f"/mcp/{made['agent_token']}"
    ua = {"User-Agent": "Claude/1.0"}
    await http.post(f"{base}?cmd=CREATE_BOARD", json={"name": "Trip"}, headers=ua)
    first = (await http.get(f"{base}?cmd=ACTIVITY", headers=ua)).json()
    item = (
        await http.post(
            f"{base}?cmd=ADD_ITEM&project=Trip",
            json={"type": "todo", "title": "Book", "assignees": ["Claude"]},
            headers=ua,
        )
    ).json()["item"]
    new = (await http.get(f"{base}?cmd=ACTIVITY&since={first['latest']}", headers=ua)).json()
    assert [e["action"] for e in new["events"]] == ["created"]
    assert [t["id"] for t in new["assigned_to_you"]["todos"]] == [item["id"]]


@pytest.mark.anyio
async def test_an_agent_reads_what_is_new_and_what_is_its_own(connect, made):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Garage")
        first = await call(c, "activity_list")
        todo = (
            await call(c, "item_create", project="Garage", type="todo", title="Sweep", assignees=["pytest-client"])
        )["item"]
        mine = await call(c, "activity_list", since=first["latest"])
        assert [e["action"] for e in mine["events"]] == ["created"]
        assert [t["id"] for t in mine["assigned_to_you"]["todos"]] == [todo["id"]]
