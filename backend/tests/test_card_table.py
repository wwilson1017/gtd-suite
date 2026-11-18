"""Projects GTD's Card Table in Basecamp's shape with Trello's card fields
(boards.py): fixed Triage / Not now / Done, On Hold, soft card limits, labels,
assignees, dates, completion, the column actions, and step 9 of the migration."""

import sqlite3

import pytest

from backend import boards, db, people, recordings
from backend.common import ConflictError, NotFoundError, ValidationError


@pytest.fixture()
def B(L) -> int:
    return boards.create_board(L, "Kitchen")["id"]  # Triage, Not now, In progress, Done


def col(L, B, name) -> dict:
    return next(c for c in boards.get_board(L, B)["columns"] if c["name"] == name)


def test_cards_carry_trello_fields(L, B):
    people.add(L, "Ana")
    card = boards.create_card(
        L,
        B,
        "Order tile",
        column="In progress",
        assignee_ids=["Ana", "me"],
        labels=["Urgent", "Design"],
        starts_on="2026-11-01",
        due_date="2026-11-05",
        cover="blue",
    )
    assert [a["name"] for a in card["assignees"]] == ["Ana", "Me"]
    assert [(lbl["name"], bool(lbl["color"])) for lbl in card["labels"]] == [("Urgent", True), ("Design", True)]
    assert (card["starts_on"], card["due_date"], card["cover"]) == ("2026-11-01", "2026-11-05", "blue")
    # Two new labels get two different colours; a name used again finds the same label.
    labels = boards.list_labels(L, B)
    assert len({lbl["color"] for lbl in labels}) == 2
    again = boards.update_card(L, card["id"], {"labels": ["urgent"]})
    assert [lbl["id"] for lbl in again["labels"]] == [labels[0]["id"]]
    with pytest.raises(ValidationError, match="starts_on must not be after"):
        boards.update_card(L, card["id"], {"starts_on": "2026-12-01"})
    with pytest.raises(ValidationError, match="color must be one of"):
        boards.update_card(L, card["id"], {"cover": "plaid"})
    with pytest.raises(ValidationError, match="Label not found"):
        boards.update_card(L, card["id"], {"labels": [999999]})
    recordings.create(L, None, "step", {"title": "Measure"}, card_id=card["id"])
    step = recordings.create(L, None, "step", {"title": "Call"}, card_id=card["id"])
    recordings.complete(L, step["id"])
    face = boards.get_card(L, card["id"])
    assert (face["steps_done"], face["steps_count"]) == (1, 2)
    full = boards.get_card(L, card["id"], thread=True)
    assert [s["title"] for s in full["subtasks"]] == ["Measure", "Call"]


def test_completing_moves_to_done_and_reopening_moves_back(L, B):
    card = boards.create_card(L, B, "Paint")
    done = boards.update_card(L, card["id"], {"completed": True})
    assert (done["column_kind"], done["completed"]) == ("done", True)
    assert boards.get_board(L, B)["columns"][-1]["cards"][0]["id"] == card["id"]
    back = boards.update_card(L, card["id"], {"completed": False})
    assert (back["column_name"], back["completed"]) == ("In progress", False)
    assert recordings.activity(L)["events"][0]["verb"] == "re-opened"


def test_on_hold_needs_a_section_and_leaving_the_column_clears_it(L, B):
    progress = col(L, B, "In progress")
    card = boards.create_card(L, B, "Wait for permit", column="In progress")
    with pytest.raises(ValidationError, match="no On Hold section"):
        boards.update_card(L, card["id"], {"on_hold": True})
    boards.update_column(L, progress["id"], {"has_on_hold": True})
    assert boards.update_card(L, card["id"], {"on_hold": True})["on_hold"] is True
    assert boards.move_card(L, card["id"], "In progress", "top")["on_hold"] is True  # a reorder keeps it
    assert boards.move_card(L, card["id"], "Triage")["on_hold"] is False
    held = boards.move_card(L, card["id"], "In progress", on_hold=True)
    assert held["on_hold"] is True
    before = boards.get_card(L, card["id"])["version"]
    boards.update_column(L, progress["id"], {"has_on_hold": False})
    after = boards.get_card(L, card["id"])
    assert after["on_hold"] is False and after["version"] == before + 1


