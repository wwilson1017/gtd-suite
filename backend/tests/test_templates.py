"""Projects GTD's copies, repeats, scheduled posts and templates (recordings.py
copy/next_due/publish_scheduled, boards.py copy_card and card repeats,
templates.py, migration step 11)."""

import datetime
import sqlite3

import pytest
from fastmcp.exceptions import ToolError

from backend import boards, common, db, people, recordings, reports, schedules, templates
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


def make(L, B, kind, title="", parent_id=None, **fields):
    if title:
        fields["title"] = title
    return recordings.create(L, B, kind, fields, parent_id=parent_id)


def today() -> datetime.date:
    return common.business_today("America/Chicago")


def day(n: int) -> str:
    return (today() + datetime.timedelta(days=n)).isoformat()


# ── Copies ────────────────────────────────────────────────────────────────────


def test_copying_a_list_takes_what_is_under_it_but_not_the_conversation(L, B):
    tl = make(L, B, "todolist", "Demolition")
    group = make(L, B, "todolist_group", "Walls", parent_id=tl["id"])
    todo = make(L, B, "todo", "Rip out tiles", parent_id=group["id"], due_on="2026-11-02")
    make(L, B, "step", "Rent a skip", parent_id=todo["id"])
    done = make(L, B, "todo", "Measure", parent_id=tl["id"])
    recordings.complete(L, done["id"])
    recordings.comment(L, "Careful with the pipes", rec_id=todo["id"])
    garage = boards.create_board(L, "Garage")["id"]
    copy = recordings.copy(L, tl["id"], board=garage)
    assert (copy["board_id"], copy["title"]) == (garage, "Demolition") and copy["id"] != tl["id"]
    page = recordings.thread(L, copy["id"])
    copied_group = next(k for k in page["children"] if k["type"] == "todolist_group")
    copied_todo = copied_group["todos"][0]
    assert (copied_todo["title"], copied_todo["due_on"]) == ("Rip out tiles", "2026-11-02")
    assert recordings.thread(L, copied_todo["id"])["comments"] == []
    assert [s["title"] for s in recordings.children(L, copied_todo["id"])] == ["Rent a skip"]
    assert [t["title"] for t in page["completed"]] == ["Measure"]  # a plain copy keeps what was done
    assert recordings.activity(L, board_id=garage)["events"][0]["verb"] == "copied"
    # Same place by default; under a parent; things that can't be copied.
    again = recordings.copy(L, todo["id"])
    assert again["parent_id"] == group["id"]
    other = make(L, B, "todolist", "Other")
    assert recordings.copy(L, todo["id"], parent_id=other["id"])["parent_id"] == other["id"]
    for bad in (make(L, B, "step", "s", parent_id=todo["id"]), recordings.comment(L, "x", rec_id=todo["id"])):
        with pytest.raises(ValidationError, match="can't be copied"):
            recordings.copy(L, bad["id"])
    assert recordings.copy(L, todo["id"], board=garage)["parent_id"] is None  # a loose to-do there
    with pytest.raises(ValidationError, match="under a parent"):
        recordings.copy(L, group["id"], board=garage)


def test_a_folder_copies_with_its_contents(L, B):
    folder = make(L, B, "vault", "Plans")
    make(L, B, "document", "Spec", parent_id=folder["id"], body="# Spec")
    inner = make(L, B, "vault", "Drawings", parent_id=folder["id"])
    copy = recordings.copy(L, folder["id"])
    assert [i["title"] for i in recordings.folder(L, B, copy["id"])["items"]] == ["Drawings", "Spec"]
    # Into itself, or into a folder inside it: what was there is copied once.
    into_self = recordings.copy(L, folder["id"], parent_id=folder["id"])
    assert [i["title"] for i in recordings.folder(L, B, into_self["id"])["items"]] == ["Drawings", "Spec"]
    into_inner = recordings.copy(L, folder["id"], parent_id=inner["id"])
    assert into_inner["parent_id"] == inner["id"]


def test_a_copy_counts_against_the_cap_whole(L, B, monkeypatch):
    tl = make(L, B, "todolist", "Big")
    for n in range(3):
        make(L, B, "todo", f"T{n}", parent_id=tl["id"])
    have = len(recordings.list_items(L, B, "todolist")) + 3
    monkeypatch.setattr(common, "recording_cap_for", lambda verified, hosted, plan=None: have + 3)
    with pytest.raises(ValidationError, match="at most|holds"):
        recordings.copy(L, tl["id"])  # 4 more would pass the cap
    monkeypatch.setattr(common, "recording_cap_for", lambda verified, hosted, plan=None: have + 4)
    assert recordings.copy(L, tl["id"])["title"] == "Big"


