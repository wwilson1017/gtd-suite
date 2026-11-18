"""Projects GTD's Card Table wormholes and the To-dos Markdown import
(recordings._check_wormhole, boards._wormholes, recordings.import_todos)."""

import pytest

from backend import boards, common, lists, recordings
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


def column(L, board, kind=None, name=None):
    cols = boards.get_board(L, board)["columns"]
    return next(c for c in cols if (kind and c["kind"] == kind) or (name and c["name"] == name))


def test_a_wormhole_sends_cards_to_another_projects_column(L, B):
    shop = boards.create_board(L, "Shop")["id"]
    target = column(L, shop, kind="triage")
    hole = recordings.create(L, B, "wormhole", {"column_id": target["id"]})
    [shown] = boards.get_board(L, B)["wormholes"]
    assert shown == {
        "id": hole["id"],
        "column_id": target["id"],
        "column_name": target["name"],
        "project_id": shop,
        "project_name": "Shop",
    }
    card = boards.create_card(L, B, "Order tile")
    boards.move_card(L, card["id"], shown["column_id"])  # what a drop on it does
    assert boards.get_card(L, card["id"])["board_id"] == shop
    # Its column is fixed; one to the same column, to this project, or to nothing is refused.
    with pytest.raises(ValidationError, match="fixed"):
        recordings.update(L, hole["id"], {"column_id": column(L, shop, kind="done")["id"]})
    for bad, match in (
        ({"column_id": target["id"]}, "already"),
        ({"column_id": column(L, B, kind="done")["id"]}, "another project"),
        ({"column_id": 10**9}, "No such column"),
        ({}, "needs column_id"),
        ({"column_id": True}, "column's id"),
    ):
        with pytest.raises(ValidationError, match=match):
            recordings.create(L, B, "wormhole", bad)
    # It stays on its table: no moving or copying it, which would skip the checks.
    with pytest.raises(ValidationError, match="stays on its table"):
        recordings.move(L, hole["id"], board=shop)
    with pytest.raises(ValidationError, match="can't be copied"):
        recordings.copy(L, hole["id"], board=shop)
    # Archived, it closes; an archived project's wormholes are hidden.
    recordings.update(L, hole["id"], {"status": "archived"})
    assert boards.get_board(L, B)["wormholes"] == []
    recordings.update(L, hole["id"], {"status": "active"})
    boards.update_board(L, shop, {"status": "archived"})
    assert boards.get_board(L, B)["wormholes"] == []


def test_a_table_has_at_most_four_wormholes(L, B):
    holes = []
    for n in range(4):
        other = boards.create_board(L, f"P{n}")["id"]
        holes.append(recordings.create(L, B, "wormhole", {"column_id": column(L, other, kind="triage")["id"]}))
    fifth = column(L, boards.create_board(L, "P4")["id"], kind="triage")["id"]
    with pytest.raises(ValidationError, match="at most 4"):
        recordings.create(L, B, "wormhole", {"column_id": fifth})
    recordings.update(L, holes[0]["id"], {"status": "archived"})
    extra = recordings.create(L, B, "wormhole", {"column_id": fifth})
    with pytest.raises(ValidationError, match="at most 4"):  # restoring one would make five
        recordings.update(L, holes[0]["id"], {"status": "active"})
    assert len(boards.get_board(L, B)["wormholes"]) == 4 and extra["id"]


def test_markdown_becomes_lists_todos_and_subtasks(L, B):
    out = recordings.import_todos(
        L,
        B,
        "- Loose one\n\n# Week one\n- Measure\n  - [x] Wall A\n  * Wall B\n"
        "1. [x] Book the fitter\n## Week two\n[ ] Tile\n",
    )
    assert out == {"lists": 2, "groups": 0, "todos": 4, "subtasks": 2, "completed": 2}
    todoset = recordings.todoset(L, B)
    assert [t["title"] for t in todoset["loose"]] == ["Loose one"]
    week_one, week_two = todoset["lists"]
    assert week_one["title"] == "Week one" and [t["title"] for t in week_one["children"]] == ["Measure"]
    assert [t["title"] for t in week_one["completed_todos"]] == ["Book the fitter"]
    steps = recordings.children(L, week_one["children"][0]["id"])
    assert [(s["title"], s["completed"]) for s in steps] == [("Wall A", True), ("Wall B", False)]
    assert [t["title"] for t in week_two["children"]] == ["Tile"]


