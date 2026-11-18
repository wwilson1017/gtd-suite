"""Projects GTD's views across projects: Everything, Reports, Mission Control and
the Needle, Hill Charts and the Hilltop View, search, Spotlight and the
archive (reports.py, recordings.py)."""

import datetime

import pytest

from backend import boards, common, db, people, recordings, reports
from backend.common import NotFoundError, ValidationError
from fastmcp.exceptions import ToolError
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


def ago(n: int) -> str:
    return (common.business_today("America/Chicago") - datetime.timedelta(days=n)).isoformat()


# ── Everything ────────────────────────────────────────────────────────────────


def test_everything_lists_one_kind_newest_first_across_projects(L, B, monkeypatch):
    # Each read of the clock is a second later: cards and recordings are separate tables, so
    # two rows made in the same millisecond have no order between them (it failed 1 run in 5).
    start, ticks = common.utcnow(), iter(range(1, 10_000))
    monkeypatch.setattr(common, "utcnow", lambda: start + datetime.timedelta(seconds=next(ticks)))
    garage = boards.create_board(L, "Garage")["id"]
    make(L, B, "message", "Kickoff")
    make(L, garage, "message", "Garage plan")
    make(L, B, "message", "Draft", status="drafted")
    todo = make(L, B, "todo", "Measure")
    make(L, B, "step", "Tape", parent_id=todo["id"])
    boards.create_card(L, garage, "Shelves")
    recordings.comment(L, "Done by Friday", rec_id=todo["id"])
    assert [i["title"] for i in reports.everything(L, "messages")["items"]] == ["Garage plan", "Kickoff"]
    assert [i["title"] for i in reports.everything(L, "tasks")["items"]] == ["Shelves", "Measure"]
    assert "Tape" in [i["title"] for i in reports.everything(L, "tasks", subtasks=True)["items"]]
    comment = reports.everything(L, "comments")["items"][0]
    assert (comment["body"], comment["on_title"]) == ("Done by Friday", "Measure")
    # A page at a time, to-dos and cards together, nothing twice.
    monkeypatch.setattr(reports, "PAGE", 1)
    pages, before = [], None
    while True:
        page = reports.everything(L, "tasks", before=before)
        pages += [i["title"] for i in page["items"]]
        if not (before := page["next_before"]):
            break
    assert pages == ["Shelves", "Measure"]
    boards.update_board(L, garage, {"status": "archived"})
    assert [i["title"] for i in reports.everything(L, "messages")["items"]] == ["Kickoff"]
    make(L, B, "document", "Spec")
    q = make(L, B, "question", "Any blockers?")
    recordings.create(L, None, "answer", {"body": "None"}, parent_id=q["id"])
    assert [i["title"] for i in reports.everything(L, "docs")["items"]] == ["Spec"]
    answer = reports.everything(L, "checkins")["items"][0]
    assert (answer["body"], answer["on_title"]) == ("None", "Any blockers?")
    with pytest.raises(ValidationError):
        reports.everything(L, "everything")


# ── Reports ───────────────────────────────────────────────────────────────────


def test_overdue_work_is_grouped_by_how_late_it_is(L, B):
    # Each group's edges: 6 and 7 days, 29 and 30, 89 and 90.
    for days in (1, 6, 7, 29, 30, 89, 90, 200):
        make(L, B, "todo", f"{days} days", due_on=ago(days))
    boards.create_card(L, B, "Old card", due_date=ago(3))
    make(L, B, "todo", "Today", due_on=ago(0))
    done = make(L, B, "todo", "Done late", due_on=ago(5))
    recordings.complete(L, done["id"])
    out = reports.overdue(L)
    assert [[i["title"] for i in g["items"]] for g in out["groups"]] == [
        ["1 days", "Old card", "6 days"],
        ["7 days", "29 days"],
        ["30 days", "89 days"],
        ["90 days", "200 days"],
    ]
    assert out["groups"][0]["items"][0]["days_late"] == 1 and out["count"] == 9
    # Work in something put away is not overdue: a to-do in an archived list, a subtask on an archived card.
    hidden = make(L, B, "todolist", "Shelved")
    make(L, B, "todo", "In the shelved list", parent_id=hidden["id"], due_on=ago(2))
    recordings.update(L, hidden["id"], {"status": "archived"})
    shelf_card = boards.create_card(L, B, "Shelved card")
    recordings.create(L, B, "step", {"title": "Card subtask", "due_on": ago(2)}, card_id=shelf_card["id"])
    boards.update_card(L, shelf_card["id"], {"status": "archived"})
    assert reports.overdue(L)["count"] == 9