def test_copies_and_templates_stay_in_their_own_account(L, B, new_list):
    other = new_list()["list_id"]
    theirs = boards.create_board(other, "Theirs")["id"]
    boards.update_board(other, theirs, {"template": True})
    their_list = recordings.create(other, theirs, "todolist", {"title": "Private"})
    their_card = boards.create_card(other, theirs, "Private card")
    mine = make(L, B, "todolist", "Mine")
    with pytest.raises(NotFoundError):
        recordings.copy(L, their_list["id"])
    with pytest.raises(NotFoundError):
        recordings.copy(L, mine["id"], board=theirs)
    with pytest.raises(NotFoundError):
        templates.make_project(L, theirs, "Stolen")
    with pytest.raises(NotFoundError):
        boards.copy_card(L, their_card["id"])
    with pytest.raises(NotFoundError):
        boards.copy_card(other, their_card["id"], board=B)
    assert [b["name"] for b in boards.list_boards(L)] == ["Kitchen"]


# ── Repeats ───────────────────────────────────────────────────────────────────


def test_next_due_by_rule():
    t = datetime.date(2026, 11, 4)  # a Wednesday
    assert recordings.next_due("every_week", "2026-11-02", t) == "2026-11-09"
    assert recordings.next_due("every_weekday", "2026-11-06", t) == "2026-11-09"  # Friday to Monday
    assert recordings.next_due("every_month", "2026-01-31", datetime.date(2026, 1, 1)) == "2026-02-28"
    assert recordings.next_due("every_day", "2026-10-01", t) == "2026-11-05"  # never already past
    assert recordings.next_due("every_other_week", None, t) == "2026-11-18"
    with pytest.raises(ValidationError):
        recordings.next_due("hourly", None, t)
    with pytest.raises(ValidationError, match="out of range"):
        recordings.next_due("every_year", "9999-06-01", datetime.date(9999, 1, 1))


def test_finishing_a_repeating_to_do_adds_the_next(L, B):
    tl = make(L, B, "todolist", "Chores")
    todo = make(
        L,
        B,
        "todo",
        "Clean the oven",
        parent_id=tl["id"],
        due_on=day(0),
        starts_on=day(-1),
        repeat="every_week",
        assignee_ids=["me"],
    )
    make(L, B, "step", "Degrease", parent_id=todo["id"])
    recordings.complete(L, todo["id"])
    open_ = [t for t in recordings.children(L, tl["id"]) if not t["completed"]]
    assert len(open_) == 1
    nxt = open_[0]
    assert (nxt["title"], nxt["due_on"], nxt["starts_on"], nxt["repeat"]) == (
        "Clean the oven",
        day(7),
        day(6),
        "every_week",
    )
    assert [a["kind"] for a in nxt["assignees"]] == ["me"]
    assert not recordings.children(L, nxt["id"])[0]["completed"]
    assert recordings.get(L, todo["id"]).get("repeat") is None  # re-opening the old one adds none
    recordings.complete(L, todo["id"], False)
    recordings.complete(L, todo["id"])
    assert len([t for t in recordings.children(L, tl["id"]) if not t["completed"]]) == 1
    # At the item cap the next one has nowhere to go: finishing is refused, nothing lost.
    capped = make(L, B, "todo", "Capped", repeat="every_day")
    have = db.get_db().execute("SELECT COUNT(*) FROM recordings WHERE list_id = ?", (L,)).fetchone()[0]
    real = common.recording_cap_for
    common.recording_cap_for = lambda verified, hosted, plan=None: have
    try:
        with pytest.raises(ValidationError):
            recordings.complete(L, capped["id"])
        assert recordings.get(L, capped["id"])["completed"] is False
    finally:
        common.recording_cap_for = real
    loose = make(L, B, "todo", "Water plants", repeat="every_day")  # no due date: tomorrow
    recordings.complete(L, loose["id"])
    assert [
        t["due_on"] for t in recordings.list_items(L, B, "todo") if not t["completed"] and t["title"] == "Water plants"
    ] == [day(1)]
    with pytest.raises(ValidationError, match="repeat must be"):
        make(L, B, "todo", "Bad", repeat="hourly")


