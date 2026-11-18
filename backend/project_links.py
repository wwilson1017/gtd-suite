"""A Todo project's home in Projects GTD: the link between a GTD project in the todo
app (service.py) and the Projects GTD project made for it (boards.py).

A project that outgrows a list of next actions gets a card table, messages and docs.
Its to-dos stay in Todo and nothing is copied: one row of `project_links` ties the two,
each side at most once. The table is its own, so Todo's tables, their fields and the
change counter are as they were.

Made from the web app only (no agent tool on the Todo side), and never unmade: nothing
is deleted. Whoever shows a link reads both statuses and leaves out a link to an archived
Projects GTD project, or from a dropped Todo project.
"""

from backend import boards, common, db
from backend.common import NotFoundError, ValidationError

# What the new project starts with. Not To-dos: the to-dos stay in Todo.
TOOLS = ("kanban_board", "message_board", "vault")

_SELECT = (
    "SELECT l.project_id, p.name AS project_name, p.status AS project_status, "
    "l.board_id, b.name AS board_name, b.status AS board_status, l.created_at "
    "FROM project_links l JOIN projects p ON p.id = l.project_id JOIN boards b ON b.id = l.board_id "
    "WHERE l.list_id = ?"
)


def links(list_id: int) -> list[dict]:
    """Every link of the account, oldest first, with both names and both statuses."""
    return [dict(r) for r in db.get_db().execute(_SELECT + " ORDER BY l.created_at, l.project_id", (list_id,))]


def todo_project(list_id: int, board_id: int) -> dict | None:
    """The Todo project a Projects GTD project is the home of (id, name, status), or None."""
    row = (
        db.get_db()
        .execute(
            "SELECT p.id, p.name, p.status FROM project_links l JOIN projects p ON p.id = l.project_id "
            "WHERE l.list_id = ? AND l.board_id = ?",
            (list_id, board_id),
        )
        .fetchone()
    )
    return dict(row) if row else None


def promote(list_id: int, project_id: int) -> dict:
    """Give a Todo project a home in Projects GTD: a new project there under its name,
    and the link. Asked again, or twice at once, it answers with the link the project
    has: the check, the new project and the link are one transaction."""
    with db.transaction() as conn:
        project = conn.execute(
            "SELECT name FROM projects WHERE id = ? AND list_id = ?", (project_id, list_id)
        ).fetchone()
        if project is None:
            raise NotFoundError(f"Project not found: {project_id}")
        if not conn.execute("SELECT 1 FROM project_links WHERE project_id = ?", (project_id,)).fetchone():
            # simplification: a name Projects GTD already uses is refused; the way up is offering to link that project, or asking for another name
            if conn.execute(
                "SELECT 1 FROM boards WHERE list_id = ? AND lower(name) = lower(?)", (list_id, project["name"])
            ).fetchone():
                raise ValidationError(
                    f'Projects GTD already has a project named "{project["name"]}". '
                    "Rename one of the two, then try again. Nothing was changed."
                )
            board_id = boards.create_board_in(conn, list_id, project["name"], tools=list(TOOLS))
            conn.execute(
                "INSERT INTO project_links (list_id, project_id, board_id, created_at) VALUES (?, ?, ?, ?)",
                (list_id, project_id, board_id, common.now_iso()),
            )
    row = db.get_db().execute(_SELECT + " AND l.project_id = ?", (list_id, project_id)).fetchone()
    return dict(row)
