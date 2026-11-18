"""Projects GTD's Docs & Files, Calendar, Automatic Check-ins and Lineup
(recordings.py types, recordings.folder, schedules.py)."""

import datetime

import pytest

from backend import boards, people, recordings, schedules
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
    return boards.create_board(L, "Kitchen")["id"]


def make(L, B, kind, title="", parent_id=None, source="ui", client=None, **fields):
    if title:
        fields["title"] = title
    return recordings.create(L, B, kind, fields, parent_id=parent_id, source=source, client=client)


# ── Docs & Files ──────────────────────────────────────────────────────────────


def test_folders_nest_and_list_folders_first(L, B):
    plans = make(L, B, "vault", "Plans", color="blue")
    make(L, B, "document", "Budget", parent_id=plans["id"], body="# Money")
    inner = make(L, B, "vault", "Drawings", parent_id=plans["id"])
    make(L, B, "link", "Mood board", parent_id=inner["id"], url="https://example.com/board")
    make(L, B, "document", "Read me")
    top = recordings.folder(L, B)
    assert [(i["type"], i["title"]) for i in top["items"]] == [("vault", "Plans"), ("document", "Read me")]
    assert top["items"][0]["items_count"] == 2
    page = recordings.folder(L, B, inner["id"])
    assert [a["title"] for a in page["above"]] == ["Plans", "Drawings"]
    assert page["items"][0]["url"] == "https://example.com/board"
    with pytest.raises(ValidationError, match="http"):
        make(L, B, "link", "Bad", url="javascript:alert(1)")
    with pytest.raises(ValidationError, match="needs a url"):
        make(L, B, "link", "Nothing")
    with pytest.raises(NotFoundError):
        recordings.folder(L, B, make(L, B, "document", "Not a folder")["id"])
    with pytest.raises(ValidationError, match="can't take comments"):
        recordings.comment(L, "hi", rec_id=plans["id"])
    # A folder can't go inside itself or a folder within it; anywhere else is fine.
    with pytest.raises(ValidationError, match="inside itself"):
        recordings.move(L, plans["id"], parent_id=inner["id"])
    with pytest.raises(ValidationError, match="inside itself"):
        recordings.move(L, plans["id"], parent_id=plans["id"])
    recordings.move(L, inner["id"], board=B)  # back to the top of Docs & Files
    assert [i["title"] for i in recordings.folder(L, B)["items"]][:2] == ["Drawings", "Plans"]
    # Another project's folder is not this project's; sorts and statuses are checked.
    other = boards.create_board(L, "Garage")["id"]
    with pytest.raises(NotFoundError):
        recordings.folder(L, other, plans["id"])
    with pytest.raises(ValidationError, match="sort"):
        recordings.folder(L, B, sort="size")
    assert [i["title"] for i in recordings.folder(L, B, sort="created")["items"]] == [
        "Drawings",
        "Plans",
        "Not a folder",
        "Read me",
    ]
    recordings.update(L, plans["id"], {"status": "archived"})
    assert [i["title"] for i in recordings.folder(L, B, status="archived")["items"]] == ["Plans"]


# ── Calendar ──────────────────────────────────────────────────────────────────


def test_events_repeat_and_the_calendar_merges_what_is_due(L, B):
    make(
        L,
        B,
        "schedule_entry",
        "Standup",
        starts_on="2026-11-02",
        starts_at="09:00",
        ends_at="09:15",
        repeat="every_weekday",
        repeat_until="2026-11-06",
    )
    make(L, B, "schedule_entry", "Tile delivery", starts_on="2026-11-04", ends_on="2026-11-05", highlighted=True)
    make(L, B, "todo", "Call the tiler", due_on="2026-11-03")
    boards.create_card(L, B, "Order grout", due_date="2026-11-05")
    cal = schedules.calendar(L, "2026-11-01", "2026-11-08", board_ref=B)
    standups = [e["on"] for e in cal["events"] if e["title"] == "Standup"]
    assert standups == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    tile = next(e for e in cal["events"] if e["title"] == "Tile delivery")
    assert (tile["on"], tile["until"], tile["all_day"], tile["highlighted"]) == ("2026-11-04", "2026-11-05", True, True)
    assert [(d["kind"], d["title"]) for d in cal["due"]] == [("todo", "Call the tiler"), ("card", "Order grout")]
    assert schedules.calendar(L, "2026-11-01", "2026-11-08", include_due=False)["due"] == []
    with pytest.raises(ValidationError, match="needs starts_on"):
        make(L, B, "schedule_entry", "No date")
    with pytest.raises(ValidationError, match="end before"):
        make(L, B, "schedule_entry", "Backwards", starts_on="2026-11-05", ends_on="2026-11-01")
    with pytest.raises(ValidationError, match="HH:MM"):
        make(L, B, "schedule_entry", "Odd time", starts_on="2026-11-05", starts_at="9am")
    with pytest.raises(ValidationError, match="range"):
        schedules.calendar(L, "2026-01-01", "2027-12-31")