def test_upcoming_unassigned_and_someones_tasks(L, B):
    make(L, B, "todo", "Soon", due_on=ago(-3), assignee_ids=["me"])
    make(L, B, "todo", "Far", due_on=ago(-40))
    boards.create_card(L, B, "Nobody's card")
    make(L, B, "message", "hi", source="agent", client="Claude")
    make(L, B, "todo", "For Claude", assignee_ids=["Claude"])
    assert [i["title"] for i in reports.upcoming(L)["items"]] == ["Soon"]
    assert [i["title"] for i in reports.upcoming(L, 60)["items"]] == ["Soon", "Far"]
    gaps = reports.unassigned(L)
    assert [t["title"] for t in gaps["todos"]] == ["Far"] and [c["title"] for c in gaps["cards"]] == ["Nobody's card"]
    claude = next(p for p in people.list_people(L) if p["name"] == "Claude")["id"]
    assert [t["title"] for t in reports.person_tasks(L, claude)["todos"]] == ["For Claude"]
    with pytest.raises(ValidationError):
        reports.upcoming(L, 500)
    with pytest.raises(ValidationError):
        reports.person_tasks(L, 999999)


def test_added_and_completed(L, B):
    a = make(L, B, "todo", "Added")
    recordings.complete(L, a["id"])
    card = boards.create_card(L, B, "Card")
    boards.update_card(L, card["id"], {"completed": True})
    out = reports.progress(L, ago(1), ago(-1))
    assert {i["title"] for i in out["added"]} == {"Added", "Card"}
    assert {i["title"] for i in out["completed"]} == {"Added", "Card"}
    assert reports.progress(L, ago(30), ago(20))["added"] == []
    with pytest.raises(ValidationError):
        reports.progress(L, ago(0), ago(5))


# ── The Needle and Mission Control ────────────────────────────────────────────


def test_the_needle_is_the_persons_and_mission_control_lists_it(L, B, monkeypatch):
    quiet = boards.create_board(L, "Old shed")["id"]
    make(L, B, "needle", needle="some_risk", body="Tile is late")
    make(L, B, "needle", needle="on_track", body="Tile came")
    assert [n["needle"] for n in recordings.needles(L, B)] == ["on_track", "some_risk"]
    assert recordings.project(L, B)["needle"]["needle"] == "on_track"
    with pytest.raises(ValidationError, match="person's to set"):
        make(L, B, "needle", needle="concerned", source="agent", client="Claude")
    with pytest.raises(ValidationError, match="needle must be"):
        make(L, B, "needle", needle="fine")
    with pytest.raises(ValidationError, match="needs needle"):
        make(L, B, "needle", body="no reading")
    with pytest.raises(ValidationError, match="can't take comments"):
        recordings.comment(L, "hm", rec_id=recordings.needles(L, B)[0]["id"])
    projects = {p["name"]: p for p in reports.mission_control(L)["projects"]}
    assert projects["Kitchen"]["needle"]["needle"] == "on_track" and not projects["Kitchen"]["quiet"]
    assert projects["Old shed"]["needle"] is None and not projects["Old shed"]["quiet"]
    # Two weeks on with nothing done anywhere, both have gone quiet.
    later = common.business_today("America/Chicago") + datetime.timedelta(days=reports.QUIET_DAYS + 1)
    monkeypatch.setattr(reports, "_today", lambda list_id: later)
    assert all(p["quiet"] for p in reports.mission_control(L)["projects"]) and quiet
    line = recordings.activity(L, board_id=B)["events"][0]
    assert line["verb"] == "updated the status of"


# ── Hill Charts ───────────────────────────────────────────────────────────────


