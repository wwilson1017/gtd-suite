"""A Todo project's home in Projects GTD (project_links.py): the link and its one
transaction, the two routes, the field on the Projects GTD project, what its panel
asks Todo for, and what delete and restore do with a link."""

import sqlite3
import threading

import pytest

from backend import backup, boards, common, db, lists, mcp_server, project_links, projects_agent, recordings, service
from backend.common import NotFoundError, ValidationError
from scripts import admin, restore_list

NAME = "Plan the fall menu"


@pytest.fixture()
def P(L) -> int:
    """A Todo project on the list L."""
    return service.create_project(L, NAME)["id"]


def _count(table: str) -> int:
    return db.get_db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── The link ──────────────────────────────────────────────────────────────────


def test_promote_makes_the_project_once_and_links_it(L, P):
    before = service.changes_count(L)
    link = project_links.promote(L, P)
    assert link == {
        "project_id": P,
        "project_name": NAME,
        "project_status": "active",
        "board_id": link["board_id"],
        "board_name": NAME,
        "board_status": "active",
        "created_at": link["created_at"],
    }
    page = recordings.project(L, link["board_id"])
    # A card table, Messages and Docs. No To-dos: the to-dos stay in Todo.
    assert [t["tool"] for t in page["dock"] if t["enabled"]] == ["kanban_board", "message_board", "vault"]
    assert [c["kind"] for c in boards.get_board(L, link["board_id"])["columns"]] == [
        "triage",
        "not_now",
        "column",
        "done",
    ]
    # Asked again: the same link, and nothing more made.
    assert project_links.promote(L, P) == link
    assert project_links.links(L) == [link]
    assert _count("boards") == 1 and _count("project_links") == 1
    # Todo's own rows and its change counter are as they were.
    assert service.changes_count(L) == before
    assert service.get_project(L, P)["name"] == NAME


def test_requests_at_the_same_moment_make_one_project(L, P):
    barrier = threading.Barrier(8)
    answers, errors = [], []

    def press():
        try:
            barrier.wait()
            answers.append(project_links.promote(L, P))
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=press) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(answers) == 8 and all(a == answers[0] for a in answers)
    assert _count("boards") == 1 and _count("project_links") == 1


def test_a_failure_after_the_project_is_made_leaves_nothing(L, P, monkeypatch):
    made = boards.create_board_in

    def then_fail(*args, **kwargs):
        made(*args, **kwargs)
        assert _count("boards") == 1  # it was made, inside the transaction
        raise RuntimeError("after the project")

    with monkeypatch.context() as m:
        m.setattr(boards, "create_board_in", then_fail)
        with pytest.raises(RuntimeError, match="after the project"):
            project_links.promote(L, P)
    for table in ("boards", "board_columns", "events", "people", "project_links"):
        assert _count(table) == 0, table
    # The connection is usable again, and the next press works.
    assert project_links.promote(L, P)["board_name"] == NAME


def test_a_name_projects_gtd_already_uses_is_refused(L, P):
    boards.create_board(L, "plan the FALL menu")
    with pytest.raises(ValidationError, match=f'Projects GTD already has a project named "{NAME}"'):
        project_links.promote(L, P)
    assert project_links.links(L) == [] and _count("boards") == 1
    # Renamed, it goes through.
    service.update_project(L, P, {"name": "Fall menu"})
    assert project_links.promote(L, P)["board_name"] == "Fall menu"


def test_the_projects_cap_applies(L, P):
    cap = common.board_caps_for(False, True)[0]
    for n in range(cap):
        boards.create_board(L, f"Project {n}")
    with pytest.raises(ValidationError, match=f"This list holds {cap} boards"):
        project_links.promote(L, P)
    assert project_links.links(L) == [] and _count("boards") == cap


def test_another_accounts_project_is_not_found(L, P):
    other = lists.create_list("UTC")["list_id"]
    with pytest.raises(NotFoundError):
        project_links.promote(other, P)
    assert _count("boards") == 0
    link = project_links.promote(L, P)
    assert project_links.links(other) == []
    assert project_links.todo_project(other, link["board_id"]) is None


def test_a_link_reports_both_names_and_statuses_as_they_are_now(L, P):
    link = project_links.promote(L, P)
    service.update_project(L, P, {"name": "Fall menu", "status": "dropped"})
    boards.update_board(L, link["board_id"], {"name": "Menu board", "status": "archived"})
    assert project_links.links(L) == [
        {
            **link,
            "project_name": "Fall menu",
            "project_status": "dropped",
            "board_name": "Menu board",
            "board_status": "archived",
        }
    ]


# ── The routes ────────────────────────────────────────────────────────────────


def test_the_routes_make_and_list_links_for_the_session_only(new_list):
    mine, theirs = new_list(), new_list()
    c = mine["client"]
    pid = c.post("/api/app/projects", json={"name": NAME}).json()["id"]
    assert c.get("/api/app/project-links").json() == {"links": []}

    made = c.post("/api/app/project-links", json={"project_id": pid})
    assert made.status_code == 200 and made.headers["cache-control"] == "no-store"
    link = made.json()
    assert (link["project_id"], link["board_name"]) == (pid, NAME)
    assert c.post("/api/app/project-links", json={"project_id": pid}).json() == link
    listed = c.get("/api/app/project-links")
    assert listed.json() == {"links": [link]} and listed.headers["cache-control"] == "no-store"

    # Another account sees none of it, and its press on this project finds nothing.
    other = theirs["client"]
    assert other.get("/api/app/project-links").json() == {"links": []}
    refused = other.post("/api/app/project-links", json={"project_id": pid})
    assert refused.status_code == 404 and refused.headers["cache-control"] == "no-store"
    assert other.get(f"/api/app/projects/{link['board_id']}").status_code == 404
    assert _count("boards") == 1


