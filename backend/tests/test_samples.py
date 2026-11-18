"""Projects GTD's sample projects (samples.py, migration step 14): seeded once on an
empty account, turned off and on, kept out of the projects cap, and shown as such
to the web app and to AI tools."""

import datetime

import pytest

from backend import boards, common, db, recordings, samples
from backend.common import ValidationError
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    anyio_backend,
    app,
    http,
    made,
)


def names(L, status="active") -> list[str]:
    return sorted(b["name"] for b in boards.list_boards(L, status))


def test_seeding_makes_the_two_sample_projects_once(L):
    out = samples.seed(L)
    assert out["state"] == "on"
    assert [p["name"] for p in out["projects"]] == ["👋 Start here", "Sample: Bakery website launch"]
    # Two tabs opening Home: the second seed changes nothing.
    assert samples.seed(L)["projects"] == out["projects"]
    assert len(boards.list_boards(L)) == 2
    bakery = boards.get_board(L, "Sample: Bakery website launch")
    assert bakery["sample"] is True
    columns = {c["name"]: c for c in bakery["columns"]}
    assert [c["name"] for c in bakery["columns"]] == ["Triage", "Not now", "To do", "Doing", "Done"]
    assert len(columns["To do"]["cards"]) == 4 and all(c["completed"] for c in columns["Done"]["cards"])
    hero = next(c for c in columns["Doing"]["cards"] if c["title"] == "Homepage hero photo")
    today = recordings._today(db.get_db(), L)
    assert hero["due_date"] == (today + datetime.timedelta(days=2)).isoformat()
    assert sorted(lbl["name"] for lbl in hero["labels"]) == ["Design", "Photos"]
    assert [p["kind"] for p in hero["assignees"]] == ["me"]
    thread = recordings.card_thread(L, hero["id"])
    assert [(s["title"], s["completed"]) for s in thread["subtasks"]][:2] == [
        ("Shortlist three shots", True),
        ("Crop for phones", False),
    ]
    assert len(thread["comments"]) == 1
    page = recordings.project(L, bakery["id"])
    assert page["sample"] is True
    assert [t["tool"] for t in page["dock"] if t["enabled"]] == [
        "kanban_board",
        "message_board",
        "todoset",
        "vault",
        "schedule",
    ]
    assert [m["title"] for m in page["previews"]["message_board"]] == ["Kickoff: the new website"]
    todos = recordings.todoset(L, bakery["id"])
    checklist = next(t for t in todos["lists"] if t["title"] == "Launch checklist")
    assert (checklist["todos_count"], checklist["completed_count"]) == (4, 1)
    # Not news: nothing in the trail, so nothing in Activity or New for you.
    assert recordings.activity(L)["events"] == []


def test_an_account_with_a_project_gets_no_samples(L):
    boards.create_board(L, "Kitchen")
    assert samples.seed(L) == {"state": None, "projects": []}
    assert names(L) == ["Kitchen"]


def test_an_archived_project_also_counts_as_having_projects(L):
    b = boards.create_board(L, "Kitchen")
    boards.update_board(L, b["id"], {"status": "archived"})
    assert samples.seed(L)["state"] is None and names(L) == []


def test_off_archives_the_samples_and_on_brings_them_back(L):
    with pytest.raises(ValidationError, match="no sample projects"):
        samples.turn(L, False)
    samples.seed(L)
    mine = boards.create_board(L, "Kitchen")
    off = samples.turn(L, False)
    assert off["state"] == "off" and {p["status"] for p in off["projects"]} == {"archived"}
    assert names(L) == ["Kitchen"]
    assert names(L, "archived") == ["Sample: Bakery website launch", "👋 Start here"]
    on = samples.turn(L, True)
    assert on["state"] == "on" and {p["status"] for p in on["projects"]} == {"active"}
    assert names(L) == ["Kitchen", "Sample: Bakery website launch", "👋 Start here"]
    assert boards.get_board(L, mine["id"])["status"] == "active"
    # Off again after on: nothing was lost in between.
    samples.turn(L, False)
    assert len(boards.get_board(L, "👋 Start here")["columns"]) == 5


def test_samples_do_not_take_a_place_under_the_projects_cap(L):
    samples.seed(L)
    cap = common.board_caps_for(False, True)[0]
    for n in range(cap):
        boards.create_board(L, f"Mine {n}")
    with pytest.raises(ValidationError, match=f"holds {cap} boards"):
        boards.create_board(L, "One too many")


def test_a_new_database_and_an_old_one_both_have_the_columns(todo_db):
    conn = db.get_db()
    assert "projects_sample" in {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}
    assert "sample" in {r["name"] for r in conn.execute("PRAGMA table_info(boards)")}
    db._migrate(conn)  # again: idempotent


# ── The web app's routes ──────────────────────────────────────────────────────


def test_the_routes_seed_turn_off_and_on(new_list):
    me = new_list()
    c, api = me["client"], me["api"]
    res = c.get(f"{api}/projects/sample")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert res.json() == {"state": None, "projects": []}
    res = c.post(f"{api}/projects/sample", json={"action": "seed"})
    assert res.status_code == 200 and res.json()["state"] == "on"
    assert res.headers["cache-control"] == "no-store"
    home = c.get(f"{api}/home").json()
    assert sorted((p["name"], p["sample"]) for p in home["projects"]) == [
        ("Sample: Bakery website launch", True),
        ("👋 Start here", True),
    ]
    assert c.post(f"{api}/projects/sample", json={"action": "off"}).json()["state"] == "off"
    assert c.get(f"{api}/home").json()["projects"] == []
    assert c.post(f"{api}/projects/sample", json={"action": "on"}).json()["state"] == "on"
    assert c.post(f"{api}/projects/sample", json={"action": "wipe"}).status_code == 422


def test_the_routes_keep_the_app_rules(new_list):
    me = new_list()
    c, api = me["client"], me["api"]
    # Another site's page cannot seed or turn them off.
    res = c.post(f"{api}/projects/sample", json={"action": "seed"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status_code == 403 and res.headers["cache-control"] == "no-store"
    # A tab showing another list is told so.
    res = c.get(f"{api}/projects/sample", headers={"X-List": str(me["list_id"] + 1)})
    assert res.status_code == 409
    # Turning off before there is anything to turn off is refused, not stored.
    res = c.post(f"{api}/projects/sample", json={"action": "off"})
    assert res.status_code == 400 and res.headers["cache-control"] == "no-store"
    assert samples.state(me["list_id"])["state"] is None


# ── AI tools ──────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_ai_tools_see_which_projects_are_samples(http, made):
    samples.seed(made["list_id"])
    link = f"/link/{made['agent_token']}"
    projects = (await http.get(f"{link}?cmd=BOARDS")).json()["projects"]
    assert {p["sample"] for p in projects} == {True}
    page = (await http.get(f"{link}?cmd=PROJECT&project=Sample: Bakery website launch")).json()
    assert page["project"]["sample"] is True
    guide = (await http.get(link)).json()
    assert "sample: true is an example the app made" in guide["about"]