def test_the_hill_chart_is_moved_by_the_person_and_kept_as_updates(L, B):
    design, build = make(L, B, "todolist", "Design"), make(L, B, "todolist", "Build")
    make(L, B, "todolist", "Untracked")
    chart = recordings.set_hill(L, B, {str(design["id"]): 30, str(build["id"]): 0}, "Starting out")
    assert [(x["title"], x["hill"]) for x in chart["lists"]] == [("Design", 30), ("Build", 0)]
    chart = recordings.set_hill(L, B, {str(design["id"]): 75.5}, "Design is downhill")
    assert [u["body"] for u in chart["updates"]] == ["Design is downhill", "Starting out"]
    assert chart["updates"][0]["lists"][0]["hill"] == 75.5 and not chart["stale"]
    recordings.set_hill(L, B, {str(build["id"]): None})  # stop tracking
    assert [x["title"] for x in recordings.hill_chart(L, B)["lists"]] == ["Design"]
    assert [x["title"] for x in recordings.project(L, B)["previews"]["hill"]] == ["Design"]
    with pytest.raises(ValidationError, match="moved by the person"):
        recordings.set_hill(L, B, {str(design["id"]): 50}, source="agent", client="Claude")
    with pytest.raises(ValidationError, match="0 to 100"):
        recordings.set_hill(L, B, {str(design["id"]): 101})
    with pytest.raises(NotFoundError):
        recordings.set_hill(L, B, {"999999": 10})
    with pytest.raises(ValidationError):
        recordings.set_hill(L, B, {"design": 10})
    other = boards.create_board(L, "Garage")["id"]
    with pytest.raises(NotFoundError):
        recordings.set_hill(L, other, {str(design["id"]): 10})
    assert [p["name"] for p in reports.hilltop(L)["projects"]] == ["Kitchen"]


def test_a_hill_nobody_moved_for_two_weeks_is_stale(L, B, monkeypatch):
    tl = make(L, B, "todolist", "Design")
    recordings.set_hill(L, B, {str(tl["id"]): 20})
    later = common.business_today("America/Chicago") + datetime.timedelta(days=recordings.STALE_HILL_DAYS + 1)
    monkeypatch.setattr(recordings, "_today", lambda conn, list_id: later)
    assert recordings.hill_chart(L, B)["stale"] is True


def test_stale_and_quiet_count_the_lists_own_days_near_midnight(L, freeze):
    """A hill moved at 22:00 in Chicago was moved that day there, though UTC had
    already turned the page; two weeks and a day later it is stale, and the
    project has gone quiet, all evening long."""
    freeze("2026-10-14T03:00:00")  # Chicago: 13 October, 22:00
    B = boards.create_board(L, "Kitchen")["id"]  # made on the frozen clock, not today's
    tl = make(L, B, "todolist", "Design")
    recordings.set_hill(L, B, {str(tl["id"]): 20})
    freeze("2026-10-29T03:00:00")  # Chicago: 28 October, 22:00
    assert recordings.hill_chart(L, B)["stale"] is True
    assert [p["quiet"] for p in reports.mission_control(L)["projects"]] == [True]


def test_a_check_in_asked_first_on_a_chicago_evening_is_asked_that_day(L, B, freeze):
    from backend import schedules

    freeze("2026-10-14T03:00:00")  # Chicago: Tuesday 13 October, 22:00
    q = make(L, B, "question", "Blockers?")
    assert schedules.checkins_due(L, people.me_in(db.get_db(), L))[0]["id"] == q["id"]


# ── Search ────────────────────────────────────────────────────────────────────


