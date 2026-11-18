"""Checking for changes: the list's change counter and what service.changes,
the CHANGES command and the todo_changes tool report from it, and the count
(service.changes_count, CHANGES_COUNT, todo_changes_count)."""

import datetime

import pytest

from backend import common, db, lists, service
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


def head(list_id: int) -> int:
    return db.get_db().execute("SELECT rev FROM lists WHERE id = ?", (list_id,)).fetchone()[0]


def ids(out) -> dict:
    return {kind: [row["id"] for row in out[kind]] for kind in ("todos", "projects", "areas")}


def test_a_sync_sees_each_addition_and_edit_once(L):
    start = service.changes(L)
    assert (start["changed"], start["more"], start["reset"]) == (False, False, False)
    assert start["next_since"] == 0
    assert ids(start) == {"todos": [], "projects": [], "areas": []}

    area = service.create_area(L, "Home")
    project = service.create_project(L, "Fence", area_id=area["id"])
    a = service.create_todo(L, "Buy paint", project_id=project["id"])
    b = service.create_todo(L, "Call Sam")
    first = service.changes(L, start["next_since"])
    assert first["changed"] is True
    assert ids(first) == {"todos": [a["id"], b["id"]], "projects": [project["id"]], "areas": [area["id"]]}
    assert first["todos"][0]["project_name"] == "Fence" and first["todos"][0]["tags"] == []
    assert first["projects"][0]["open_count"] == 1

    # Nothing since: the cheap check.
    again = service.changes(L, first["next_since"])
    assert again["changed"] is False and again["next_since"] == first["next_since"]

    edited = service.update_todo(L, b["id"], {"status": "dropped"})
    service.update_project(L, project["id"], {"outcome": "A painted fence"})
    second = service.changes(L, first["next_since"])
    assert ids(second) == {"todos": [b["id"]], "projects": [project["id"]], "areas": []}
    assert second["todos"][0]["status"] == "dropped"  # an archive is an edit; nothing vanishes
    # A write hands back the row's rev, so the writer can tell its own change.
    assert second["todos"][0]["rev"] == edited["rev"] > a["rev"]
    assert second["next_since"] == head(L)


def test_bulk_edits_and_a_repeat_spawn_are_all_reported(L):
    a, b = (service.create_todo(L, t, status="next_action") for t in ("a", "b"))
    routine = service.create_todo(L, "Water plants", repeat="daily", due_date="2026-10-11")
    since = service.changes(L)["next_since"]
    service.bulk_update(L, [a["id"], b["id"]], {"star": True})
    service.update_todo(L, routine["id"], {"status": "done"})
    out = service.changes(L, since)
    assert [t["id"] for t in out["todos"][:3]] == [a["id"], b["id"], routine["id"]]
    assert len(out["todos"]) == 4 and out["todos"][3]["title"] == "Water plants"
    assert out["todos"][3]["status"] != "done"


def test_a_brain_tickle_is_not_a_change(L):
    todo = service.create_todo(L, "Ring the bank", status="next_action")
    since = service.changes(L)["next_since"]
    assert service.record_tickle(L, todo["id"])["tickle_count"] == 1
    assert service.changes(L, since)["changed"] is False
    service.update_todo(L, todo["id"], {"star": True})  # a real edit after it still counts
    assert ids(service.changes(L, since))["todos"] == [todo["id"]]


def test_the_count_moves_with_every_change_and_nothing_else(L):
    assert service.changes_count(L) == {"count": 0, "last_change_at": None}
    now = datetime.datetime.now(datetime.timezone.utc)  # the database's clock is the real one
    todo = service.create_todo(L, "Ring the bank", status="next_action")
    first = service.changes_count(L)
    assert first["count"] == 1 == service.changes(L)["next_since"]
    second = datetime.timedelta(seconds=1)
    assert common.to_iso(now - second) <= first["last_change_at"] <= common.to_iso(now + second)
    assert len(first["last_change_at"]) == len(common.to_iso(now))  # the app's own format

    # Reads, a brain tickle and another list's writes leave it alone.
    service.get_todo(L, todo["id"])
    service.list_todos(L)
    service.changes(L)
    service.record_tickle(L, todo["id"])
    service.create_todo(lists.create_list("UTC")["list_id"], "theirs")
    assert service.changes_count(L) == first
    # A project or an area is a change too, one each.
    service.create_project(L, "Fence")
    service.create_area(L, "Home")
    service.update_todo(L, todo["id"], {"star": True})
    assert service.changes_count(L)["count"] == 4 == service.changes(L)["next_since"]