def test_work_columns_take_colour_and_a_soft_limit(L, B):
    progress = col(L, B, "In progress")
    board = boards.update_column(L, progress["id"], {"color": "purple", "card_limit": 2})
    column = next(c for c in board["columns"] if c["id"] == progress["id"])
    assert (column["color"], column["card_limit"]) == ("purple", 2)
    for t in "abc":  # over the limit is allowed: it only warns
        boards.create_card(L, B, t, column="In progress")
    assert len(col(L, B, "In progress")["cards"]) == 3
    with pytest.raises(ValidationError, match="whole number"):
        boards.update_column(L, progress["id"], {"card_limit": -1})
    assert boards.update_column(L, progress["id"], {"card_limit": None})["columns"][2]["card_limit"] is None


def test_move_all_archive_all_and_sort(L, B):
    for t, due in (("b", "2026-11-02"), ("a", None), ("c", "2026-11-01")):
        boards.create_card(L, B, t, due_date=due)
    triage = col(L, B, "Triage")
    boards.sort_column(L, triage["id"], "due")
    assert [c["title"] for c in col(L, B, "Triage")["cards"]] == ["c", "b", "a"]
    boards.sort_column(L, triage["id"], "title")
    assert [c["title"] for c in col(L, B, "Triage")["cards"]] == ["a", "b", "c"]
    boards.move_all_cards(L, triage["id"], "done")
    done = col(L, B, "Done")
    assert [c["title"] for c in done["cards"]] == ["a", "b", "c"] and all(c["completed"] for c in done["cards"])
    boards.archive_all_cards(L, done["id"])
    assert col(L, B, "Done")["cards"] == [] and boards.get_board(L, B)["archived_cards"] == 3
    with pytest.raises(ValidationError, match="Sort by"):
        boards.sort_column(L, triage["id"], "colour")
    with pytest.raises(NotFoundError):
        boards.move_all_cards(L, 999999, "Done")


def test_labels_are_per_project_and_archive_rather_than_delete(L, B):
    label = boards.create_label(L, B, "Bug", "red")
    card = boards.create_card(L, B, "Leak", labels=[label["id"]])
    boards.update_label(L, label["id"], {"status": "archived"})
    assert boards.get_card(L, card["id"])["labels"] == []
    assert [lbl["name"] for lbl in boards.list_labels(L, B, "archived")] == ["Bug"]
    with pytest.raises(ValidationError, match="name or a colour"):
        boards.create_label(L, B)


def test_assigned_cards_are_open_ones_only(L, B):
    a = boards.create_card(L, B, "Mine", assignee_ids=["me"], due_date="2026-11-03")
    boards.create_card(L, B, "Also mine", assignee_ids=["me"], due_date="2026-11-01")
    boards.update_card(L, a["id"], {"completed": True})
    assert [c["title"] for c in boards.assigned_cards(L)] == ["Also mine"]


