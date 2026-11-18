"""Projects GTD: boards, columns and cards (boards.py), the web app's board API,
and the same boards through the agent link (MCP tools and Agent Commands)."""

import datetime

import pytest

from backend import boards, cleanup, common, db, lists
from backend.common import ConflictError, NotFoundError, ValidationError
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    anyio_backend,
    app,
    call,
    connect,
    http,
    link,
    made,
)
from backend.tests.test_pages import built  # noqa: F401 (fixture)


def titles(board: dict) -> dict[str, list[str]]:
    return {c["name"]: [card["title"] for card in c["cards"]] for c in board["columns"]}


def kinds(board: dict) -> list[tuple[str, str]]:
    return [(c["name"], c["kind"]) for c in board["columns"]]


@pytest.fixture()
def B(L) -> int:
    """A fresh board on the list L: Triage, Not now, To do, Doing, Done."""
    return boards.create_board(L, "Kitchen", columns=["To do", "Doing", "Done"])["id"]


# ── The service ───────────────────────────────────────────────────────────────


def test_a_new_card_table_is_shaped_as_basecamps(L, B):
    fresh = boards.create_board(L, "Garden")
    assert kinds(fresh) == [("Triage", "triage"), ("Not now", "not_now"), ("In progress", "column"), ("Done", "done")]
    board = boards.get_board(L, B)
    assert kinds(board)[2:] == [("To do", "column"), ("Doing", "column"), ("Done", "done")]
    assert [c["done"] for c in board["columns"]] == [False, False, False, False, True]
    assert boards.get_board(L, "kitchen")["id"] == B  # by name, any case
    with pytest.raises(ValidationError, match="already exists"):
        boards.create_board(L, "KITCHEN")
    with pytest.raises(ValidationError, match="Triage and Not now are there already"):
        boards.create_board(L, "Odd", columns=["Triage", "Done"])


def test_cards_land_in_triage_at_the_bottom_but_on_top_of_done(L, B):
    for t in ("a", "b"):
        boards.create_card(L, B, t)
    boards.create_card(L, B, "c", position="top")
    for t in ("x", "y"):
        boards.create_card(L, B, t, column="done")
    assert titles(boards.get_board(L, B)) == {
        "Triage": ["c", "a", "b"],
        "Not now": [],
        "To do": [],
        "Doing": [],
        "Done": ["y", "x"],
    }
    assert all(c["completed"] for c in boards.get_board(L, B)["columns"][-1]["cards"])


def test_moving_renumbers_the_target_column(L, B):
    a, b, c = (boards.create_card(L, B, t, column="To do")["id"] for t in "abc")
    boards.move_card(L, c, "To do", 0)
    boards.move_card(L, a, "Doing")
    boards.move_card(L, b, "Doing", "top")
    board = boards.get_board(L, B)
    assert titles(board)["To do"] == ["c"] and titles(board)["Doing"] == ["b", "a"]
    assert [card["position"] for card in board["columns"][3]["cards"]] == [0, 1]
    with pytest.raises(NotFoundError, match="Triage, Not now, To do, Doing, Done"):
        boards.move_card(L, a, "Nope")


def test_fixed_columns_answer_to_their_kind_whatever_their_name(L, B):
    cols = boards.get_board(L, B)["columns"]
    boards.update_column(L, cols[-1]["id"], {"name": "Shipped"})
    card = boards.create_card(L, B, "a")
    assert card["column_kind"] == "triage"
    done = boards.move_card(L, card["id"], "done")
    assert (done["column_name"], done["completed"]) == ("Shipped", True)
    back = boards.move_card(L, card["id"], "not now")
    assert (back["column_name"], back["completed"]) == ("Not now", False)
    for fixed in (cols[0], cols[1], cols[-1]):
        with pytest.raises(ValidationError, match="fixed"):
            boards.update_column(L, fixed["id"], {"status": "archived"})
        with pytest.raises(ValidationError, match="fixed"):
            boards.update_column(L, fixed["id"], {"color": "red"})