def test_each_tool_keeps_its_own_place(L):
    early = service.changes(L)["next_since"]
    a = service.create_todo(L, "a")
    late = service.changes(L)["next_since"]
    b = service.create_todo(L, "b")
    assert ids(service.changes(L, early))["todos"] == [a["id"], b["id"]]
    assert ids(service.changes(L, late))["todos"] == [b["id"]]
    assert ids(service.changes(L, early))["todos"] == [a["id"], b["id"]]  # reading moved nothing


def test_paging_walks_every_change_in_order_without_a_gap_or_a_repeat(L):
    made_ids = []
    for n in range(3):
        made_ids.append(("todos", service.create_todo(L, f"t{n}")["id"]))
        made_ids.append(("projects", service.create_project(L, f"p{n}")["id"]))
    made_ids.append(("areas", service.create_area(L, "Home")["id"]))
    seen, since, calls = [], 0, 0
    while True:
        out = service.changes(L, since, limit=2)
        page = sorted((row["rev"], kind, row["id"]) for kind in ("todos", "projects", "areas") for row in out[kind])
        seen += [(kind, row_id) for _, kind, row_id in page]
        since, calls = out["next_since"], calls + 1
        if not out["more"]:
            break
        assert len(page) == 2
    assert seen == made_ids and calls == 4
    assert since == head(L)


def test_another_list_is_neither_reported_nor_counted(L):
    other = lists.create_list("UTC")["list_id"]
    since = service.changes(L)["next_since"]
    service.create_todo(other, "theirs")
    service.create_project(other, "theirs")
    out = service.changes(L, since)
    assert out["changed"] is False and out["next_since"] == since
    assert ids(service.changes(other))["todos"] != []


def test_a_place_ahead_of_the_list_gets_everything_and_says_reset(L):
    todo = service.create_todo(L, "a")
    out = service.changes(L, head(L) + 50)  # the database was put back
    assert out["reset"] is True and ids(out)["todos"] == [todo["id"]]
    assert out["next_since"] == head(L)


@pytest.mark.parametrize("args", [{"since": -1}, {"limit": 0}, {"limit": 501}])
def test_bad_arguments_are_refused(L, args):
    with pytest.raises(ValidationError):
        service.changes(L, **args)


def test_a_one_list_repair_sends_every_syncing_tool_back_to_a_full_sync(L):
    """scripts/restore_list.py removes rows made since the snapshot, which no
    list of changes can say, so a tool that synced before it gets `reset`."""
    from backend import backup
    from scripts import restore_list

    kept = service.create_todo(L, "kept")
    other = lists.create_list("UTC")["list_id"]
    theirs = service.changes(other)["next_since"]
    snapshot = backup.snapshot()
    service.update_todo(L, kept["id"], {"title": "mistake"})
    service.create_todo(L, "made after the snapshot")
    since = service.changes(L)["next_since"]
    db.close_db()
    restore_list.restore(snapshot, L, db.db_path())
    db.init_db()
    out = service.changes(L, since)
    assert out["reset"] is True and [t["title"] for t in out["todos"]] == ["kept"]
    # Synced again, it is back to plain changes; a first sync and other lists never reset.
    after = service.changes(L, out["next_since"])
    assert (after["reset"], after["changed"]) == (False, False)
    assert service.changes(L)["reset"] is False
    assert service.changes(other, theirs)["reset"] is False


pytestmark_async = pytest.mark.anyio