def test_step_9_gives_an_old_board_triage_not_now_and_done(tmp_path, monkeypatch):
    """A database from before card tables had kinds: the migration keeps every card
    and makes the rightmost column Done, completing its cards."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPEN_SIGNUP", "true")
    db.init_db()
    from backend import lists

    list_id = lists.create_list("UTC")["list_id"]
    board = boards.create_board(list_id, "Old", columns=["To do", "Doing", "Done"])
    boards.create_card(list_id, board["id"], "a", column="To do")
    boards.create_card(list_id, board["id"], "z", column="Done")
    db.close_db()
    conn = sqlite3.connect(tmp_path / "todo.db")
    conn.executescript(
        "DELETE FROM board_columns WHERE kind IN ('triage', 'not_now'); "
        "UPDATE cards SET completed_at = NULL; "
        "ALTER TABLE board_columns DROP COLUMN kind; ALTER TABLE cards DROP COLUMN completed_at;"
    )
    conn.close()
    db.init_db()
    try:
        old = boards.get_board(list_id, board["id"])
        assert [(c["name"], c["kind"]) for c in old["columns"]] == [
            ("Triage", "triage"),
            ("Not now", "not_now"),
            ("To do", "column"),
            ("Doing", "column"),
            ("Done", "done"),
        ]
        assert [c["title"] for c in old["columns"][2]["cards"]] == ["a"]
        assert old["columns"][-1]["cards"][0]["completed"] is True
        db.init_db()  # again: nothing more is added
        assert len(boards.get_board(list_id, board["id"])["columns"]) == 5
    finally:
        db.close_db()


# ── The agent link ────────────────────────────────────────────────────────────

from backend.tests.test_mcp import (  # noqa: E402,F401 (fixtures)
    anyio_backend,
    app,
    call,
    connect,
    http,
    link,
    made,
)


@pytest.mark.anyio
async def test_an_agent_files_a_card_by_column_kind_with_trello_fields(connect, made):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Garage", columns=["Doing", "Shipped"])
        card = (
            await call(
                c,
                "card_create",
                project="garage",
                title="Sort tools",
                labels=["Weekend"],
                assignees=["me"],
                starts_on="2026-11-01",
            )
        )["card"]
        assert (card["column_kind"], [lbl["name"] for lbl in card["labels"]]) == ("triage", ["Weekend"])
        done = (await call(c, "card_move", id=card["id"], column="done"))["card"]
        assert (done["column_name"], done["completed"]) == ("Shipped", True)
        back = (await call(c, "card_update", id=card["id"], completed=False))["card"]
        assert back["column_name"] == "Doing"
        await call(c, "item_create", project="Garage", type="step", card_id=card["id"], title="Pegboard")
        full = (await call(c, "card_get", id=card["id"]))["card"]
        assert [s["title"] for s in full["subtasks"]] == ["Pegboard"]


@pytest.mark.anyio
async def test_card_commands_take_people_labels_and_hold(http, made):
    base = f"/mcp/{made['agent_token']}"
    await http.post(f"{base}?cmd=CREATE_BOARD", json={"name": "Trip"})
    card = (
        await http.post(
            f"{base}?cmd=ADD_CARD&project=Trip", json={"title": "Book", "labels": ["Travel"], "assignees": ["me"]}
        )
    ).json()["card"]
    assert [lbl["name"] for lbl in card["labels"]] == ["Travel"]
    res = await http.post(f"{base}?cmd=MOVE_CARD&id={card['id']}", json={"column": "In progress", "on_hold": True})
    assert res.status_code == 400 and "On Hold" in res.json()["error"]
    res = await http.post(
        f"{base}?cmd=UPDATE_CARD&id={card['id']}", json={"assignees": [], "labels": ["Travel", "Urgent"]}
    )
    assert (res.json()["card"]["assignees"], len(res.json()["card"]["labels"])) == ([], 2)
    res = await http.post(f"{base}?cmd=UPDATE_CARD&id={card['id']}", json={"completed": True})
    assert res.json()["card"]["column_kind"] == "done"


def test_the_card_table_api_round_trip(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    board = c.post(f"{api}/boards", json={"name": "Shop"}).json()
    cols = {col["kind"] if col["kind"] != "column" else col["name"]: col["id"] for col in board["columns"]}
    card = c.post(
        f"{api}/boards/{board['id']}/cards",
        json={"title": "Sign", "labels": ["Paint"], "assignee_ids": ["me"], "starts_on": "2026-11-01", "cover": "red"},
    ).json()
    assert (
        [lbl["name"] for lbl in card["labels"]],
        card["assignees"][0]["kind"],
        card["starts_on"],
        card["cover"],
    ) == (["Paint"], "me", "2026-11-01", "red")
    c.put(f"{api}/columns/{cols['In progress']}", json={"has_on_hold": True})
    moved = c.post(f"{api}/cards/{card['id']}/move", json={"column_id": cols["In progress"], "on_hold": True}).json()
    assert moved["on_hold"] is True
    done = c.put(f"{api}/cards/{card['id']}", json={"completed": True, "labels": []}).json()
    assert (done["column_kind"], done["labels"]) == ("done", [])
    for t in ("b", "a"):
        c.post(f"{api}/boards/{board['id']}/cards", json={"title": t})
    res = c.post(f"{api}/columns/{cols['triage']}/sort", json={"by": "title"})
    assert res.headers["cache-control"] == "no-store"
    assert [x["title"] for x in res.json()["columns"][0]["cards"]] == ["a", "b"]
    after = c.post(f"{api}/columns/{cols['triage']}/move-cards", json={"to_column_id": cols["not_now"]}).json()
    assert [len(col["cards"]) for col in after["columns"][:2]] == [0, 2]
    after = c.post(f"{api}/columns/{cols['not_now']}/archive-cards").json()
    assert after["archived_cards"] == 2
    label = c.post(f"{api}/boards/{board['id']}/labels", json={"name": "Rush", "color": "orange"}).json()
    assert c.put(f"{api}/labels/{label['id']}", json={"name": "Urgent"}).json()["name"] == "Urgent"
    assert [lbl["name"] for lbl in c.get(f"{api}/boards/{board['id']}/labels").json()["labels"]] == ["Paint", "Urgent"]
    other = new_list()["client"]
    assert other.put(f"{api}/labels/{label['id']}", json={"name": "x"}).status_code == 404
    assert other.post(f"{api}/columns/{cols['triage']}/sort", json={"by": "title"}).status_code == 404


def test_the_fixed_words_always_mean_the_fixed_columns(L, B):
    done = col(L, B, "Done")
    boards.update_column(L, done["id"], {"name": "Shipped"})
    with pytest.raises(ValidationError, match="fixed columns"):
        boards.add_column(L, B, "Done")
    with pytest.raises(ValidationError, match="fixed columns"):
        boards.update_column(L, col(L, B, "In progress")["id"], {"name": "Not now"})
    card = boards.create_card(L, B, "x")
    assert boards.move_card(L, card["id"], "done")["column_name"] == "Shipped"


def test_a_moved_card_keeps_its_colour_only_labels(L, B):
    plain = boards.create_label(L, B, "", "purple")
    card = boards.create_card(L, B, "x", labels=[plain["id"], "Named"])
    other = boards.create_board(L, "Other")["id"]
    moved = boards.move_card(L, card["id"], "triage", board=other)
    assert sorted((lbl["name"], lbl["color"]) for lbl in moved["labels"])[0] == ("", "purple")
    assert {lbl["name"] for lbl in moved["labels"]} == {"", "Named"}
    back = boards.move_card(L, card["id"], "triage", board=B)
    assert [lbl["id"] for lbl in back["labels"] if not lbl["name"]] == [plain["id"]]


def test_a_numeric_label_name_travels_as_a_name(L, B):
    card = boards.create_card(L, B, "x")
    boards.create_label(L, B, "2026", "blue")
    card = boards.update_card(L, card["id"], {"labels": [boards.list_labels(L, B)[0]["id"]]})
    other = boards.create_board(L, "Other")["id"]
    moved = boards.move_card(L, card["id"], "triage", board=other)
    assert [(lbl["name"], lbl["color"]) for lbl in moved["labels"]] == [("2026", "blue")]


def test_a_restored_done_card_keeps_when_it_was_finished(L, B):
    card = boards.create_card(L, B, "x", column="done")
    boards.update_card(L, card["id"], {"status": "archived"})
    back = boards.update_card(L, card["id"], {"status": "active"})
    assert back["completed_at"] == card["completed_at"]


# ── A move that names the card's version ──────────────────────────────────────


def _table(L, B) -> list:
    """Everything a move could change: each column's cards in order, with their
    place, On Hold and version."""
    return [
        (c["name"], [(k["id"], k["position"], k["on_hold"], k["completed"], k["version"]) for k in c["cards"]])
        for c in boards.get_board(L, B)["columns"]
    ]


def test_a_move_from_an_older_version_is_refused_and_changes_nothing(L, B):
    boards.update_column(L, col(L, B, "In progress")["id"], {"has_on_hold": True})
    first, held, last = (boards.create_card(L, B, t, column="In progress") for t in ("first", "held", "last"))
    held = boards.update_card(L, held["id"], {"on_hold": True})
    boards.append_note(L, held["id"], "agent was here", by="Claude")  # it changed after it was read
    table, trail = _table(L, B), [e["id"] for e in recordings.activity(L)["events"]]
    for column, position, on_hold in (("triage", "top", False), ("In progress", 0, False), ("done", None, None)):
        with pytest.raises(ConflictError, match="changed since it was opened"):
            boards.move_card(L, held["id"], column, position, on_hold=on_hold, version=held["version"])
    assert _table(L, B) == table  # column, On Hold, places and version, of every card
    assert [e["id"] for e in recordings.activity(L)["events"]] == trail
    assert boards.get_card(L, held["id"])["notes"].endswith("· Claude: agent was here")
    # The same refusal as an edit's, word for word.
    with pytest.raises(ConflictError) as edit:
        boards.update_card(L, held["id"], {"title": "x"}, version=held["version"])
    with pytest.raises(ConflictError) as move:
        boards.move_card(L, held["id"], "triage", version=held["version"])
    assert str(move.value) == str(edit.value)
    # With the version it has now, the same move goes through.
    fresh = boards.get_card(L, held["id"])
    moved = boards.move_card(L, held["id"], "triage", "top", version=fresh["version"])
    assert (moved["column_kind"], moved["on_hold"], moved["version"]) == ("triage", False, fresh["version"] + 1)
    assert [k["id"] for k in col(L, B, "In progress")["cards"]] == [first["id"], last["id"]]


def test_a_move_without_a_version_works_as_before(L, B):
    card = boards.create_card(L, B, "Paint")
    boards.append_note(L, card["id"], "agent was here", by="Claude")
    moved = boards.move_card(L, card["id"], "In progress")  # never asked what it read
    assert moved["column_name"] == "In progress"
    assert recordings.activity(L)["events"][0]["action"] == "moved"


def test_a_completed_card_goes_back_where_it_was_in_one_move(new_list):
    """What Todo's "From Projects GTD" group sends: complete with the version read,
    then one move back to the column and On Hold it remembered, with the version the
    completion answered."""
    made = new_list()
    c, api = made["client"], made["api"]
    board = c.post(f"{api}/boards", json={"name": "Shop", "columns": ["To do", "Doing", "Done"]}).json()
    doing = next(x["id"] for x in board["columns"] if x["name"] == "Doing")
    c.put(f"{api}/columns/{doing}", json={"has_on_hold": True})
    card = c.post(
        f"{api}/boards/{board['id']}/cards", json={"title": "Sign", "column_id": doing, "assignee_ids": ["me"]}
    ).json()
    card = c.put(f"{api}/cards/{card['id']}", json={"on_hold": True}).json()
    assert [x["id"] for x in c.get(f"{api}/assignments").json()["cards"]] == [card["id"]]

    done = c.put(f"{api}/cards/{card['id']}", json={"completed": True, "version": card["version"]}).json()
    assert (done["column_kind"], done["on_hold"], done["completed"]) == ("done", False, True)
    assert c.get(f"{api}/assignments").json()["cards"] == []
    undo = {"column_id": card["column_id"], "on_hold": card["on_hold"]}
    back = c.post(f"{api}/cards/{card['id']}/move", json={**undo, "version": done["version"]})
    assert back.status_code == 200
    assert (back.json()["column_id"], back.json()["on_hold"], back.json()["completed"]) == (doing, True, False)

    # Completed again, then changed somewhere else before the Undo: nothing is overwritten.
    done = c.put(f"{api}/cards/{card['id']}", json={"completed": True, "version": back.json()["version"]}).json()
    c.put(f"{api}/cards/{card['id']}", json={"title": "Sign, both sides"})
    stale = c.post(f"{api}/cards/{card['id']}/move", json={**undo, "version": done["version"]})
    assert stale.status_code == 409 and stale.headers["cache-control"] == "no-store"
    assert "changed since it was opened" in stale.json()["detail"]
    now = c.get(f"{api}/cards/{card['id']}").json()
    assert (now["column_kind"], now["title"], now["version"]) == ("done", "Sign, both sides", done["version"] + 1)