def test_search_finds_every_word_in_titles_and_text(L, B):
    garage = boards.create_board(L, "Garage")["id"]
    make(L, B, "message", "Tile choices", body="We picked the grey tile.")
    make(L, B, "todo", "Call the tiler", body="Ask about grey grout")
    make(L, garage, "document", "Shelf plan", body="Grey paint, then tile the floor")
    old = make(L, B, "message", "Old tile note")
    recordings.update(L, old["id"], {"status": "archived"})
    gone = make(L, B, "message", "Trashed tile")
    recordings.update(L, gone["id"], {"status": "trashed"})
    boards.create_card(L, garage, "Tile the bench", notes="grey")
    make(L, B, "message", "100% sure", body="a_b")
    make(L, B, "message", "Draft about tile", status="drafted")
    make(L, B, "needle", needle="on_track", body="tile is on its way")
    make(L, B, "todo", "Claude's tile check", source="agent", client="Claude")
    found = reports.search(L, "tile")
    titles = [r["title"] for r in found["results"]]
    assert "Trashed tile" not in titles and "Old tile note" in titles  # archived is found, the trash is not
    assert "Draft about tile" not in titles and all(r["type"] != "needle" for r in found["results"])
    # Best match: title matches first (newest first among them), then text matches.
    assert [r["title_match"] for r in found["results"]] == [True, True, True, True, True, False]
    assert titles[-1] == "Shelf plan"
    claude = next(p for p in people.list_people(L) if p["name"] == "Claude")["id"]
    assert [r["title"] for r in reports.search(L, "tile", person_id=claude)["results"]] == ["Claude's tile check"]
    choices = next(r for r in reports.search(L, "choices")["results"])
    recordings.comment(L, "cobalt glaze wins", rec_id=choices["id"])
    found_comment = next(r for r in reports.search(L, "cobalt")["results"] if r["type"] == "comment")
    assert found_comment["title"] == "Re: Tile choices"

    both = reports.search(L, "grey tile")
    assert {r["title"] for r in both["results"]} == {"Tile choices", "Call the tiler", "Shelf plan", "Tile the bench"}
    assert [r["title"] for r in reports.search(L, "grey", kind="document")["results"]] == ["Shelf plan"]
    assert [r["title"] for r in reports.search(L, "grey", kind="card")["results"]] == ["Tile the bench"]
    assert {r["title"] for r in reports.search(L, "grey", board_id=B)["results"]} == {"Tile choices", "Call the tiler"}
    assert "snippet" in found["results"][0]
    # LIKE's wildcards are plain text here.
    assert [r["title"] for r in reports.search(L, "100%")["results"]] == ["100% sure"]
    assert reports.search(L, "a_c")["results"] == []
    assert [r["title"] for r in reports.search(L, "tiler", sort="recent")["results"]] == ["Call the tiler"]
    assert reports.search(L, "tile", since=ago(-2))["results"] == []
    for bad in ({"q": ""}, {"q": "x", "kind": "spaceship"}, {"q": "x", "sort": "random"}, {"q": "x" * 300}):
        with pytest.raises(ValidationError):
            reports.search(L, **bad)


def test_search_finds_only_this_accounts_things(L, B, new_list):
    make(L, B, "message", "Secret tile plan")
    other = new_list()["list_id"]
    other_board = boards.create_board(other, "Theirs")["id"]
    recordings.create(other, other_board, "message", {"title": "Their tile plan"})
    assert [r["title"] for r in reports.search(L, "tile")["results"]] == ["Secret tile plan"]


# ── Spotlight and the archive ─────────────────────────────────────────────────


def test_spotlight_puts_things_on_the_project_page(L, B, monkeypatch):
    doc = make(L, B, "document", "Brief")
    before = recordings.activity(L)["latest"]
    recordings.update(L, doc["id"], {"spotlight": True})
    assert [i["title"] for i in recordings.project(L, B)["spotlight"]] == ["Brief"]
    assert recordings.activity(L)["latest"] == before  # placing it is not an edit
    recordings.update(L, doc["id"], {"spotlight": False})
    assert recordings.project(L, B)["spotlight"] == []
    monkeypatch.setattr(recordings, "MAX_SPOTLIGHT", 1)
    news = make(L, B, "message", "Big news", spotlight=True)
    with pytest.raises(ValidationError, match="Spotlight"):
        recordings.update(L, doc["id"], {"spotlight": True})
    with pytest.raises(ValidationError, match="Spotlight"):
        make(L, B, "message", "Two", spotlight=True)
    assert recordings.update(L, news["id"], {"spotlight": True})["spotlight"] is True  # already in: no change
    # One back from the archive while the Spotlight is full comes back out of it.
    recordings.update(L, news["id"], {"status": "archived"})
    recordings.update(L, doc["id"], {"spotlight": True})
    assert recordings.update(L, news["id"], {"status": "active"}).get("spotlight") is None


def test_the_archive_and_trash_of_a_project(L, B):
    a, t = make(L, B, "message", "Old"), make(L, B, "document", "Wrong")
    recordings.update(L, a["id"], {"status": "archived"})
    recordings.update(L, t["id"], {"status": "trashed"})
    card = boards.create_card(L, B, "Stale card")
    boards.update_card(L, card["id"], {"status": "archived"})
    away = recordings.put_away(L, B)
    assert [i["title"] for i in away["archived"]] == ["Old"]
    assert [i["title"] for i in away["trashed"]] == ["Wrong"]
    assert [c["title"] for c in away["cards"]] == ["Stale card"]
    recordings.update(L, t["id"], {"status": "active"})
    assert recordings.put_away(L, B)["trashed"] == []