def test_finishing_a_repeating_card_adds_the_next_where_it_was(L, B):
    cols = {c["name"]: c for c in boards.get_board(L, B)["columns"]}
    card = boards.create_card(
        L, B, "Weekly order", column="In progress", due_date=day(0), repeat="every_week", labels=["supplies"]
    )
    recordings.create(L, B, "step", {"title": "Count stock"}, card_id=card["id"])
    boards.update_card(L, card["id"], {"completed": True})
    in_progress = [c for c in boards.get_board(L, B)["columns"] if c["name"] == "In progress"][0]["cards"]
    assert [(c["title"], c["due_date"], c["repeat"]) for c in in_progress] == [("Weekly order", day(7), "every_week")]
    assert [lbl["name"] for lbl in in_progress[0]["labels"]] == ["supplies"] and in_progress[0]["steps_count"] == 1
    assert boards.get_card(L, card["id"])["repeat"] is None
    # Moving one into Done does the same: the next waits where this one was, here Triage.
    triaged = boards.create_card(L, B, "Clean the walk-in", due_date=day(0), repeat="every_day")
    boards.move_card(L, triaged["id"], "Done")
    triage = [c for c in boards.get_board(L, B)["columns"] if c["name"] == "Triage"][0]["cards"]
    assert [(c["title"], c["due_date"]) for c in triage] == [("Clean the walk-in", day(1))]
    assert cols["Triage"]["cards"] == []  # (before any of this)
    # At the card cap the finishing is refused rather than the repeat lost.
    capped = boards.create_card(L, B, "Capped card", repeat="every_day")
    have = db.get_db().execute("SELECT COUNT(*) FROM cards WHERE list_id = ?", (L,)).fetchone()[0]
    real = common.board_caps_for
    common.board_caps_for = lambda verified, hosted, plan=None: (100, have)
    try:
        with pytest.raises(ValidationError):
            boards.move_card(L, capped["id"], "Done")
        assert boards.get_card(L, capped["id"])["completed"] is False
    finally:
        common.board_caps_for = real
    # …and at the item cap when its subtasks would pass it.
    recordings.create(L, None, "step", {"title": "Step"}, card_id=capped["id"])
    have = db.get_db().execute("SELECT COUNT(*) FROM recordings WHERE list_id = ?", (L,)).fetchone()[0]
    real_items = common.recording_cap_for
    common.recording_cap_for = lambda verified, hosted, plan=None: have
    try:
        with pytest.raises(ValidationError):
            boards.move_card(L, capped["id"], "Done")
    finally:
        common.recording_cap_for = real_items


# ── Card copies and templates ─────────────────────────────────────────────────


def test_copy_a_card_here_or_to_another_project(L, B):
    card = boards.create_card(L, B, "Order tile", column="In progress", labels=["urgent"], assignee_ids=["me"])
    recordings.comment(L, "Ask for samples", card_id=card["id"])
    here = boards.copy_card(L, card["id"])
    assert (here["column_name"], here["title"], here["comments_count"]) == ("In progress", "Order tile", 0)
    garage = boards.create_board(L, "Garage")["id"]
    there = boards.copy_card(L, card["id"], board=garage, title="Order shelving")
    assert (there["board_id"], there["column_name"], there["title"]) == (garage, "Triage", "Order shelving")
    assert [lbl["name"] for lbl in there["labels"]] == ["urgent"]  # carried by name
    assert boards.copy_card(L, card["id"], column="Done")["completed"] is True


def test_a_card_template_makes_new_cards(L, B):
    tpl = boards.create_card(L, B, "Bug report", column="In progress", notes="Steps:\n1.", template=True)
    assert tpl["template"] is True
    made = boards.copy_card(L, tpl["id"], title="Oven light flickers")
    assert (made["template"], made["notes"], made["title"]) == (False, "Steps:\n1.", "Oven light flickers")
    assert boards.update_card(L, tpl["id"], {"template": False})["template"] is False