def test_a_card_can_move_to_another_board_by_name_or_column_id(L, B):
    card = boards.create_card(L, B, "a", labels=["Urgent"])["id"]
    other = boards.create_board(L, "Garden", columns=["Ideas", "Done"])
    moved = boards.move_card(L, card, "Ideas", board="Garden")
    assert moved["board_name"] == "Garden" and [lbl["name"] for lbl in moved["labels"]] == ["Urgent"]
    assert [lbl["name"] for lbl in boards.list_labels(L, other["id"])] == ["Urgent"]
    doing = next(c for c in boards.get_board(L, B)["columns"] if c["name"] == "Doing")
    back = boards.move_card(L, card, doing["id"])
    assert (back["board_id"], back["column_name"]) == (B, "Doing")
    assert titles(boards.get_board(L, other["id"]))["Ideas"] == []


def test_an_edit_from_an_older_version_is_refused(L, B):
    card = boards.create_card(L, B, "a")
    boards.append_note(L, card["id"], "agent was here", by="Claude")
    with pytest.raises(ConflictError):
        boards.update_card(L, card["id"], {"notes": "browser text"}, version=card["version"])
    fresh = boards.get_card(L, card["id"])
    assert fresh["notes"].endswith("· Claude: agent was here")
    assert boards.update_card(L, card["id"], {"title": "b"}, version=fresh["version"])["title"] == "b"


def test_appending_keeps_what_is_there(L, B):
    card = boards.create_card(L, B, "a", notes="Plan")["id"]
    assert boards.append_note(L, card, "step one done")["notes"] == "Plan\n\nstep one done"


def test_archive_and_restore_a_card(L, B):
    a, b = (boards.create_card(L, B, t, column="To do")["id"] for t in "ab")
    boards.update_card(L, a, {"status": "archived"})
    board = boards.get_board(L, B)
    assert (titles(board)["To do"], board["archived_cards"]) == (["b"], 1)
    assert [c["title"] for c in boards.archived_cards(L, B)] == ["a"]
    with pytest.raises(ValidationError, match="Restore it"):
        boards.move_card(L, a, "Doing")
    boards.update_card(L, a, {"status": "active"})
    assert titles(boards.get_board(L, B))["To do"] == ["b", "a"]


def test_only_an_empty_work_column_is_archived(L, B):
    cols = {c["name"]: c for c in boards.get_board(L, B)["columns"]}
    card = boards.create_card(L, B, "a", column="Doing")["id"]
    with pytest.raises(ValidationError, match="cards first"):
        boards.update_column(L, cols["Doing"]["id"], {"status": "archived"})
    boards.update_card(L, card, {"status": "archived"})
    boards.update_column(L, cols["Doing"]["id"], {"status": "archived"})
    boards.update_column(L, cols["To do"]["id"], {"status": "archived"})
    # Restored columns go last of the work columns; a column can be moved and renamed.
    board = boards.update_column(L, cols["To do"]["id"], {"status": "active", "position": 0})
    board = boards.add_column(L, B, "Waiting", 1)
    assert [c["name"] for c in board["columns"]] == ["Triage", "Not now", "To do", "Waiting", "Done"]
    with pytest.raises(ValidationError, match="already has"):
        boards.update_column(L, cols["To do"]["id"], {"name": "waiting"})


def test_renaming_a_column_keeps_its_place(L, B):
    first = boards.get_board(L, B)["columns"][2]["id"]
    board = boards.update_column(L, first, {"name": "Backlog"})
    assert [c["name"] for c in board["columns"]] == ["Triage", "Not now", "Backlog", "Doing", "Done"]


def test_a_ref_that_only_looks_numeric_is_a_name(L, B):
    with pytest.raises(NotFoundError):
        boards.get_board(L, "²")
    card = boards.create_card(L, B, "a")["id"]
    with pytest.raises(NotFoundError):
        boards.move_card(L, card, "²")