def test_the_routes_follow_the_web_apps_rules(new_list, client):
    mine = new_list()
    c = mine["client"]
    pid = c.post("/api/app/projects", json={"name": NAME}).json()["id"]
    body = {"project_id": pid}
    # Not this site's own page, another list named, or no session: refused, nothing made.
    assert c.post("/api/app/project-links", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.post("/api/app/project-links", json=body, headers={"X-List": "0"}).status_code == 409
    client.cookies.clear()
    assert client.post("/api/app/project-links", json=body).status_code == 401
    assert client.get("/api/app/project-links").status_code == 401
    assert _count("boards") == 0

    boards.create_board(mine["list_id"], NAME)
    taken = c.post("/api/app/project-links", json=body)
    assert taken.status_code == 400 and taken.headers["cache-control"] == "no-store"
    assert taken.json()["detail"].startswith(f'Projects GTD already has a project named "{NAME}"')


# ── The Projects GTD side ─────────────────────────────────────────────────────


def test_the_project_page_names_its_todo_project(new_list):
    mine = new_list()
    c, L = mine["client"], mine["list_id"]
    pid = c.post("/api/app/projects", json={"name": NAME}).json()["id"]
    board_id = c.post("/api/app/project-links", json={"project_id": pid}).json()["board_id"]
    assert c.get(f"/api/app/projects/{board_id}").json()["todo_project"] == {
        "id": pid,
        "name": NAME,
        "status": "active",
    }
    # A project nobody linked has no such field.
    assert "todo_project" not in recordings.project(L, boards.create_board(L, "Garage")["id"])

    # The agent's project_open reads the same page, with the Todo project's status as it is now.
    service.update_project(L, pid, {"status": "dropped"})
    token = mcp_server._list_id.set(L)
    try:
        page = projects_agent.project_open(project=NAME)["project"]
    finally:
        mcp_server._list_id.reset(token)
    assert page["todo_project"] == {"id": pid, "name": NAME, "status": "dropped"}


def test_the_panels_request_lists_only_open_next_actions(new_list):
    mine = new_list()
    c = mine["client"]
    pid = c.post("/api/app/projects", json={"name": NAME}).json()["id"]
    c.post("/api/app/projects", json={"name": "Another"})
    for todo in (
        {"title": "Cost the pumpkin swirl", "status": "next_action", "project_id": pid},
        {"title": "Finished", "status": "done", "project_id": pid},
        {"title": "Given up", "status": "dropped", "project_id": pid},
        {"title": "On the supplier", "status": "waiting_for", "project_id": pid},
        {"title": "Not until spring", "status": "next_action", "project_id": pid, "revisit_on": "2099-03-01"},
        {"title": "Someone else's", "status": "next_action", "project": "Another"},
    ):
        assert c.post("/api/app/todos", json=todo).status_code == 200
    listed = c.get(f"/api/app/todos?project={pid}&status=next_action&limit=500&offset=0").json()["todos"]
    assert [t["title"] for t in listed] == ["Cost the pumpkin swirl"]


# ── Delete, restore, startup ──────────────────────────────────────────────────


def test_admin_delete_removes_a_list_with_links(L, P):
    link = project_links.promote(L, P)
    other = lists.create_list("UTC")["list_id"]
    kept = project_links.promote(other, service.create_project(other, NAME)["id"])
    # Foreign keys are enforced: the links go before the project and the board they name.
    assert admin.main(["delete", str(L), f"--yes-delete-list-{L}", "--no-snapshot"]) == 0
    assert _count("project_links") == 1 and link != kept
    assert project_links.links(other) == [kept]
    assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_version_that_does_not_know_the_table_can_still_delete_a_list(L, P, monkeypatch):
    # After a rollback the older code deletes a list without this table in its own list of them.
    monkeypatch.setattr(admin, "_LIST_TABLES", tuple(t for t in admin._LIST_TABLES if t != "project_links"))
    project_links.promote(L, P)
    assert admin.main(["delete", str(L), f"--yes-delete-list-{L}", "--no-snapshot"]) == 0
    assert lists.get_list(L) is None and _count("project_links") == 0


def test_restore_brings_links_back_and_a_snapshot_without_the_table_has_none(L, P):
    link = project_links.promote(L, P)
    snapshot = backup.snapshot()
    later = service.create_project(L, "Made later")["id"]
    project_links.promote(L, later)
    assert len(project_links.links(L)) == 2

    restore_list.restore(snapshot, L, db.db_path())
    assert project_links.links(L) == [link]
    assert recordings.project(L, link["board_id"])["todo_project"]["id"] == P

    # A snapshot from before the table existed: the list had no links then.
    old = sqlite3.connect(snapshot)
    old.execute("DROP TABLE project_links")
    old.commit()
    old.close()
    restore_list.restore(snapshot, L, db.db_path())
    assert project_links.links(L) == []
    assert [p["name"] for p in service.list_projects(L)] == [NAME]
    assert [b["name"] for b in boards.list_boards(L)] == [NAME]
    assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []
    # Both are still there, so the link can be made again only under another name.
    with pytest.raises(ValidationError, match="already has a project named"):
        project_links.promote(L, P)


def test_startup_adds_the_table_to_an_older_database(L, P):
    db.get_db().execute("DROP TABLE project_links")
    db.init_db()
    db.init_db()
    assert project_links.links(L) == []
    assert project_links.promote(L, P)["project_id"] == P