def test_card_templates_are_listed_for_every_project(L, B, new_list):
    tpl = boards.create_card(L, B, "Bug report", column="In progress", template=True)
    boards.create_card(L, B, "Not one", column="In progress")
    garage = boards.create_board(L, "Garage")["id"]
    assert [(t["title"], t["board_name"]) for t in boards.card_templates(L)] == [
        ("Bug report", boards.get_board(L, B)["name"])
    ]
    triage = next(c["id"] for c in boards.get_board(L, garage)["columns"] if c["kind"] == "triage")
    made = boards.copy_card(L, tpl["id"], column=triage, board=garage)  # what "Or from a template…" does
    assert made["board_id"] == garage and made["template"] is False
    boards.update_card(L, tpl["id"], {"status": "archived"})
    assert boards.card_templates(L) == []
    other = new_list()  # another account sees none of these
    assert other["client"].get(f"{other['api']}/card-templates").json() == {"templates": []}


def test_an_items_change_log_is_its_own_history(L, B):
    todo = make(L, B, "todo", "Order tile")
    other = make(L, B, "todo", "Call the fitter")
    recordings.update(L, todo["id"], {"due_on": "2026-11-02"})
    recordings.comment(L, "Ordered.", rec_id=todo["id"])
    log = recordings.activity(L, rec_id=todo["id"])["events"]
    assert [e["action"] for e in log] == ["commented", "edited", "created"]
    assert other["id"] not in [e.get("recording_id") for e in log]


def test_the_change_log_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K"}).json()["id"]
    todo = c.post(f"{api}/projects/{pid}/items", json={"type": "todo", "title": "T"}).json()
    c.post(f"{api}/projects/{pid}/items", json={"type": "todo", "title": "U"})
    log = c.get(f"{api}/activity?item_id={todo['id']}").json()["events"]
    assert [e["action"] for e in log] == ["created"] and len(c.get(f"{api}/activity").json()["events"]) > 1


# ── Scheduled posts ───────────────────────────────────────────────────────────


def test_a_draft_posts_itself_when_its_time_comes(L, B):
    at = common.utcnow() + datetime.timedelta(hours=2)
    msg = make(L, B, "message", "Holiday hours", status="drafted", post_at=at.isoformat())
    assert msg["post_at"] and msg["status"] == "drafted"
    assert recordings.publish_scheduled() == 0
    assert recordings.publish_scheduled(at + datetime.timedelta(minutes=1)) == 1
    posted = recordings.get(L, msg["id"])
    assert posted["status"] == "active" and posted.get("post_at") is None
    assert recordings.activity(L)["events"][0]["action"] == "posted"
    # A project put away holds its post until it comes back.
    later = make(L, B, "message", "Later", status="drafted", post_at=at.isoformat())
    boards.update_board(L, B, {"status": "archived"})
    assert recordings.publish_scheduled(at + datetime.timedelta(minutes=1)) == 0
    assert recordings.get(L, later["id"])["status"] == "drafted"
    boards.update_board(L, B, {"status": "active"})
    with pytest.raises(ValidationError, match="future"):
        make(L, B, "message", "Past", status="drafted", post_at="2020-01-01T00:00:00Z")
    with pytest.raises(ValidationError, match="ISO"):
        make(L, B, "message", "Odd", status="drafted", post_at="next tuesday")


# ── Project templates ─────────────────────────────────────────────────────────