# ── The browser and the agent ─────────────────────────────────────────────────


def test_the_reports_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K"}).json()["id"]
    tl = c.post(f"{api}/projects/{pid}/items", json={"type": "todolist", "title": "Design"}).json()
    c.post(f"{api}/projects/{pid}/items", json={"type": "todo", "title": "Late", "due_on": "2020-01-01"})
    assert c.get(f"{api}/reports/overdue").json()["count"] == 1
    hill = c.post(f"{api}/projects/{pid}/hill", json={"positions": {str(tl["id"]): 40}, "note": "Moving"})
    assert hill.status_code == 200 and hill.json()["lists"][0]["hill"] == 40
    assert c.get(f"{api}/reports/hilltop").json()["projects"][0]["name"] == "K"
    assert c.post(f"{api}/projects/{pid}/items", json={"type": "needle", "needle": "concerned"}).status_code == 200
    assert c.get(f"{api}/projects/{pid}/needle").json()["needles"][0]["needle"] == "concerned"
    assert c.get(f"{api}/reports/mission-control").json()["projects"][0]["needle"]["needle"] == "concerned"
    assert c.get(f"{api}/search?q=late").json()["results"][0]["title"] == "Late"
    assert c.get(f"{api}/search?q=").status_code == 400
    assert c.get(f"{api}/everything?kind=tasks").json()["items"][0]["title"] == "Late"
    for path in ("upcoming", "unassigned", "progress?start=2026-01-01&end=2026-01-31"):
        assert c.get(f"{api}/reports/{path}").status_code == 200
    assert c.get(f"{api}/projects/{pid}/put-away").json()["archived"] == []


@pytest.mark.anyio
async def test_an_agent_reads_reports_and_searches_but_never_moves_the_needle(connect, made):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Garage")
        await call(c, "item_create", project="Garage", type="todo", title="Sweep the floor", due_on="2020-01-01")
        late = await call(c, "report_get", report="overdue")
        assert late["groups"][-1]["items"][0]["title"] == "Sweep the floor"
        found = await call(c, "project_search", q="sweep")
        assert found["results"][0]["title"] == "Sweep the floor"
        with pytest.raises(ToolError, match="person's to set"):
            await call(c, "item_create", project="Garage", type="needle", fields={"needle": "on_track"})
        mine = recordings.create(made["list_id"], "Garage", "needle", {"needle": "concerned"})
        for tool, args in (
            ("item_update", {"id": mine["id"], "fields": {"needle": "on_track"}}),
            ("item_archive", {"id": mine["id"]}),
        ):
            with pytest.raises(ToolError, match="person's to set"):
                await call(c, tool, **args)
        with pytest.raises(ToolError, match="report must be"):
            await call(c, "report_get", report="gossip")


@pytest.mark.anyio
async def test_the_find_and_report_commands(http, made):
    base, ua = f"/mcp/{made['agent_token']}", {"User-Agent": "Claude/1.0"}
    await http.post(f"{base}?cmd=CREATE_BOARD", json={"name": "Trip"}, headers=ua)
    await http.post(f"{base}?cmd=ADD_ITEM&project=Trip", json={"type": "todo", "title": "Book the ferry"}, headers=ua)
    found = (await http.get(f"{base}?cmd=FIND&q=ferry", headers=ua)).json()
    assert found["results"][0]["title"] == "Book the ferry"
    gaps = (await http.get(f"{base}?cmd=REPORT&report=unassigned", headers=ua)).json()
    assert [t["title"] for t in gaps["todos"]] == ["Book the ferry"]
    assert (await http.get(f"{base}?cmd=REPORT&report=progress", headers=ua)).status_code == 400


def test_best_match_keeps_old_title_matches_past_the_candidate_cap(L, B, monkeypatch):
    make(L, B, "message", "Grout colours")  # the oldest, a title match
    for n in range(3):
        make(L, B, "message", f"Note {n}", body="grout talk")
    monkeypatch.setattr(reports, "CANDIDATES", 2)
    assert reports.search(L, "grout")["results"][0]["title"] == "Grout colours"
    assert "Grout colours" not in [r["title"] for r in reports.search(L, "grout", sort="recent")["results"]]