def test_importing_into_a_list_makes_groups(L, B):
    tl = recordings.create(L, B, "todolist", {"title": "Launch"})
    out = recordings.import_todos(L, None, "- First\n# Design\n- Logo\n", parent_id=tl["id"])
    assert out == {"lists": 0, "groups": 1, "todos": 2, "subtasks": 0, "completed": 0}
    with pytest.raises(ValidationError, match="list or a group"):
        recordings.import_todos(L, None, "- x", parent_id=recordings.create(L, B, "message", {"title": "M"})["id"])
    group = recordings.create(L, B, "todolist_group", {"title": "Week one"}, parent_id=tl["id"])
    out = recordings.import_todos(L, None, "## Learn C# ##\n- Read\n# ###\n", parent_id=group["id"])
    assert out["groups"] == 0 and out["todos"] == 2  # inside a group a heading is a to-do; an empty one is skipped
    assert [t["title"] for t in recordings.children(L, group["id"])] == ["Learn C#", "Read"]
    recordings.update(L, tl["id"], {"status": "archived"})
    with pytest.raises(ValidationError):
        recordings.import_todos(L, None, "- x", parent_id=tl["id"])
    for bad, match in (("\n# Only a heading\n", "Nothing to import"), ("- x\n" * 501, "At most 500")):
        with pytest.raises(ValidationError, match=match):
            recordings.import_todos(L, B, bad)


def test_an_import_over_the_cap_adds_nothing(L, B, monkeypatch):
    have = len(recordings.todoset(L, B)["loose"])
    monkeypatch.setattr(common, "recording_cap_for", lambda verified, hosted, pro=False: have + 2)
    with pytest.raises(ValidationError):
        recordings.import_todos(L, B, "- a\n- b\n- c")
    assert recordings.todoset(L, B)["loose"] == []


def test_another_accounts_columns_and_lists_are_out_of_reach(L, B):
    other = lists.create_list("America/Chicago")["list_id"]
    theirs = boards.create_board(other, "Theirs")["id"]
    with pytest.raises(ValidationError, match="No such column"):
        recordings.create(L, B, "wormhole", {"column_id": column(other, theirs, kind="triage")["id"]})
    their_list = recordings.create(other, theirs, "todolist", {"title": "Theirs"})
    with pytest.raises(Exception, match="Not found"):
        recordings.import_todos(L, None, "- x", parent_id=their_list["id"])
    assert recordings.children(other, their_list["id"]) == []


def test_the_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K"}).json()["id"]
    shop = c.post(f"{api}/boards", json={"name": "Shop"}).json()
    triage = next(col for col in c.get(f"{api}/boards/{shop['id']}").json()["columns"] if col["kind"] == "triage")
    assert (
        c.post(f"{api}/projects/{pid}/items", json={"type": "wormhole", "column_id": triage["id"]}).status_code == 200
    )
    assert [w["project_name"] for w in c.get(f"{api}/boards/{pid}").json()["wormholes"]] == ["Shop"]
    assert c.post(f"{api}/projects/{pid}/todos/import", json={"text": "# L\n- a\n- b"}).json()["todos"] == 2
    assert c.post(f"{api}/projects/{pid}/todos/import", json={"text": "# Only a heading"}).status_code == 400


@pytest.mark.anyio
async def test_an_agent_imports_a_plan(connect, made, http):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Garage")
        out = await call(
            c, "todos_import", project="Garage", markdown="# Clear-out\n- Sort\n  - Tools\n- [x] Skip booked"
        )
        assert out == {"lists": 1, "groups": 0, "todos": 2, "subtasks": 1, "completed": 1}
    base, ua = f"/mcp/{made['agent_token']}", {"User-Agent": "Claude/1.0"}
    posted = await http.post(f"{base}?cmd=IMPORT_TODOS&project=Garage", json={"markdown": "- One more"}, headers=ua)
    assert posted.json()["todos"] == 1
    assert (
        await http.post(f"{base}?cmd=IMPORT_TODOS&project=Garage", json={"text": "- x"}, headers=ua)
    ).status_code == 400
    assert (await http.get(f"{base}?cmd=IMPORT_TODOS&project=Garage", headers=ua)).status_code == 405