def test_the_agents_overview_cuts_notes_and_the_done_column(L, B):
    boards.create_card(L, B, "long", notes="x" * 500)
    for n in range(boards.DONE_SHOWN + 3):
        boards.create_card(L, B, f"d{n}", column="Done")
    board = boards.get_board(L, B, snippets=True)
    todo, done = board["columns"][0], board["columns"][-1]  # Triage, Done
    assert todo["cards"][0]["notes_cut"] and len(todo["cards"][0]["notes"]) == boards.SNIPPET_CHARS + 1
    assert (len(done["cards"]), done["more_cards"]) == (boards.DONE_SHOWN, 3)
    assert done["cards"][0]["title"] == f"d{boards.DONE_SHOWN + 2}"  # newest first


def test_an_unconfirmed_hosted_list_holds_few_boards(L):
    for n in range(common.BOARD_ANON_CAPS[0]):
        boards.create_board(L, f"b{n}")
    with pytest.raises(ValidationError, match="until an email is confirmed"):
        boards.create_board(L, "one more")


def test_boards_are_per_list(L, B):
    other = lists.create_list("UTC")["list_id"]
    with pytest.raises(NotFoundError):
        boards.get_board(other, B)
    card = boards.create_card(L, B, "a")["id"]
    with pytest.raises(NotFoundError):
        boards.update_card(other, card, {"title": "mine now"})


def test_cleanup_keeps_a_list_that_only_has_a_board(todo_db):
    made = [lists.create_list("UTC")["list_id"] for _ in range(2)]
    boards.create_board(made[0], "Only this")
    old = common.to_iso(common.utcnow() - datetime.timedelta(days=40))
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = ?", (old,))
    assert cleanup.delete_unused_lists() == 1
    assert lists.get_list(made[0]) is not None


# ── The web app's API, and the Projects host ──────────────────────────────────