def test_occurrences_by_rule():
    d = datetime.date
    # An event that began in the year 1 costs no more to read than a new one, and the
    # end of the calendar is not an error.
    import time

    began = time.perf_counter()
    assert schedules.occurrences(d(1, 1, 1), "every_day", None, d(2026, 1, 1), d(2026, 1, 3)) == [
        d(2026, 1, 1),
        d(2026, 1, 2),
        d(2026, 1, 3),
    ]
    assert schedules.occurrences(d(1, 1, 31), "every_month", None, d(2026, 2, 1), d(2026, 3, 31)) == [
        d(2026, 2, 28),
        d(2026, 3, 31),
    ]
    assert time.perf_counter() - began < 0.1
    assert schedules.occurrences(d(9999, 12, 1), "every_week", None, d(9999, 12, 1), d(9999, 12, 31))[-1] == d(
        9999, 12, 29
    )
    assert schedules.occurrences(d(9999, 11, 30), "every_month", None, d(9999, 12, 1), d(9999, 12, 31)) == [
        d(9999, 12, 30)
    ]
    assert schedules.occurrences(d(2026, 1, 31), "every_month", None, d(2026, 1, 1), d(2026, 4, 30)) == [
        d(2026, 1, 31),
        d(2026, 2, 28),
        d(2026, 3, 31),
        d(2026, 4, 30),
    ]
    assert schedules.occurrences(d(2026, 11, 2), "every_other_week", None, d(2026, 11, 1), d(2026, 11, 30)) == [
        d(2026, 11, 2),
        d(2026, 11, 16),
        d(2026, 11, 30),
    ]
    assert schedules.occurrences(d(2026, 11, 2), None, None, d(2026, 11, 3), d(2026, 11, 30)) == []


# ── Automatic Check-ins ───────────────────────────────────────────────────────


def test_a_check_in_is_due_on_its_days_until_answered(L, B):
    q = make(L, B, "question", "What did you work on today?")
    assert q["frequency"] == "every_day" and q["days"] == [1, 2, 3, 4, 5] and q["time"] == "09:00"
    me = next(p for p in people.list_people(L) if p["kind"] == "me")["id"]
    tuesday = datetime.date(2030, 1, 1)
    saturday = datetime.date(2030, 1, 5)
    assert [x["title"] for x in schedules.checkins_due(L, me, tuesday)] == ["What did you work on today?"]
    assert schedules.checkins_due(L, me, saturday) == []
    recordings.create(L, None, "answer", {"body": "Tiles.", "group_on": "2030-01-01"}, parent_id=q["id"])
    assert schedules.checkins_due(L, me, tuesday) == []
    recordings.update(L, q["id"], {"paused": True})
    assert schedules.checkins_due(L, me, datetime.date(2030, 1, 2)) == []


@pytest.mark.parametrize(
    "frequency, days, began, asked, not_asked",
    [
        # every week: only the first chosen weekday (Wednesday)
        ("every_week", [3, 5], "2030-01-01", ["2030-01-02", "2030-01-09"], ["2030-01-04", "2030-01-03"]),
        # every other week: from the week it began, skipping the next
        ("every_other_week", [3], "2030-01-01", ["2030-01-02", "2030-01-16"], ["2030-01-09", "2030-01-23"]),
        # every month: the day it began, or the month's last day when shorter
        ("every_month", [1], "2030-01-31", ["2030-01-31", "2030-02-28", "2030-03-31"], ["2030-02-27", "2030-03-30"]),
        # never before it began
        ("every_day", [0, 1, 2, 3, 4, 5, 6], "2030-01-05", ["2030-01-05"], ["2030-01-04"]),
    ],
)
def test_how_often_a_check_in_is_asked(frequency, days, began, asked, not_asked):
    q = {"frequency": frequency, "days": days, "created_at": f"{began}T12:00:00.000Z"}
    assert all(schedules.asked_on(q, datetime.date.fromisoformat(x)) for x in asked)
    assert not any(schedules.asked_on(q, datetime.date.fromisoformat(x)) for x in not_asked)


