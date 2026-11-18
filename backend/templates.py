"""Projects GTD — project templates, as Basecamp's: a project marked as a template
is where new projects start. Making one copies the template's tools, its card
table's columns and labels, its cards (open, in Triage; card templates stay in
their columns as templates), and everything in its tools but the conversation
(comments, answers, the Needle, Hill Chart updates), with completed work
re-opened and every date moved by how far the new start is from the
template's. Like the rest, list-scoped, one transaction, nothing deleted.
"""

import datetime

from backend import boards, common, db, people, recordings
from backend.common import ValidationError


def make_project(
    list_id: int,
    template_ref,
    name: str,
    *,
    starts_on: str | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """A new project named `name` from a template project (by id or name). With
    `starts_on`, its dates and every date in it move to start then."""
    name = boards._name(name)
    starts = common.validate_due(starts_on, "starts_on") if starts_on else None
    with db.transaction() as conn:
        tpl = boards._board(conn, list_id, template_ref)
        if not tpl["template"]:
            raise ValidationError(f'"{tpl["name"]}" is not a template. Mark it as one first.')
        if conn.execute(
            "SELECT 1 FROM boards WHERE list_id = ? AND lower(name) = lower(?)", (list_id, name)
        ).fetchone():
            raise ValidationError(f'Project "{name}" already exists')
        # The caps hold for the whole copy: the template's cards and recordings, counted first.
        boards._check_cap(conn, list_id, "boards")
        boards._check_cap(
            conn,
            list_id,
            "cards",
            adding=conn.execute(
                "SELECT COUNT(*) FROM cards WHERE board_id = ? AND list_id = ? AND status = 'active'",
                (tpl["id"], list_id),
            ).fetchone()[0],
        )
        # Every active recording but the conversation (card subtasks included): at most what is copied.
        recordings._check_cap(
            conn,
            list_id,
            adding=conn.execute(
                "SELECT COUNT(*) FROM recordings WHERE board_id = ? AND list_id = ? AND status = 'active' "
                "AND type NOT IN ('comment', 'answer', 'needle', 'hill_update')",
                (tpl["id"], list_id),
            ).fetchone()[0],
        )
        anchor = datetime.date.fromisoformat(tpl["starts_on"] or tpl["created_at"][:10])
        shift = (datetime.date.fromisoformat(starts) - anchor).days if starts else 0

        def moved(day):
            return (datetime.date.fromisoformat(day) + datetime.timedelta(days=shift)).isoformat() if day else None

        now = common.now_iso()
        board_id = conn.execute(
            "INSERT INTO boards (list_id, name, notes, dock, starts_on, ends_on, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (list_id, name, tpl["notes"], tpl["dock"], starts or tpl["starts_on"], moved(tpl["ends_on"]), now, now),
        ).lastrowid
        assert board_id is not None  # A successful INSERT into a rowid table.
        columns = {}
        for col in conn.execute(
            "SELECT * FROM board_columns WHERE board_id = ? AND status = 'active' ORDER BY position, id", (tpl["id"],)
        ).fetchall():
            columns[col["id"]] = conn.execute(
                "INSERT INTO board_columns (list_id, board_id, name, position, kind, color, has_on_hold, "
                "card_limit, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    list_id,
                    board_id,
                    col["name"],
                    col["position"],
                    col["kind"],
                    col["color"],
                    col["has_on_hold"],
                    col["card_limit"],
                    col["description"],
                    now,
                    now,
                ),
            ).lastrowid
        new_columns = {c["id"]: c for c in boards._columns(conn, board_id)}
        # Every label, in use or not, so the new project starts with the template's set.
        boards._carry_labels(
            conn,
            list_id,
            board_id,
            [
                dict(r)
                for r in conn.execute(
                    "SELECT name, color FROM labels WHERE board_id = ? AND list_id = ? AND status = 'active'",
                    (tpl["id"], list_id),
                )
            ],
        )
        triage = boards._kind_column(conn, board_id, "triage")
        for card in conn.execute(
            "SELECT * FROM cards WHERE board_id = ? AND list_id = ? AND status = 'active' ORDER BY position, id",
            (tpl["id"], list_id),
        ).fetchall():
            card = dict(card)
            home = new_columns.get(columns.get(card["column_id"])) if card["template"] else triage
            new_id = boards._copy_card_in(
                conn, list_id, card, board_id, home or triage, shift=shift, source=source, client=client
            )
            if card["template"]:
                conn.execute("UPDATE cards SET template = 1 WHERE id = ?", (new_id,))
        actor = people.actor_in(conn, list_id, client, source)
        for row in conn.execute(
            "SELECT r.*, b.name AS board_name FROM recordings r JOIN boards b ON b.id = r.board_id "
            "WHERE r.board_id = ? AND r.list_id = ? AND r.parent_id IS NULL AND r.card_id IS NULL "
            "AND r.status = 'active' AND r.type NOT IN ('comment', 'answer', 'needle', 'hill_update') "
            "ORDER BY r.type, r.position, r.id",
            (tpl["id"], list_id),
        ).fetchall():
            recordings._copy_in(
                conn, list_id, dict(row), board_id, None, actor, source, client, reset=True, shift=shift
            )
        boards._trail(conn, list_id, board_id, "started", source, client, detail=f"from {tpl['name']}")
    return boards.get_board(list_id, board_id)


def templates(list_id: int) -> list[dict]:
    """The account's project templates, by name."""
    return [
        {"id": r["id"], "name": r["name"], "notes": r["notes"]}
        for r in db.get_db().execute(
            "SELECT id, name, notes FROM boards WHERE list_id = ? AND status = 'active' AND template = 1 "
            "ORDER BY lower(name)",
            (list_id,),
        )
    ]