def test_a_project_from_a_template(L, B):
    boards.update_board(
        L, B, {"starts_on": "2026-01-05", "ends_on": "2026-02-27", "template": True, "notes": "Our kitchen playbook"}
    )
    tl = make(L, B, "todolist", "Demolition")
    done = make(L, B, "todo", "Book the skip", parent_id=tl["id"], due_on="2026-01-09")
    recordings.complete(L, done["id"])
    recordings.comment(L, "Use Acme", rec_id=done["id"])
    make(L, B, "schedule_entry", "Inspection", starts_on="2026-02-02")
    make(L, B, "message", "Kickoff notes", body="Who does what")
    make(L, B, "needle", needle="concerned")
    boards.create_card(L, B, "Order cabinets", column="In progress", due_date="2026-01-20")
    boards.create_label(L, B, "Rush", "red")  # on no card: still part of the template
    boards.create_card(L, B, "Change request", column="In progress", template=True)
    assert [t["name"] for t in templates.templates(L)] == ["Kitchen"]
    # A template is not anyone's work: none of its dates show anywhere.
    q = make(L, B, "question", "Status?", days=[0, 1, 2, 3, 4, 5, 6])
    tl2 = make(L, B, "todolist", "Hill")
    recordings.set_hill(L, B, {str(tl2["id"]): 30})
    assert reports.overdue(L)["count"] == 0
    assert schedules.calendar(L, "2026-01-01", "2026-03-01")["events"] == []
    assert schedules.lineup(L, "2026-01-01", "2026-03-01") == []
    assert reports.everything(L, "tasks")["items"] == []
    assert reports.unassigned(L) == {"todos": [], "cards": []}
    assert reports.mission_control(L)["projects"] == [] and reports.hilltop(L)["projects"] == []
    me = next(p for p in people.list_people(L) if p["kind"] == "me")["id"]
    assert schedules.checkins_due(L, me, today() + datetime.timedelta(days=1)) == [] and q

    new = templates.make_project(L, B, "Smith kitchen", starts_on="2026-03-02")  # 56 days later
    page = recordings.project(L, new["id"])
    assert (page["name"], page["notes"], page["starts_on"], page["ends_on"], page["template"]) == (
        "Smith kitchen",
        "Our kitchen playbook",
        "2026-03-02",
        "2026-04-24",
        0,
    )
    todos = recordings.todoset(L, new["id"])["lists"][0]
    copied = todos["children"][0]
    assert (copied["title"], copied["due_on"], copied["completed"]) == ("Book the skip", "2026-03-06", False)
    assert recordings.thread(L, copied["id"])["comments"] == []
    events = schedules.calendar(L, "2026-03-01", "2026-04-30", board_ref=new["id"])["events"]
    assert [(e["title"], e["on"]) for e in events] == [("Inspection", "2026-03-30")]
    assert [m["title"] for m in recordings.list_items(L, new["id"], "message")] == ["Kickoff notes"]
    assert page["needle"] is None
    assert [lbl["name"] for lbl in boards.list_labels(L, new["id"])] == ["Rush"]
    assert all(i["board_id"] != B for i in reports.progress(L, day(-1), day(1))["added"])  # the template's own
    columns = {c["name"]: c for c in boards.get_board(L, new["id"])["columns"]}
    assert [(c["title"], c["due_date"]) for c in columns["Triage"]["cards"]] == [("Order cabinets", "2026-03-17")]
    assert [(c["title"], c["template"]) for c in columns["In progress"]["cards"]] == [("Change request", True)]
    # Without a start it copies the dates as they are; the name must be new; only templates.
    same = templates.make_project(L, "Kitchen", "Jones kitchen")
    assert recordings.project(L, same["id"])["starts_on"] == "2026-01-05"
    with pytest.raises(ValidationError, match="already exists"):
        templates.make_project(L, B, "Smith kitchen")
    with pytest.raises(ValidationError, match="not a template"):
        templates.make_project(L, new["id"], "Nope")


def test_step_11_adds_the_template_and_repeat_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    conn = db.get_db()
    conn.execute("ALTER TABLE boards DROP COLUMN template")
    conn.execute("ALTER TABLE cards DROP COLUMN template")
    conn.execute("ALTER TABLE cards DROP COLUMN repeat")
    db.close_db()
    db.init_db()
    names = {t: {r["name"] for r in db.get_db().execute(f"PRAGMA table_info({t})")} for t in ("boards", "cards")}
    assert "template" in names["boards"] and {"template", "repeat"} <= names["cards"]
    assert isinstance(db.get_db(), sqlite3.Connection)


def test_step_13_adds_the_home_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db.init_db()
    db.get_db().execute("ALTER TABLE boards DROP COLUMN folder")
    db.close_db()
    db.init_db()
    assert "folder" in {r["name"] for r in db.get_db().execute("PRAGMA table_info(boards)")}


def test_a_project_sits_in_a_home_folder(L, B):
    assert boards.update_board(L, B, {"folder": "  Clients  "})["folder"] == "Clients"
    assert [b["folder"] for b in boards.list_boards(L)] == ["Clients"]
    assert boards.update_board(L, B, {"folder": ""})["folder"] == ""


# ── The browser and the agent ─────────────────────────────────────────────────