def test_answers_group_by_day_and_ai_tools_are_asked_too(L, B):
    q = make(L, B, "question", "Any blockers?", assignee_ids=["me"])
    make(L, B, "message", "hello", source="agent", client="Claude")  # Claude is a person now
    recordings.update(L, q["id"], {"assignee_ids": ["me", "Claude"]})
    claude = next(p for p in people.list_people(L) if p["name"] == "Claude")["id"]
    monday = datetime.date(2030, 1, 7)
    assert [x["id"] for x in schedules.checkins_due(L, claude, monday)] == [q["id"]]
    recordings.create(
        L,
        None,
        "answer",
        {"body": "None.", "group_on": "2030-01-07"},
        parent_id=q["id"],
        source="agent",
        client="Claude",
    )
    recordings.create(L, None, "answer", {"body": "Waiting on tile.", "group_on": "2030-01-08"}, parent_id=q["id"])
    days = schedules.answers(L, q["id"])
    assert [(g["day"], [a["body"] for a in g["answers"]]) for g in days] == [
        ("2030-01-08", ["Waiting on tile."]),
        ("2030-01-07", ["None."]),
    ]
    assert [g["day"] for g in schedules.answers(L, q["id"], person_id=claude)] == ["2030-01-07"]
    line = recordings.activity(L)["events"][0]  # an answer names the question it answers
    assert (line["verb"], line["recording_title"]) == ("answered", "Any blockers?")
    with pytest.raises(ValidationError, match="weekdays"):
        recordings.update(L, q["id"], {"days": [9]})
    with pytest.raises(ValidationError, match="can't go inside"):
        make(L, B, "answer", body="loose", parent_id=make(L, B, "message", "m")["id"])
    for blank in ({}, {"body": "  "}):  # an empty answer would silence the reminder
        with pytest.raises(ValidationError, match="needs some text"):
            recordings.create(L, None, "answer", blank, parent_id=q["id"])


def test_the_lineup_lists_projects_with_dates(L, B):
    boards.update_board(L, B, {"starts_on": "2026-10-01", "ends_on": "2026-12-15"})
    later = boards.create_board(L, "Spring")["id"]
    boards.update_board(L, later, {"starts_on": "2027-03-01", "ends_on": "2027-05-01"})
    boards.create_board(L, "No dates")
    assert [p["name"] for p in schedules.lineup(L, "2026-09-01", "2027-06-01")] == ["Kitchen", "Spring"]
    assert [p["name"] for p in schedules.lineup(L, "2026-09-01", "2026-11-01")] == ["Kitchen"]


def test_the_project_page_previews_the_new_tools(L, B):
    recordings.set_dock(L, B, [{"tool": t} for t in recordings.TOOLS])
    make(L, B, "vault", "Plans")
    make(L, B, "question", "Any blockers?")
    page = recordings.project(L, B)
    assert [i["title"] for i in page["previews"]["vault"]] == ["Plans"]
    assert [q["title"] for q in page["previews"]["questionnaire"]] == ["Any blockers?"]
    assert set(page["previews"]["schedule"]) >= {"events", "due"}