@pytestmark_async
async def test_the_command_and_the_tool_report_the_same_changes(http, connect, made):
    url = f"/mcp/{made['agent_token']}"
    first = (await http.get(f"{url}?cmd=CHANGES")).json()
    assert first["ok"] is True and first["changed"] is False
    added = (await http.post(f"{url}?cmd=ADD", json={"title": "Buy paint"})).json()["todo"]
    out = (await http.get(f"{url}?cmd=CHANGES&since={first['next_since']}")).json()
    assert out["changed"] is True and [t["id"] for t in out["todos"]] == [added["id"]]
    assert out["todos"][0]["rev"] == added["rev"] == out["next_since"]

    async with connect(link(made)) as c:
        same = await call(c, "todo_changes", since=first["next_since"])
        assert [t["id"] for t in same["todos"]] == [added["id"]]
        assert same["next_since"] == out["next_since"]
        assert (await call(c, "todo_changes", since=same["next_since"]))["changed"] is False
        everything = await call(c, "todo_changes")
        assert [t["id"] for t in everything["todos"]] == [added["id"]]

    # The count says the same on both.
    count = (await http.get(f"{url}?cmd=CHANGES_COUNT")).json()
    assert count == {"ok": True, **service.changes_count(made["list_id"])}
    assert count["count"] == out["next_since"]
    async with connect(link(made)) as c:
        assert await call(c, "todo_changes_count") == {
            "count": count["count"],
            "last_change_at": count["last_change_at"],
        }

    # A read: POST is refused, and so is a bad number.
    assert (await http.post(f"{url}?cmd=CHANGES")).status_code == 405
    assert (await http.post(f"{url}?cmd=CHANGES_COUNT")).status_code == 405
    assert (await http.get(f"{url}?cmd=CHANGES&since=-1")).status_code == 400
    assert (await http.get(f"{url}?cmd=CHANGES&limit=0")).status_code == 400


def test_edits_made_in_the_web_app_reach_a_syncing_tool(new_list):
    """The surface a person uses is the web app; a tool keeping a copy in step reads CHANGES on the agent link. Every web-app write must show up there."""
    made = new_list()
    web, api = made["client"], made["api"]
    link = f"/mcp/{lists.get_list(made['list_id'])['agent_token']}"
    start = web.get(f"{link}?cmd=CHANGES").json()["next_since"]

    todo = web.post(f"{api}/todos", json={"title": "Call the plumber"}).json()
    project = web.post(f"{api}/projects", json={"name": "Fix the leak"}).json()
    added = web.get(f"{link}?cmd=CHANGES&since={start}").json()
    assert [t["id"] for t in added["todos"]] == [todo["id"]]
    assert [p["id"] for p in added["projects"]] == [project["id"]]

    # An edit alone, read from a cursor past the creation, so only the edit can report it.
    web.put(f"{api}/todos/{todo['id']}", json={"tags": ["errand"], "project_id": project["id"]})
    out = web.get(f"{link}?cmd=CHANGES&since={added['next_since']}").json()
    assert out["changed"] is True and out["projects"] == []
    assert [t["id"] for t in out["todos"]] == [todo["id"]]
    assert out["todos"][0]["tags"] == ["errand"] and out["todos"][0]["project_id"] == project["id"]

    # Completing it and renaming the project are changes too; the count says so first.
    count = web.get(f"{link}?cmd=CHANGES_COUNT").json()["count"]
    web.put(f"{api}/todos/{todo['id']}", json={"status": "done"})
    web.put(f"{api}/projects/{project['id']}", json={"name": "Fixed the leak", "status": "completed"})
    assert web.get(f"{link}?cmd=CHANGES_COUNT").json()["count"] > count
    later = web.get(f"{link}?cmd=CHANGES&since={out['next_since']}").json()
    assert [t["status"] for t in later["todos"]] == ["done"]
    assert [(p["name"], p["status"]) for p in later["projects"]] == [("Fixed the leak", "completed")]
    assert web.get(f"{link}?cmd=CHANGES&since={later['next_since']}").json()["changed"] is False