def test_the_copy_and_template_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K", "tools": ["todoset"]}).json()["id"]
    tl = c.post(f"{api}/projects/{pid}/items", json={"type": "todolist", "title": "Prep"}).json()
    assert c.post(f"{api}/items/{tl['id']}/copy", json={}).json()["title"] == "Prep"
    card = c.post(f"{api}/boards/{pid}/cards", json={"title": "Fix sign", "repeat": "every_month"}).json()
    assert card["repeat"] == "every_month"
    assert c.post(f"{api}/cards/{card['id']}/copy", json={"title": "Fix door"}).json()["title"] == "Fix door"
    other = c.post(f"{api}/boards", json={"name": "Shop"}).json()["id"]
    moved = c.post(f"{api}/cards/{card['id']}/move", json={"project_id": other})
    assert moved.status_code == 200 and moved.json()["board_id"] == other
    assert c.put(f"{api}/boards/{pid}", json={"template": True}).status_code == 200
    assert c.get(f"{api}/templates").json()["templates"][0]["name"] == "K"
    new = c.post(f"{api}/templates/{pid}/use", json={"name": "K2"}).json()
    assert new["name"] == "K2"
    draft = c.post(
        f"{api}/projects/{pid}/items",
        json={"type": "message", "title": "Soon", "status": "drafted", "post_at": "2099-01-01T09:00:00Z"},
    ).json()
    assert draft["post_at"] == "2099-01-01T09:00:00.000Z"


@pytest.mark.anyio
async def test_an_agent_moves_copies_and_starts_from_a_template(connect, made):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Template: launch")
        tl = (await call(c, "item_create", project="Template: launch", type="todolist", title="Launch list"))["item"]
        other = (await call(c, "item_create", project="Template: launch", type="todolist", title="Later"))["item"]
        todo = (
            await call(
                c,
                "item_create",
                project="Template: launch",
                type="todo",
                title="Write copy",
                parent_id=tl["id"],
                fields={"repeat": "every_week"},
            )
        )["item"]
        assert todo["repeat"] == "every_week"
        moved = (await call(c, "item_move", id=todo["id"], parent_id=other["id"]))["item"]
        assert moved["parent_id"] == other["id"]
        copied = (await call(c, "item_move", id=tl["id"], copy=True))["item"]
        assert copied["title"] == "Launch list" and copied["id"] != tl["id"]
        with pytest.raises(ToolError, match="Say where"):
            await call(c, "item_move", id=todo["id"])
        card = (await call(c, "card_create", project="Template: launch", title="Book venue"))["card"]
        assert (await call(c, "card_update", id=card["id"], repeat="every_month"))["card"]["repeat"] == "every_month"
        copy = (await call(c, "card_move", id=card["id"], column="", copy=True))["card"]
        assert copy["id"] != card["id"] and copy["title"] == "Book venue"
        boards.update_board(made["list_id"], "Template: launch", {"template": True})
        new = (await call(c, "board_create", name="Spring launch", template="Template: launch"))["project"]
        assert new["name"] == "Spring launch"
        assert [t["title"] for t in recordings.list_items(made["list_id"], new["id"], "todolist")] == [
            "Launch list",
            "Later",
            "Launch list",
        ]


@pytest.mark.anyio
async def test_the_move_and_copy_commands(http, made):
    base, ua = f"/mcp/{made['agent_token']}", {"User-Agent": "Claude/1.0"}
    for name in ("Garage", "Shop"):
        await http.post(f"{base}?cmd=CREATE_BOARD", json={"name": name}, headers=ua)
    tl = (
        await http.post(
            f"{base}?cmd=ADD_ITEM&project=Garage", json={"type": "todolist", "title": "Clear out"}, headers=ua
        )
    ).json()["item"]
    other = (
        await http.post(f"{base}?cmd=ADD_ITEM&project=Garage", json={"type": "todolist", "title": "Later"}, headers=ua)
    ).json()["item"]
    todo = (
        await http.post(
            f"{base}?cmd=ADD_ITEM&project=Garage",
            json={"type": "todo", "title": "Sweep", "parent_id": tl["id"]},
            headers=ua,
        )
    ).json()["item"]
    moved = (
        await http.post(f"{base}?cmd=MOVE_ITEM&id={todo['id']}", json={"parent_id": other["id"]}, headers=ua)
    ).json()
    assert moved["item"]["parent_id"] == other["id"]
    copied = (await http.post(f"{base}?cmd=COPY_ITEM&id={tl['id']}", json={"project": "Shop"}, headers=ua)).json()
    assert copied["item"]["board_name"] == "Shop" and copied["item"]["id"] != tl["id"]
    nowhere = await http.post(f"{base}?cmd=MOVE_ITEM&id={todo['id']}", json={}, headers=ua)
    assert nowhere.status_code == 400 and "Say where" in nowhere.json()["error"]
    assert (await http.get(f"{base}?cmd=COPY_ITEM&id={tl['id']}", headers=ua)).status_code == 405