def test_the_board_api_round_trip(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    board = c.post(f"{api}/boards", json={"name": "Kitchen"}).json()
    doing = board["columns"][2]["id"]
    card = c.post(f"{api}/boards/{board['id']}/cards", json={"title": "Quotes"}).json()
    moved = c.post(f"{api}/cards/{card['id']}/move", json={"column_id": doing}).json()
    assert moved["column_name"] == "In progress"
    stale = c.put(f"{api}/cards/{card['id']}", json={"notes": "x", "version": card["version"]})
    assert stale.status_code == 409 and stale.headers["cache-control"] == "no-store"
    ok = c.put(f"{api}/cards/{card['id']}", json={"notes": "x", "version": moved["version"]})
    assert ok.status_code == 200 and ok.json()["notes"] == "x"
    assert [b["cards"] for b in c.get(f"{api}/boards").json()["boards"]] == [1]
    # Another list's browser cannot see it.
    other = new_list()
    assert other["client"].get(f"{api}/boards/{board['id']}").status_code == 404


def test_projects_host_serves_the_projects_app(client, built, new_list, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    monkeypatch.setenv("PROJECTS_BASE_URL", "https://projects.example")
    on_projects = {"Host": "projects.example"}
    page = client.get("/", headers=on_projects).text
    assert '<meta name="gtd-app" content="projects">' in page and "<title>Projects GTD</title>" in page
    # The same account's agent link, on the Projects address; and the way across.
    made = new_list()
    c = made["client"]
    url = c.get("/api/app/agent-link", headers=on_projects).json()["url"]
    assert url.startswith("https://projects.example/") and url.endswith(made["agent_token"])
    assert c.post("/api/app/signin-link?app=projects").json()["url"].startswith("https://projects.example/signin/")


# ── The agent link ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_an_agent_works_a_board_over_mcp(connect, made):
    async with connect(link(made)) as c:
        board = (await call(c, "board_create", name="Garage"))["project"]
        card = (await call(c, "card_create", project="garage", title="Sort tools"))["card"]
        assert card["source"] == "agent" and card["column_name"] == "Triage"
        await call(c, "card_update", id=card["id"], append="Pegboard ordered")
        moved = (await call(c, "card_move", id=card["id"], column="Done"))["card"]
        assert moved["column_name"] == "Done"
        view = (await call(c, "board_get", project=str(board["id"])))["project"]
        assert view["columns"][-1]["cards"][0]["notes"].endswith(": Pegboard ordered")
        await call(c, "card_archive", id=card["id"])
        assert (await call(c, "board_list"))["projects"][0]["cards"] == 0


@pytest.mark.anyio
async def test_board_commands_read_by_get_and_write_by_post(http, made):
    base = f"/mcp/{made['agent_token']}"
    res = await http.post(f"{base}?cmd=CREATE_BOARD", json={"name": "Trip"})
    assert res.json()["ok"]
    assert (await http.get(f"{base}?cmd=ADD_CARD&project=Trip")).status_code == 405
    card = (await http.post(f"{base}?cmd=ADD_CARD&project=Trip", json={"title": "Book"})).json()["card"]
    res = await http.post(f"{base}?cmd=MOVE_CARD&id={card['id']}", json={"column": "In progress"})
    assert res.json()["card"]["column_name"] == "In progress"
    board = (await http.get(f"{base}?cmd=BOARD&project=trip")).json()["project"]
    assert [len(c["cards"]) for c in board["columns"]] == [0, 0, 1, 0]
    assert (await http.post(f"{base}?cmd=ARCHIVE_CARD&id={card['id']}")).json()["card"]["status"] == "archived"


def test_archived_cards_page(L, B):
    for t in "abc":
        boards.update_card(L, boards.create_card(L, B, t)["id"], {"status": "archived"})
    assert len(boards.archived_cards(L, B, limit=2)) == 2
    assert len(boards.archived_cards(L, B, limit=2, offset=2)) == 1


def test_restoring_a_snapshot_with_boards_or_from_before_them(L, B):
    import sqlite3

    from backend import backup
    from scripts import restore_list

    boards.create_card(L, B, "in the snapshot", column="To do")
    snapshot = backup.snapshot()
    boards.create_board(L, "Made later")
    restore_list.restore(snapshot, L, db.db_path())
    assert [b["name"] for b in boards.list_boards(L)] == ["Kitchen"]
    assert titles(boards.get_board(L, B))["To do"] == ["in the snapshot"]
    # A snapshot from before the Basecamp tables and the boards' project fields.
    old = sqlite3.connect(snapshot)
    old.executescript(
        "DROP TABLE boosts; DROP TABLE bookmarks; DROP TABLE events; "
        "DROP TABLE recordings; DROP TABLE people; DROP TABLE labels; "
        "ALTER TABLE boards DROP COLUMN dock; ALTER TABLE boards DROP COLUMN pinned;"
    )
    # …and from before card tables had kinds: the old columns, the last one Done by place.
    old.executescript(
        "DELETE FROM board_columns WHERE kind IN ('triage', 'not_now'); "
        "ALTER TABLE board_columns DROP COLUMN kind; "
        "ALTER TABLE cards DROP COLUMN completed_at;"
    )
    old.close()
    restore_list.restore(snapshot, L, db.db_path())
    board = boards.get_board(L, B)
    assert titles(board)["To do"] == ["in the snapshot"]
    assert kinds(board) == [
        ("Triage", "triage"),
        ("Not now", "not_now"),
        ("To do", "column"),
        ("Doing", "column"),
        ("Done", "done"),
    ]
    # A snapshot from before the board tables: the list had no boards then.
    old = sqlite3.connect(snapshot)
    old.executescript("DROP TABLE cards; DROP TABLE board_columns; DROP TABLE boards;")
    old.close()
    restore_list.restore(snapshot, L, db.db_path())
    assert boards.list_boards(L) == []