def test_the_docs_and_calendar_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K"}).json()["id"]
    folder = c.post(f"{api}/projects/{pid}/items", json={"type": "vault", "title": "Plans"}).json()
    c.post(f"{api}/projects/{pid}/items", json={"type": "document", "title": "Spec", "parent_id": folder["id"]})
    assert [i["title"] for i in c.get(f"{api}/projects/{pid}/docs?folder_id={folder['id']}").json()["items"]] == [
        "Spec"
    ]
    c.post(f"{api}/projects/{pid}/items", json={"type": "schedule_entry", "title": "Demo", "starts_on": "2026-11-02"})
    cal = c.get(f"{api}/calendar?start=2026-11-01&end=2026-11-30").json()
    assert [e["title"] for e in cal["events"]] == ["Demo"]
    q = c.post(f"{api}/projects/{pid}/items", json={"type": "question", "title": "Blockers?"}).json()
    c.post(f"{api}/projects/{pid}/items", json={"type": "answer", "body": "None", "parent_id": q["id"]})
    assert len(c.get(f"{api}/items/{q['id']}/answers").json()["days"]) == 1
    assert "questions" in c.get(f"{api}/checkins/due").json()
    assert c.get(f"{api}/lineup?start=2026-01-01&end=2026-12-31").json() == {"projects": []}
    # The browser sets every field the agent can: a link's address, an event's times, repeat and
    # last day (moving it on the calendar sends both days), a check-in's pause.
    link_item = c.post(
        f"{api}/projects/{pid}/items", json={"type": "link", "title": "Drive", "url": "https://example.com/d"}
    )
    assert link_item.status_code == 200 and link_item.json()["url"] == "https://example.com/d"
    ev = c.post(
        f"{api}/projects/{pid}/items",
        json={
            "type": "schedule_entry",
            "title": "Standup",
            "starts_on": "2026-11-02",
            "ends_on": "2026-11-02",
            "all_day": False,
            "starts_at": "08:30",
            "ends_at": "08:45",
            "repeat": "every_weekday",
        },
    ).json()
    assert (ev["starts_at"], ev["repeat"], ev["all_day"]) == ("08:30", "every_weekday", False)
    assert c.put(f"{api}/items/{ev['id']}", json={"repeat": None}).json()["repeat"] is None  # "Does not repeat"
    moved = c.put(f"{api}/items/{ev['id']}", json={"starts_on": "2026-11-09", "ends_on": "2026-11-09"})
    assert moved.status_code == 200 and (moved.json()["starts_on"], moved.json()["due_on"]) == (
        "2026-11-09",
        "2026-11-09",
    )
    assert (
        c.put(f"{api}/items/{q['id']}", json={"paused": True, "days": [1, 3], "time": "16:00"}).json()["paused"] is True
    )


@pytest.mark.anyio
async def test_an_agent_answers_its_check_in_and_reads_the_calendar(connect, made):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Garage")
        await call(c, "item_create", project="Garage", type="message", title="Hi")  # becomes a person
        q = (
            await call(
                c,
                "item_create",
                project="Garage",
                type="question",
                title="Blockers?",
                assignees=["pytest-client"],
                fields={"days": [0, 1, 2, 3, 4, 5, 6]},
            )
        )["item"]
        due = (await call(c, "activity_list"))["assigned_to_you"]["check_ins"]
        assert [x["id"] for x in due] == [q["id"]]
        await call(c, "item_create", project="Garage", type="answer", parent_id=q["id"], body="None today")
        assert (await call(c, "activity_list"))["assigned_to_you"]["check_ins"] == []
        await call(
            c,
            "item_create",
            project="Garage",
            type="schedule_entry",
            title="Clean out",
            fields={"starts_on": "2026-11-07"},
        )
        cal = await call(c, "calendar_list", start="2026-11-01", end="2026-11-30")
        assert [e["title"] for e in cal["events"]] == ["Clean out"]


@pytest.mark.anyio
async def test_the_calendar_command(http, made):
    base, ua = f"/mcp/{made['agent_token']}", {"User-Agent": "Claude/1.0"}
    for name in ("Garage", "Kitchen"):
        await http.post(f"{base}?cmd=CREATE_BOARD", json={"name": name}, headers=ua)
    await http.post(
        f"{base}?cmd=ADD_ITEM&project=Garage",
        headers=ua,
        json={"type": "schedule_entry", "title": "Clean out", "starts_on": "2026-11-07"},
    )
    await http.post(
        f"{base}?cmd=ADD_ITEM&project=Kitchen",
        headers=ua,
        json={"type": "todo", "title": "Order tile", "due_on": "2026-11-08"},
    )
    whole = (await http.get(f"{base}?cmd=CALENDAR&start=2026-11-01&end=2026-11-30", headers=ua)).json()
    assert [e["title"] for e in whole["events"]] == ["Clean out"] and [d["title"] for d in whole["due"]] == [
        "Order tile"
    ]
    garage = (
        await http.get(
            f"{base}?cmd=CALENDAR&start=2026-11-01&end=2026-11-30&project=Garage&include_due=false", headers=ua
        )
    ).json()
    assert [e["title"] for e in garage["events"]] == ["Clean out"] and garage["due"] == []
    missing = await http.get(f"{base}?cmd=CALENDAR&start=2026-11-01", headers=ua)
    assert missing.status_code == 400 and "end" in missing.json()["error"]
