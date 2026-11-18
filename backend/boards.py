"""Projects GTD — each project's Card Table: its columns and cards, for one list.

A project is a board, and its card table is shaped as Basecamp's: a Triage column
where cards come in, a Not now column beside it, any number of work columns in
order, and a Done column. Triage, Not now and Done are fixed (their `kind`): they
can be renamed but never archived or reordered, and every card table has one of
each. Work columns can carry a colour, an On Hold section and a soft card limit
(Trello's list limit: it warns, never refuses). Cards carry Trello's fields too:
assignees, a start and a due date, the project's labels, a cover colour; a card
in Done is complete. A card's subtasks, comments and boosts are recordings
(recordings.py) tied to it by card_id.

It is apart from the todo app's GTD projects (service.py); the account, its links
and its caps' rules are shared. Like service.py, every function takes the
`list_id` first and scopes every query by it, and every write is one
``db.transaction()``.

Nothing is deleted: a board, column, card or label is archived (status
'archived') and can be brought back. Order is a plain integer ``position``; a move
renumbers the whole target column (or the board's work columns) inside the write
that makes it. Cards land on the top of Done (newest finished first), and the
agent's overview shows only its first DONE_SHOWN. A card's ``version`` goes up on
every change; an edit naming an older one is refused, so a browser's autosave
cannot overwrite what an agent just wrote.

# simplification: whole-column renumbering per move — fine for one person's columns; fractional keys if a column ever holds thousands
"""

import datetime
import json

from backend.paid import caps as paid_caps
from backend.paid import plans
from backend.paid import billing
from backend import apps, common, db, people, recordings, settings
from backend.common import ConflictError, NotFoundError, ValidationError

# A new card table's work columns, then its Done column's name (Basecamp's defaults).
DEFAULT_COLUMNS = ("In progress", "Done")
FIXED = {"triage": "Triage", "not_now": "Not now"}
KIND_ORDER = "CASE kind WHEN 'triage' THEN 0 WHEN 'not_now' THEN 1 WHEN 'column' THEN 2 ELSE 3 END"
# Words that name a fixed column whatever it has been renamed to.
KIND_WORDS = {"triage": "triage", "not now": "not_now", "not_now": "not_now", "done": "done"}
STATUSES = ("active", "archived")
BOARD_FIELDS = frozenset({"name", "notes", "status", "pinned", "starts_on", "ends_on", "template", "folder"})
COLUMN_FIELDS = frozenset({"name", "status", "position", "color", "has_on_hold", "card_limit", "description"})
CARD_FIELDS = frozenset(
    {
        "title",
        "notes",
        "due_date",
        "starts_on",
        "status",
        "assignee_ids",
        "labels",
        "cover",
        "on_hold",
        "completed",
        "repeat",
        "template",
    }
)
LABEL_FIELDS = frozenset({"name", "color", "status"})
MAX_LABELS = 30
SORTS = {
    "due": "c.due_date IS NULL, c.due_date, c.id",
    "created": "c.created_at, c.id",
    "newest": "c.created_at DESC, c.id DESC",
    "title": "lower(c.title), c.id",
}
# A card's notes as the board view shows them to an agent (get_board(snippets=True)).
SNIPPET_CHARS = 200
DONE_SHOWN = 20

_CARD = (
    "SELECT c.id, c.board_id, b.name AS board_name, c.column_id, col.name AS column_name, "
    "col.kind AS column_kind, c.title, c.notes, c.due_date, c.starts_on, c.position, c.status, "
    "c.source, c.source_client, c.version, c.created_at, c.updated_at, c.assignee_ids, "
    "c.label_ids, c.cover, c.on_hold, c.completed_at, c.repeat, c.template "
    "FROM cards c JOIN boards b ON b.id = c.board_id "
    "JOIN board_columns col ON col.id = c.column_id"
)


# ── Checks ────────────────────────────────────────────────────────────────────


def _check_fields(fields: dict, valid: frozenset) -> None:
    unknown = sorted(set(fields) - valid)
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(unknown)}. Valid: {', '.join(sorted(valid))}")


def _status(status) -> str:
    if status not in STATUSES:
        raise ValidationError(f"Invalid status '{status}'. Valid: {', '.join(STATUSES)}")
    return status


def _name(value, field: str = "name") -> str:
    text = common.validate_short(value, field)
    if not text:
        raise ValidationError(f"{field} is required")
    return text


def _color(value) -> str:
    if value not in ("", *recordings.COLORS):
        raise ValidationError(f"color must be one of {', '.join(recordings.COLORS)}, or empty")
    return value


def _check_cap(conn, list_id: int, table: str, adding: int = 1) -> None:
    """Refuse `adding` more boards or cards past the list's cap (common.board_caps_for).
    Archived rows count: nothing is ever deleted. The sample projects (samples.py) do not.
    # simplification: their dozen cards and items do count (of 200 cards, 2,000 items); exclude them too if the samples grow"""
    row = conn.execute(
        f"SELECT email_verified_at, {paid_caps.PLAN_COLUMNS} FROM lists WHERE id = ?", (list_id,)
    ).fetchone()
    verified, hosted = bool(row and row["email_verified_at"]), settings.open_signup()
    plan = plans.of(row) if row else None
    cap = common.board_caps_for(verified, hosted, plan)[("boards", "cards").index(table)]
    n = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE list_id = ?{' AND sample = 0' if table == 'boards' else ''}", (list_id,)
    ).fetchone()[0]
    if n + adding <= cap:
        return
    if hosted and not verified:
        raise ValidationError(
            f"This list holds {cap} {table} until an email is confirmed in {apps.settings_page()}. Nothing was changed."
        )
    raise ValidationError(
        f"A list holds at most {cap} {table}.{billing.upsell(hosted and not plan)} Nothing was changed."
    )


def _trail(
    conn,
    list_id: int,
    board_id: int,
    action: str,
    source: str,
    client: str | None,
    *,
    card_id: int | None = None,
    detail: str = "",
) -> None:
    """A row of the project's activity trail (recordings.event_in), by whoever wrote."""
    actor = people.actor_in(conn, list_id, client, source)
    recordings.event_in(conn, list_id, board_id, action, actor, card_id=card_id, detail=detail)


def _as_id(ref) -> int | None:
    """`ref` as an id when it is one (an int, or a string of ASCII digits), else None."""
    if isinstance(ref, int):
        return ref
    text = str(ref or "").strip()
    return int(text) if text.isascii() and text.isdigit() else None


def _board(conn, list_id: int, ref) -> dict:
    """A board by id, or by name (case-insensitive) when `ref` is not a number."""
    if _as_id(ref) is not None:
        row = conn.execute("SELECT * FROM boards WHERE id = ? AND list_id = ?", (_as_id(ref), list_id)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM boards WHERE lower(name) = lower(?) AND list_id = ?", (str(ref or "").strip(), list_id)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"Project not found: {ref}")
    return dict(row)


def _columns(conn, board_id: int, status: str = "active") -> list[dict]:
    """The board's columns in Basecamp's order: Triage, Not now, the work columns
    by position, Done."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, board_id, name, position, status, kind, color, has_on_hold, card_limit, "
            f"description FROM board_columns WHERE board_id = ? AND status = ? ORDER BY {KIND_ORDER}, "
            "position, id",
            (board_id, status),
        )
    ]


def _kind_column(conn, board_id: int, kind: str) -> dict:
    return next(c for c in _columns(conn, board_id) if c["kind"] == kind)


def _column(conn, list_id: int, board_id: int, ref) -> dict:
    """An active column of the board: by id, by name (case-insensitive), or by
    the kind of a fixed one ("triage", "not now", "done") whatever its name."""
    text = str(ref if ref is not None else "").strip()
    columns = _columns(conn, board_id)
    kind = KIND_WORDS.get(text.lower())
    if kind:  # the fixed columns' words win: a work column may not take them (_work_name)
        return next(c for c in columns if c["kind"] == kind)
    for col in columns:
        if str(col["id"]) == text or col["name"].lower() == text.lower():
            return col
    names = ", ".join(c["name"] for c in columns)
    raise NotFoundError(f"Column not found: {ref}. This project's columns: {names}")


def _work_name(name: str) -> str:
    """A work column's name, which may not be one of the words that name a fixed
    column ("triage", "not now", "done"): those always mean the fixed ones."""
    if name.strip().lower() in KIND_WORDS:
        raise ValidationError(f'"{name}" names one of the fixed columns; pick another name')
    return name


def _name_taken(conn, board_id: int, name: str, except_id: int = 0) -> bool:
    return any(c["name"].lower() == name.lower() and c["id"] != except_id for c in _columns(conn, board_id))


def _place(ids: list[int], item: int, position) -> list[int]:
    """`ids` with `item` put at `position`: 'top', 'bottom' (or None) or a 0-based index."""
    rest = [i for i in ids if i != item]
    if position in (None, "", "bottom"):
        return rest + [item]
    if position == "top":
        return [item] + rest
    try:
        index = int(position)
    except (TypeError, ValueError):
        raise ValidationError("position must be 'top', 'bottom' or a number from 0") from None
    index = max(0, min(index, len(rest)))
    return rest[:index] + [item] + rest[index:]


def _renumber(conn, table: str, ids: list[int]) -> None:
    conn.executemany(f"UPDATE {table} SET position = ? WHERE id = ?", [(n, i) for n, i in enumerate(ids)])


def _default_position(conn, board_id: int, column_id: int, position):
    """Where a card goes when no position is given: the bottom, except in Done,
    where the newest finished card goes on top."""
    if position not in (None, ""):
        return position
    return "top" if _kind_column(conn, board_id, "done")["id"] == column_id else "bottom"


def _card_ids(conn, column_id: int) -> list[int]:
    return [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM cards WHERE column_id = ? AND status = 'active' ORDER BY position, id", (column_id,)
        )
    ]


def _work_ids(columns: list[dict]) -> list[int]:
    return [c["id"] for c in columns if c["kind"] == "column"]


# ── Labels ────────────────────────────────────────────────────────────────────


def list_labels(list_id: int, board_ref, status: str = "active") -> list[dict]:
    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    return _labels(conn, board["id"], status)


def _labels(conn, board_id: int, status: str = "active") -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, board_id, name, color, position, status FROM labels WHERE board_id = ? "
            "AND status = ? ORDER BY position, id",
            (board_id, status),
        )
    ]


def _new_label_in(conn, list_id: int, board_id: int, name: str, color: str = "") -> int:
    existing = _labels(conn, board_id)
    if len(existing) >= MAX_LABELS:
        raise ValidationError(f"A project has at most {MAX_LABELS} labels")
    # A new label takes the next palette colour nobody has yet, as Trello's do.
    used = {lbl["color"] for lbl in existing}
    color = color or next((c for c in recordings.COLORS[1:] if c not in used), "gray")
    now = common.now_iso()
    return conn.execute(
        "INSERT INTO labels (list_id, board_id, name, color, position, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (list_id, board_id, name, color, len(existing), now, now),
    ).lastrowid


def create_label(list_id: int, board_ref, name: str = "", color: str = "") -> dict:
    name = common.validate_short(name, "name")
    color = _color(color)
    if not name and not color:
        raise ValidationError("A label needs a name or a colour")
    with db.transaction() as conn:
        board = _board(conn, list_id, board_ref)
        label_id = _new_label_in(conn, list_id, board["id"], name, color)
        _touch(conn, "boards", board["id"], {})
    return dict(db.get_db().execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone())


def update_label(list_id: int, label_id: int, fields: dict) -> dict:
    """Rename, recolour, archive or restore a label."""
    _check_fields(fields, LABEL_FIELDS)
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM labels WHERE id = ? AND list_id = ?", (label_id, list_id)).fetchone()
        if row is None:
            raise NotFoundError(f"Label not found: {label_id}")
        sets = {}
        if "name" in fields:
            sets["name"] = common.validate_short(fields["name"], "name")
        if "color" in fields:
            sets["color"] = _color(fields["color"])
        if "status" in fields:
            sets["status"] = _status(fields["status"])
        _touch(conn, "labels", label_id, sets)
        _touch(conn, "boards", row["board_id"], {})
    return dict(db.get_db().execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone())


def _label_ids_in(conn, list_id: int, board_id: int, refs) -> list[int]:
    """The board's labels named by id or by name (any case), as ids. A name the
    board does not have yet becomes a new label."""
    if refs in (None, ""):
        return []
    if not isinstance(refs, list):
        raise ValidationError("labels must be a list of label names or ids")
    out: list[int] = []
    labels = _labels(conn, board_id)
    for ref in refs:
        found = next(
            (
                lbl
                for lbl in labels
                if (_as_id(ref) is not None and lbl["id"] == _as_id(ref))
                or (lbl["name"] and lbl["name"].lower() == str(ref).strip().lower())
            ),
            None,
        )
        if found is None and _as_id(ref) is not None:
            raise ValidationError(f"Label not found: {ref}")
        label_id = found["id"] if found else _new_label_in(conn, list_id, board_id, _name(ref, "label name"))
        if found is None:
            labels = _labels(conn, board_id)
        if label_id not in out:
            out.append(label_id)
    return out


def _carry_labels(conn, list_id: int, board_id: int, labels: list[dict]) -> list[int]:
    """A moved card's labels on its new project: a named one by name, a
    colour-only one by colour; either is made there when the project lacks it."""
    out: list[int] = []
    for lbl in labels:
        if lbl["name"]:  # by name only: a name that looks like a number is still a name
            found = next((x for x in _labels(conn, board_id) if x["name"].lower() == lbl["name"].lower()), None)
            label_id = found["id"] if found else _new_label_in(conn, list_id, board_id, lbl["name"], lbl["color"])
        else:
            found = next((x for x in _labels(conn, board_id) if not x["name"] and x["color"] == lbl["color"]), None)
            label_id = found["id"] if found else _new_label_in(conn, list_id, board_id, "", lbl["color"])
        if label_id not in out:
            out.append(label_id)
    return out


# ── Cards as the app and the agent see them ──────────────────────────────────


def _shape_cards(conn, list_id: int, rows) -> list[dict]:
    """Cards with their people and labels in place of ids, and the badges a card's
    face shows: subtasks done of total, comments."""
    cards = [dict(r) for r in rows]
    if not cards:
        return []
    ids = [c["id"] for c in cards]
    marks = ",".join("?" * len(ids))
    who = {
        r["id"]: {"id": r["id"], "name": r["name"], "kind": r["kind"], "color": r["color"]}
        for r in conn.execute("SELECT id, name, kind, color FROM people WHERE list_id = ?", (list_id,))
    }
    labels = {
        r["id"]: {"id": r["id"], "name": r["name"], "color": r["color"]}
        for r in conn.execute("SELECT id, name, color FROM labels WHERE list_id = ? AND status = 'active'", (list_id,))
    }
    counts: dict[int, dict] = {i: {"steps_count": 0, "steps_done": 0, "comments_count": 0} for i in ids}
    for r in conn.execute(
        f"SELECT card_id, type, completed_at IS NOT NULL AS done, COUNT(*) AS n FROM recordings "
        f"WHERE list_id = ? AND card_id IN ({marks}) AND status = 'active' "
        "GROUP BY card_id, type, done",
        (list_id, *ids),
    ):
        if r["type"] == "step":
            counts[r["card_id"]]["steps_count"] += r["n"]
            counts[r["card_id"]]["steps_done"] += r["n"] if r["done"] else 0
        elif r["type"] == "comment":
            counts[r["card_id"]]["comments_count"] += r["n"]
    for c in cards:
        c["assignees"] = [who[i] for i in json.loads(c.pop("assignee_ids") or "[]") if i in who]
        c["labels"] = [labels[i] for i in json.loads(c.pop("label_ids") or "[]") if i in labels]
        c["on_hold"] = bool(c["on_hold"])
        c["template"] = bool(c.get("template"))
        c["completed"] = c["completed_at"] is not None
        c.update(counts[c["id"]])
    return cards


# ── Boards ────────────────────────────────────────────────────────────────────


def list_boards(list_id: int, status: str = "active") -> list[dict]:
    """The list's boards, newest change first, each with its columns and how many
    active cards each holds."""
    _status(status)
    conn = db.get_db()
    boards = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM boards WHERE list_id = ? AND status = ? ORDER BY updated_at DESC, id DESC", (list_id, status)
        )
    ]
    counts = {
        (r["column_id"]): r["n"]
        for r in conn.execute(
            "SELECT column_id, COUNT(*) AS n FROM cards WHERE list_id = ? AND status = 'active' GROUP BY column_id",
            (list_id,),
        )
    }
    for board in boards:
        board["columns"] = [
            {"id": c["id"], "name": c["name"], "kind": c["kind"], "color": c["color"], "cards": counts.get(c["id"], 0)}
            for c in _columns(conn, board["id"])
        ]
        board["cards"] = sum(c["cards"] for c in board["columns"])
        board["sample"] = bool(board["sample"])
    return boards


def get_board(list_id: int, ref, *, snippets: bool = False) -> dict:
    """A board's card table: its active columns in order (Triage, Not now, the work
    columns, Done), each holding its active cards in order, and the project's
    labels. `snippets` (the agent's overview) cuts each card's notes to
    SNIPPET_CHARS and Done to its first DONE_SHOWN cards."""
    conn = db.get_db()
    board = _board(conn, list_id, ref)
    board["sample"] = bool(board["sample"])
    columns = _columns(conn, board["id"])
    by_column: dict[int, list] = {c["id"]: [] for c in columns}
    rows = conn.execute(
        f"{_CARD} WHERE c.board_id = ? AND c.status = 'active' ORDER BY c.position, c.id", (board["id"],)
    ).fetchall()
    for card in _shape_cards(conn, list_id, rows):
        if snippets and len(card["notes"]) > SNIPPET_CHARS:
            card["notes"] = card["notes"][:SNIPPET_CHARS] + "…"
            card["notes_cut"] = True
        if card["column_id"] in by_column:
            by_column[card["column_id"]].append(card)
    board["columns"] = [
        {**c, "has_on_hold": bool(c["has_on_hold"]), "done": c["kind"] == "done", "cards": by_column[c["id"]]}
        for c in columns
    ]
    done = next((c for c in board["columns"] if c["done"]), None)
    if snippets and done and len(done["cards"]) > DONE_SHOWN:
        done["more_cards"] = len(done["cards"]) - DONE_SHOWN
        done["cards"] = done["cards"][:DONE_SHOWN]
    board["labels"] = _labels(conn, board["id"])
    board["wormholes"] = _wormholes(conn, list_id, board["id"])
    board["archived_cards"] = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE board_id = ? AND status = 'archived'", (board["id"],)
    ).fetchone()[0]
    return board


def _wormholes(conn, list_id: int, board_id: int) -> list[dict]:
    """The table's open wormholes (recordings of type 'wormhole'): each names the
    column of another project a card dropped on it goes to. One whose column or
    project was archived is hidden until that comes back."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT r.id, c.id AS column_id, c.name AS column_name, b.id AS project_id, b.name AS project_name "
            "FROM recordings r JOIN board_columns c ON c.id = json_extract(r.data, '$.column_id') AND c.list_id = r.list_id "
            "JOIN boards b ON b.id = c.board_id AND b.list_id = r.list_id "
            "WHERE r.list_id = ? AND r.board_id = ? AND r.type = 'wormhole' AND r.status = 'active' "
            "AND c.status = 'active' AND b.status = 'active' ORDER BY r.position, r.id",
            (list_id, board_id),
        )
    ]


def _add_fixed_in(conn, list_id: int, board_id: int, now: str) -> None:
    conn.executemany(
        "INSERT INTO board_columns (list_id, board_id, name, position, kind, created_at, updated_at) "
        "VALUES (?, ?, ?, -1, ?, ?, ?)",
        [(list_id, board_id, name, kind, now, now) for kind, name in FIXED.items()],
    )


def create_board(
    list_id: int,
    name: str,
    notes: str = "",
    columns: list[str] | None = None,
    *,
    tools: list[str] | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """A new project, its card table set up as Basecamp's: Triage and Not now, the
    work columns, and Done (the last of `columns` names it). `tools` are the ones
    it starts with (recordings.TOOLS keys); None keeps the card table alone, []
    starts it empty as Basecamp 5 does."""
    name = _name(name)
    notes = common.validate_notes(notes)
    columns = [_name(c, "column name") for c in (columns or DEFAULT_COLUMNS)]
    if len(columns) + len(FIXED) > common.MAX_COLUMNS:
        raise ValidationError(
            f"A project has at most {common.MAX_COLUMNS - len(FIXED)} columns besides Triage and Not now"
        )
    if len({c.lower() for c in [*columns, *FIXED.values()]}) != len(columns) + len(FIXED):
        raise ValidationError("Column names must differ (Triage and Not now are there already)")
    for work in columns[:-1]:
        _work_name(work)
    with db.transaction() as conn:
        if conn.execute(
            "SELECT 1 FROM boards WHERE list_id = ? AND lower(name) = lower(?)", (list_id, name)
        ).fetchone():
            raise ValidationError(f'Project "{name}" already exists')
        _check_cap(conn, list_id, "boards")
        now = common.now_iso()
        dock = (
            None
            if tools is None
            else json.dumps([{"tool": t, "enabled": True} for t in tools if t in recordings.TOOLS])
        )
        board_id = conn.execute(
            "INSERT INTO boards (list_id, name, notes, dock, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (list_id, name, notes, dock, now, now),
        ).lastrowid
        assert board_id is not None  # A successful INSERT into a rowid table.
        _add_fixed_in(conn, list_id, board_id, now)
        conn.executemany(
            "INSERT INTO board_columns (list_id, board_id, name, position, kind, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (list_id, board_id, c, n, "done" if n == len(columns) - 1 else "column", now, now)
                for n, c in enumerate(columns)
            ],
        )
        _trail(conn, list_id, board_id, "started", source, client)
    return get_board(list_id, board_id)


def update_board(list_id: int, ref, fields: dict) -> dict:
    """Rename, re-note, archive or restore a board; pin it to the top of Home,
    or give it dates (the Lineup)."""
    _check_fields(fields, BOARD_FIELDS)
    with db.transaction() as conn:
        board = _board(conn, list_id, ref)
        sets = {}
        if "name" in fields:
            sets["name"] = _name(fields["name"])
            if conn.execute(
                "SELECT 1 FROM boards WHERE list_id = ? AND lower(name) = lower(?) AND id != ?",
                (list_id, sets["name"], board["id"]),
            ).fetchone():
                raise ValidationError(f'Project "{sets["name"]}" already exists')
        if "notes" in fields:
            sets["notes"] = common.validate_notes(fields["notes"])
        if "status" in fields:
            sets["status"] = _status(fields["status"])
        if "pinned" in fields:
            sets["pinned"] = 1 if fields["pinned"] else 0
        if "template" in fields:
            sets["template"] = 1 if fields["template"] else 0
        if "folder" in fields:  # Basecamp 5's Home folders: a name, or "" for none
            sets["folder"] = common.validate_short(fields["folder"], "folder")
        for date in ("starts_on", "ends_on"):
            if date in fields:
                sets[date] = common.validate_due(fields[date], date)
        starts = sets.get("starts_on", board.get("starts_on"))
        ends = sets.get("ends_on", board.get("ends_on"))
        if starts and ends and starts > ends:
            raise ValidationError("The project can't end before it starts")
        _touch(conn, "boards", board["id"], sets)
    return get_board(list_id, board["id"])


def _touch(conn, table: str, row_id: int, sets: dict) -> None:
    """Write `sets` and stamp updated_at; a card's version goes up too."""
    sets = {**sets, "updated_at": common.now_iso()}
    bump = ", version = version + 1" if table == "cards" else ""
    conn.execute(
        f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in sets)}{bump} WHERE id = ?", (*sets.values(), row_id)
    )


# ── Columns ───────────────────────────────────────────────────────────────────


def add_column(list_id: int, board_ref, name: str, position=None) -> dict:
    """A work column, at the end of the work columns (before Done) or at
    `position` among them."""
    name = _work_name(_name(name, "column name"))
    with db.transaction() as conn:
        board = _board(conn, list_id, board_ref)
        columns = _columns(conn, board["id"])
        if len(columns) >= common.MAX_COLUMNS:
            raise ValidationError(f"A project has at most {common.MAX_COLUMNS} columns")
        if _name_taken(conn, board["id"], name):
            raise ValidationError(f'This project already has a column "{name}"')
        now = common.now_iso()
        work = _work_ids(columns)
        col_id = conn.execute(
            "INSERT INTO board_columns (list_id, board_id, name, position, kind, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'column', ?, ?)",
            (list_id, board["id"], name, len(work), now, now),
        ).lastrowid
        assert col_id is not None  # A successful INSERT into a rowid table.
        _renumber(conn, "board_columns", _place(work, col_id, position))
        _touch(conn, "boards", board["id"], {})
    return get_board(list_id, board["id"])


def update_column(list_id: int, column_id: int, fields: dict) -> dict:
    """Rename a column; move (position among the work columns), colour, give an
    On Hold section to, set a soft card limit on, or archive a work column. Only
    an empty column can be archived, so no card is ever hidden by it; a restored
    one goes last. Triage, Not now and Done can only be renamed."""
    _check_fields(fields, COLUMN_FIELDS)
    with db.transaction() as conn:
        col = conn.execute("SELECT * FROM board_columns WHERE id = ? AND list_id = ?", (column_id, list_id)).fetchone()
        if col is None:
            raise NotFoundError(f"Column not found: {column_id}")
        sets, board_id = {}, col["board_id"]
        if col["kind"] != "column" and set(fields) - {"name", "description"}:
            raise ValidationError(f'"{col["name"]}" is fixed: it can be renamed, nothing else')
        if "name" in fields:
            sets["name"] = _name(fields["name"], "column name")
            if col["kind"] == "column":
                _work_name(sets["name"])
            if _name_taken(conn, board_id, sets["name"], except_id=column_id):
                raise ValidationError(f'This project already has a column "{sets["name"]}"')
        if "color" in fields:
            sets["color"] = _color(fields["color"])
        if "description" in fields:
            sets["description"] = common.validate_notes(fields["description"], "description")
        if "has_on_hold" in fields:
            sets["has_on_hold"] = 1 if fields["has_on_hold"] else 0
            if not fields["has_on_hold"]:
                # Its on-hold cards come back into the column, at the bottom.
                for row in conn.execute(
                    "SELECT id FROM cards WHERE column_id = ? AND on_hold = 1", (column_id,)
                ).fetchall():
                    _touch(conn, "cards", row["id"], {"on_hold": 0})  # a new version: open sheets reload
        if "card_limit" in fields:
            limit = fields["card_limit"]
            if limit not in (None, "", 0) and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
                raise ValidationError("card_limit must be a whole number from 1, or empty for none")
            sets["card_limit"] = limit or None
        status = _status(fields.get("status", col["status"]))
        active = _work_ids(_columns(conn, board_id))
        if status == "archived" and col["status"] == "active":
            if _card_ids(conn, column_id):
                raise ValidationError("Move or archive this column's cards first")
            active.remove(column_id)
        elif status == "active" and col["status"] == "archived":
            if len(_columns(conn, board_id)) >= common.MAX_COLUMNS:
                raise ValidationError(f"A project has at most {common.MAX_COLUMNS} columns")
            if _name_taken(conn, board_id, sets.get("name", col["name"]), except_id=column_id):
                raise ValidationError(f'This project already has a column "{col["name"]}"')
            active.append(column_id)
        sets["status"] = status
        _touch(conn, "board_columns", column_id, sets)
        if col["kind"] == "column":
            if "position" in fields or (status == "active" and col["status"] == "archived"):
                active = _place(active, column_id, fields.get("position"))
            _renumber(conn, "board_columns", active)
        _touch(conn, "boards", board_id, {})
    return get_board(list_id, board_id)


def move_all_cards(list_id: int, column_id: int, to_column, *, source: str = "ui", client: str | None = None) -> dict:
    """Trello's "Move all cards in this list": every active card of a column to
    the bottom of another column of the same project, in order."""
    with db.transaction() as conn:
        col = conn.execute("SELECT * FROM board_columns WHERE id = ? AND list_id = ?", (column_id, list_id)).fetchone()
        if col is None:
            raise NotFoundError(f"Column not found: {column_id}")
        target = _column(conn, list_id, col["board_id"], to_column)
        if target["id"] == column_id:
            raise ValidationError("Pick another column")
        moving = _card_ids(conn, column_id)
        done = target["kind"] == "done"
        spawned = []
        for card_id in moving:
            before = dict(
                conn.execute("SELECT * FROM cards WHERE id = ? AND list_id = ?", (card_id, list_id)).fetchone()
            )
            _touch(
                conn,
                "cards",
                card_id,
                {"column_id": target["id"], "on_hold": 0, "completed_at": common.now_iso() if done else None},
            )
            if done and not before["completed_at"]:
                spawned.append(
                    _repeat_in(conn, list_id, {**before, "column_id": target["id"]}, dict(col), source, client)
                )
        ids = (
            moving + [i for i in _card_ids(conn, target["id"]) if i not in moving]
            if done
            else [i for i in _card_ids(conn, target["id"]) if i not in moving] + moving
        )
        _renumber(conn, "cards", ids)
        if moving:
            _trail(
                conn,
                list_id,
                col["board_id"],
                "moved",
                source,
                client,
                detail=f"{len(moving)} cards from {col['name']} to {target['name']}",
            )
        _touch(conn, "boards", col["board_id"], {})
    for card_id in moving:
        _fire(list_id, col["board_id"], "card_moved", card_id, target["id"])
        if done and col["kind"] != "done":
            _fire(list_id, col["board_id"], "card_completed", card_id, target["id"])
    for new_id in filter(None, spawned):
        _fire(list_id, col["board_id"], "card_added", new_id, None)
    return get_board(list_id, col["board_id"])


def archive_all_cards(list_id: int, column_id: int, *, source: str = "ui", client: str | None = None) -> dict:
    """Trello's "Archive all cards in this list". Nothing is deleted."""
    with db.transaction() as conn:
        col = conn.execute("SELECT * FROM board_columns WHERE id = ? AND list_id = ?", (column_id, list_id)).fetchone()
        if col is None:
            raise NotFoundError(f"Column not found: {column_id}")
        ids = _card_ids(conn, column_id)
        for card_id in ids:
            _touch(conn, "cards", card_id, {"status": "archived"})
        if ids:
            _trail(
                conn, list_id, col["board_id"], "archived", source, client, detail=f"{len(ids)} cards in {col['name']}"
            )
        _touch(conn, "boards", col["board_id"], {})
    return get_board(list_id, col["board_id"])


def sort_column(list_id: int, column_id: int, by: str) -> dict:
    """Trello's "Sort by": put a column's cards in order by due date, creation
    (oldest or newest first) or title, once; later moves are by hand."""
    if by not in SORTS:
        raise ValidationError(f"Sort by one of {', '.join(SORTS)}")
    with db.transaction() as conn:
        col = conn.execute("SELECT * FROM board_columns WHERE id = ? AND list_id = ?", (column_id, list_id)).fetchone()
        if col is None:
            raise NotFoundError(f"Column not found: {column_id}")
        _renumber(
            conn,
            "cards",
            [
                r["id"]
                for r in conn.execute(
                    f"SELECT c.id FROM cards c WHERE c.column_id = ? AND c.status = 'active' ORDER BY {SORTS[by]}",
                    (column_id,),
                )
            ],
        )
        _touch(conn, "boards", col["board_id"], {})
    return get_board(list_id, col["board_id"])


# ── Cards ─────────────────────────────────────────────────────────────────────


def get_card(list_id: int, card_id: int, *, thread: bool = False) -> dict:
    """One card. With `thread`, its subtasks and comments too (the agent's card_get)."""
    conn = db.get_db()
    row = conn.execute(f"{_CARD} WHERE c.id = ? AND c.list_id = ?", (card_id, list_id)).fetchone()
    if row is None:
        raise NotFoundError(f"Card not found: {card_id}")
    card = _shape_cards(conn, list_id, [row])[0]
    if thread:
        card["subtasks"] = [
            {k: s[k] for k in ("id", "title", "completed", "due_on", "assignees")}
            for s in recordings.card_steps(list_id, card_id)
        ]
        card["comments"] = [
            {k: c[k] for k in ("id", "body", "creator", "created_at")}
            for c in recordings.comments(list_id, card_id=card_id)
        ]
    return card


def archived_cards(list_id: int, board_ref, limit: int = 200, offset: int = 0) -> list[dict]:
    """A board's archived cards, the most recently changed first, a page at a time."""
    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    return _shape_cards(
        conn,
        list_id,
        conn.execute(
            f"{_CARD} WHERE c.board_id = ? AND c.status = 'archived' "
            "ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?",
            (board["id"], limit, offset),
        ),
    )


def _card_fields(conn, list_id: int, board_id: int, fields: dict) -> dict:
    """The writable card fields that are not about place or status, as columns."""
    sets = {}
    if "title" in fields:
        sets["title"] = _name(fields["title"], "title")
    if "notes" in fields:
        sets["notes"] = common.validate_notes(fields["notes"])
    if "due_date" in fields:
        sets["due_date"] = common.validate_due(fields["due_date"])
    if "starts_on" in fields:
        sets["starts_on"] = common.validate_due(fields["starts_on"], "starts_on")
    if "assignee_ids" in fields:
        ids = people.resolve_in(conn, list_id, fields["assignee_ids"])
        if len(ids) > recordings.MAX_ASSIGNEES:
            raise ValidationError(f"At most {recordings.MAX_ASSIGNEES} people")
        sets["assignee_ids"] = json.dumps(ids)
    if "labels" in fields:
        sets["label_ids"] = json.dumps(_label_ids_in(conn, list_id, board_id, fields["labels"]))
    if "cover" in fields:
        sets["cover"] = _color(fields["cover"])
    if "repeat" in fields:
        if fields["repeat"] not in (None, *recordings.REPEATS):
            raise ValidationError(f"repeat must be one of {', '.join(r for r in recordings.REPEATS if r)}, or empty")
        sets["repeat"] = fields["repeat"] or None
    if "template" in fields:
        sets["template"] = 1 if fields["template"] else 0
    return sets


def create_card(
    list_id: int,
    board_ref,
    title: str,
    *,
    column=None,
    notes: str = "",
    due_date=None,
    position=None,
    source: str = "ui",
    source_client: str | None = None,
    **extra,
) -> dict:
    """A card at the bottom of `column` (Triage when not given), or at `position`.
    `extra`: starts_on, assignee_ids, labels, cover, repeat, template."""
    _check_fields(extra, frozenset({"starts_on", "assignee_ids", "labels", "cover", "repeat", "template"}))
    title = _name(title, "title")
    notes = common.validate_notes(notes)
    due_date = common.validate_due(due_date)
    with db.transaction() as conn:
        board = _board(conn, list_id, board_ref)
        if board["status"] != "active":
            raise ValidationError("This project is archived. Restore it first.")
        col = (
            _column(conn, list_id, board["id"], column)
            if column not in (None, "")
            else _kind_column(conn, board["id"], "triage")
        )
        sets = _card_fields(conn, list_id, board["id"], extra)
        _check_range(sets.get("starts_on"), due_date)
        _check_cap(conn, list_id, "cards")
        now = common.now_iso()
        ids = _card_ids(conn, col["id"])
        row = {
            "list_id": list_id,
            "board_id": board["id"],
            "column_id": col["id"],
            "title": title,
            "notes": notes,
            "due_date": due_date,
            "position": len(ids),
            "source": source,
            "source_client": common.clean_source_client(source_client),
            "created_at": now,
            "updated_at": now,
            "completed_at": now if col["kind"] == "done" else None,
            **sets,
        }
        card_id = conn.execute(
            f"INSERT INTO cards ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
        ).lastrowid
        assert card_id is not None  # A successful INSERT into a rowid table.
        _renumber(conn, "cards", _place(ids, card_id, _default_position(conn, board["id"], col["id"], position)))
        _touch(conn, "boards", board["id"], {})
        _trail(conn, list_id, board["id"], "created", source, source_client, card_id=card_id, detail=col["name"])
    _fire(list_id, board["id"], "card_added", card_id, col["id"])
    return get_card(list_id, card_id)


def _fire(list_id: int, board_id: int, event: str, card_id: int, column_id: int | None = None) -> None:
    """After a card write commits: the project's automation rules for it (automation.fire).
    Without a column, the card's own."""
    from backend import automation  # here: automation imports this module

    if column_id is None:
        row = (
            db.get_db()
            .execute("SELECT column_id FROM cards WHERE id = ? AND list_id = ?", (card_id, list_id))
            .fetchone()
        )
        column_id = row["column_id"] if row else None
    automation.fire(list_id, board_id, event, card_id, column_id)


def _check_range(starts, due) -> None:
    if starts and due and starts > due:
        raise ValidationError("starts_on must not be after due_date")


def update_card(
    list_id: int,
    card_id: int,
    fields: dict,
    version: int | None = None,
    *,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """Edit a card's fields; put it on or off hold in its column; complete it
    (to the top of Done) or re-open it (out of Done, to its first work column, or
    Triage); archive it, or bring it back (to its column, or Triage if that one is
    archived). With `version`, refused (ConflictError) when the card changed since."""
    _check_fields(fields, CARD_FIELDS)
    spawned = None
    with db.transaction() as conn:
        card = conn.execute("SELECT * FROM cards WHERE id = ? AND list_id = ?", (card_id, list_id)).fetchone()
        if card is None:
            raise NotFoundError(f"Card not found: {card_id}")
        card = dict(card)
        if version is not None and version != card["version"]:
            raise ConflictError(
                "This card changed since it was opened. Nothing was saved; reload it to see the change."
            )
        board_id = card["board_id"]
        sets = _card_fields(conn, list_id, board_id, fields)
        _check_range(sets.get("starts_on", card["starts_on"]), sets.get("due_date", card["due_date"]))
        if "status" in fields:
            sets["status"] = _status(fields["status"])
        columns = _columns(conn, board_id)
        here = next((c for c in columns if c["id"] == card["column_id"]), None)
        target = None
        restore = sets.get("status") == "active" and card["status"] == "archived"
        if restore:
            target = here or _kind_column(conn, board_id, "triage")
        if "completed" in fields and card["status"] == "active" and not restore:
            in_done = here is not None and here["kind"] == "done"
            if fields["completed"] and not in_done:
                target = _kind_column(conn, board_id, "done")
            elif not fields["completed"] and in_done:
                target = next((c for c in columns if c["kind"] == "column"), _kind_column(conn, board_id, "triage"))
        if "on_hold" in fields:
            column = target or here
            if fields["on_hold"] and not (column and column["has_on_hold"]):
                raise ValidationError("This column has no On Hold section; add one from its menu first")
            sets["on_hold"] = 1 if fields["on_hold"] else 0
        if target is not None:
            sets["column_id"] = target["id"]
            # A card brought back into Done keeps when it was finished.
            sets["completed_at"] = (card["completed_at"] or common.now_iso()) if target["kind"] == "done" else None
            if target["id"] != card["column_id"]:
                sets.setdefault("on_hold", 0)
        _touch(conn, "cards", card_id, sets)
        if target is not None:
            _renumber(
                conn,
                "cards",
                _place(_card_ids(conn, target["id"]), card_id, _default_position(conn, board_id, target["id"], None)),
            )
            if target["kind"] == "done" and card["status"] == "active" and not card["completed_at"]:
                spawned = _repeat_in(conn, list_id, {**card, **sets}, here, source, client)
        _touch(conn, "boards", board_id, {})
        status = sets.get("status", card["status"])
        if status != card["status"]:
            action = "archived" if status == "archived" else "restored"
        elif target is not None and target["id"] != card["column_id"]:
            action = "completed" if target["kind"] == "done" else "reopened"
        else:
            action = "assigned" if set(fields) == {"assignee_ids"} else "edited"
        _trail(
            conn,
            list_id,
            board_id,
            action,
            source,
            client,
            card_id=card_id,
            detail=target["name"] if action == "reopened" and target else "",
        )
    if action in ("completed", "reopened"):
        assert target is not None  # These actions are set only when a target column exists.
        # Completing or re-opening relocates the card: rules see the move as well.
        _fire(list_id, board_id, "card_moved", card_id, target["id"])
    if action == "completed":
        assert target is not None  # Completing relocates the card to Done.
        _fire(list_id, board_id, "card_completed", card_id, target["id"])
    if spawned:
        _fire(list_id, board_id, "card_added", spawned, None)
    return get_card(list_id, card_id)


def append_note(list_id: int, card_id: int, text: str, by: str | None = None) -> dict:
    """Add `text` to the end of a card's notes, after a blank line: a log an agent
    can keep without rewriting what is there. With `by` (the AI tool's name), the
    entry starts with the list's date and that name."""
    text = str(text or "").strip()
    if not text:
        raise ValidationError("Nothing to append")
    with db.transaction() as conn:
        card = get_card(list_id, card_id)
        if by is not None:
            tz = conn.execute("SELECT tz FROM lists WHERE id = ?", (list_id,)).fetchone()["tz"]
            text = f"{common.business_today(tz).isoformat()} · {by}: {text}"
        old = card["notes"].rstrip()
        notes = common.validate_notes(f"{old}\n\n{text}" if old else text)
        _touch(conn, "cards", card_id, {"notes": notes})
        _touch(conn, "boards", card["board_id"], {})
        _trail(
            conn,
            list_id,
            card["board_id"],
            "edited",
            "ui" if by is None else "agent",
            None if by == "agent" else by,
            card_id=card_id,
            detail=recordings._excerpt(text),
        )
    return get_card(list_id, card_id)


def move_card(
    list_id: int,
    card_id: int,
    column,
    position=None,
    board=None,
    *,
    on_hold: bool | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """Move an active card to `column` (id, name, or "triage" / "not now" / "done")
    at `position` ('top', 'bottom' or a 0-based index; by default the bottom, or the
    top of Done), on or off hold there. A column name is looked up on the card's
    own board, or on `board` to move it to another project (its labels go with it,
    by name). Into Done completes the card; out of Done re-opens it."""
    spawned = None
    with db.transaction() as conn:
        card = get_card(list_id, card_id)
        if card["status"] != "active":
            raise ValidationError("This card is archived. Restore it before moving it.")
        if board not in (None, ""):
            target = _board(conn, list_id, board)
        elif _as_id(column) is not None:
            row = conn.execute(
                "SELECT board_id FROM board_columns WHERE id = ? AND list_id = ?", (_as_id(column), list_id)
            ).fetchone()
            target = _board(conn, list_id, row["board_id"] if row else card["board_id"])
        else:
            target = _board(conn, list_id, card["board_id"])
        if target["status"] != "active":
            raise ValidationError("That project is archived. Restore it first.")
        col = _column(conn, list_id, target["id"], column)
        hold = bool(on_hold) if on_hold is not None else (card["on_hold"] and col["id"] == card["column_id"])
        if hold and not col["has_on_hold"]:
            raise ValidationError(f'"{col["name"]}" has no On Hold section; add one from its menu first')
        sets = {"column_id": col["id"], "board_id": target["id"], "on_hold": 1 if hold else 0}
        if (col["kind"] == "done") != card["completed"]:
            sets["completed_at"] = common.now_iso() if col["kind"] == "done" else None
        if target["id"] != card["board_id"]:
            sets["label_ids"] = json.dumps(_carry_labels(conn, list_id, target["id"], card["labels"]))
            conn.execute(
                "UPDATE recordings SET board_id = ? WHERE card_id = ? AND list_id = ?", (target["id"], card_id, list_id)
            )
        _touch(conn, "cards", card_id, sets)
        _renumber(
            conn,
            "cards",
            _place(_card_ids(conn, col["id"]), card_id, _default_position(conn, target["id"], col["id"], position)),
        )
        if col["kind"] == "done" and not card["completed"]:
            row = dict(conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone())
            was = conn.execute("SELECT * FROM board_columns WHERE id = ?", (card["column_id"],)).fetchone()
            spawned = _repeat_in(
                conn, list_id, row, dict(was) if was and target["id"] == card["board_id"] else None, source, client
            )
        for board_id in {card["board_id"], target["id"]}:
            _touch(conn, "boards", board_id, {})
        if col["id"] != card["column_id"]:
            where = col["name"] if target["id"] == card["board_id"] else f"{col['name']} in {target['name']}"
            action = "completed" if col["kind"] == "done" else "reopened" if card["completed"] else "moved"
            _trail(conn, list_id, target["id"], action, source, client, card_id=card_id, detail=where)
        elif hold != card["on_hold"]:
            _trail(
                conn,
                list_id,
                target["id"],
                "moved",
                source,
                client,
                card_id=card_id,
                detail=f"On Hold in {col['name']}" if hold else col["name"],
            )
    if col["id"] != card["column_id"]:
        _fire(list_id, target["id"], "card_moved", card_id, col["id"])
        if col["kind"] == "done" and not card["completed"]:
            _fire(list_id, target["id"], "card_completed", card_id, col["id"])
    if spawned:
        _fire(list_id, target["id"], "card_added", spawned, None)
    return get_card(list_id, card_id)


def assigned_cards(list_id: int, person_id: int | None = None) -> list[dict]:
    """Open cards (not in Done) assigned to a person (me by default), soonest due first."""
    conn = db.get_db()
    if person_id is None:
        row = conn.execute("SELECT id FROM people WHERE list_id = ? AND kind = 'me'", (list_id,)).fetchone()
        if row is None:
            return []
        person_id = row["id"]
    return _shape_cards(
        conn,
        list_id,
        conn.execute(
            f"{_CARD} WHERE c.list_id = ? AND c.status = 'active' AND c.completed_at IS NULL "
            "AND b.status = 'active' AND b.template = 0 "
            "AND EXISTS (SELECT 1 FROM json_each(c.assignee_ids) WHERE value = ?) "
            "ORDER BY c.due_date IS NULL, c.due_date, c.id",
            (list_id, person_id),
        ),
    )


# ── Copies, templates and repeats ─────────────────────────────────────────────


def _copy_card_in(
    conn,
    list_id: int,
    card: dict,
    board_id: int,
    column: dict,
    *,
    title: str | None = None,
    due_date=None,
    shift: int = 0,
    source: str = "ui",
    client: str | None = None,
    keep_repeat: bool = True,
) -> int:
    """A new open card like `card` (a cards row) at the bottom of `column`: its notes,
    people, labels (by name in another project), dates (moved `shift` days), cover,
    repeat and open subtasks; never its comments. Returns the new id."""

    def moved(day):
        return (datetime.date.fromisoformat(day) + datetime.timedelta(days=shift)).isoformat() if day and shift else day

    label_ids = card["label_ids"]
    if board_id != card["board_id"]:
        names = (
            [
                dict(r)
                for r in conn.execute(
                    f"SELECT name, color FROM labels WHERE list_id = ? AND id IN ({','.join('?' * len(json.loads(label_ids)))})",
                    (list_id, *json.loads(label_ids)),
                )
            ]
            if json.loads(label_ids)
            else []
        )
        label_ids = json.dumps(_carry_labels(conn, list_id, board_id, names))
    now = common.now_iso()
    ids = _card_ids(conn, column["id"])
    row = {
        "list_id": list_id,
        "board_id": board_id,
        "column_id": column["id"],
        "title": title or card["title"],
        "notes": card["notes"],
        "due_date": due_date if due_date is not None else moved(card["due_date"]),
        "starts_on": moved(card["starts_on"]),
        "position": len(ids),
        "source": source,
        "source_client": common.clean_source_client(client),
        "created_at": now,
        "updated_at": now,
        "assignee_ids": card["assignee_ids"],
        "label_ids": label_ids,
        "cover": card["cover"],
        "repeat": card["repeat"] if keep_repeat else None,
        "completed_at": now if column["kind"] == "done" else None,
    }
    new_id = conn.execute(
        f"INSERT INTO cards ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
    ).lastrowid
    _renumber(conn, "cards", ids + [new_id])
    for step in conn.execute(
        "SELECT * FROM recordings WHERE card_id = ? AND list_id = ? AND type = 'step' "
        "AND status = 'active' ORDER BY position, id",
        (card["id"], list_id),
    ).fetchall():
        conn.execute(
            "INSERT INTO recordings (list_id, board_id, card_id, type, title, status, position, due_on, "
            "assignee_ids, data, creator_id, source, source_client, created_at, updated_at) "
            "VALUES (?, ?, ?, 'step', ?, 'active', ?, ?, ?, '{}', ?, ?, ?, ?, ?)",
            (
                list_id,
                board_id,
                new_id,
                step["title"],
                step["position"],
                moved(step["due_on"]),
                step["assignee_ids"],
                people.actor_in(conn, list_id, client, source),
                source,
                common.clean_source_client(client),
                now,
                now,
            ),
        )
    return new_id


def _repeat_in(conn, list_id: int, card: dict, was: dict | None, source: str, client: str | None) -> int | None:
    """A repeating card just finished: the next one, due on the next day of its
    rule, waits where this one was (Triage, Not now or its work column; the first
    work column when it was already in Done or came from another project). The
    repeat moves to the new card."""
    if not card.get("repeat"):
        return None
    nxt, shift = recordings.next_and_shift(card["repeat"], card["due_date"], recordings._today(conn, list_id))
    # At a cap: refused, with the finishing, rather than a lost repeat.
    _check_cap(conn, list_id, "cards")
    recordings._check_cap(
        conn,
        list_id,
        adding=conn.execute(
            "SELECT COUNT(*) FROM recordings WHERE card_id = ? AND list_id = ? AND type = 'step' AND status = 'active'",
            (card["id"], list_id),
        ).fetchone()[0],
    )
    columns = _columns(conn, card["board_id"])
    home = (
        was
        if was and was["kind"] != "done" and was.get("status", "active") == "active"
        else next((c for c in columns if c["kind"] == "column"), _kind_column(conn, card["board_id"], "triage"))
    )
    new_id = _copy_card_in(
        conn, list_id, card, card["board_id"], home, due_date=nxt, shift=shift, source=source, client=client
    )
    conn.execute("UPDATE cards SET repeat = NULL WHERE id = ?", (card["id"],))
    _trail(conn, list_id, card["board_id"], "created", source, client, card_id=new_id, detail=home["name"])
    return new_id


def card_templates(list_id: int) -> list[dict]:
    """Every card template in the account's open projects, for Trello's "Create from
    template" at the foot of any column (here usable in every project)."""
    return [
        dict(r)
        for r in db.get_db().execute(
            "SELECT c.id, c.title, c.board_id, b.name AS board_name FROM cards c JOIN boards b ON b.id = c.board_id "
            "WHERE c.list_id = ? AND c.template = 1 AND c.status = 'active' AND b.status = 'active' "
            "ORDER BY lower(b.name), lower(c.title), c.id LIMIT 200",
            (list_id,),
        )
    ]


def copy_card(
    list_id: int,
    card_id: int,
    *,
    column=None,
    board=None,
    title: str | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """Copy a card (Trello's Copy card, and making a card from a template): into
    `column` of its own project, or of `board`; by default the same column, or
    Triage in another project. The copy is open, never a template itself."""
    if title is not None:
        title = _name(title, "title")
    with db.transaction() as conn:
        card = conn.execute("SELECT * FROM cards WHERE id = ? AND list_id = ?", (card_id, list_id)).fetchone()
        if card is None:
            raise NotFoundError(f"Card not found: {card_id}")
        card = dict(card)
        target = _board(conn, list_id, board if board not in (None, "") else card["board_id"])
        if target["status"] != "active":
            raise ValidationError("That project is archived. Restore it first.")
        if column not in (None, ""):
            col = _column(conn, list_id, target["id"], column)
        elif target["id"] == card["board_id"]:
            col = dict(conn.execute("SELECT * FROM board_columns WHERE id = ?", (card["column_id"],)).fetchone())
            if col["status"] != "active" or col["kind"] == "done":
                col = _kind_column(conn, target["id"], "triage")
        else:
            col = _kind_column(conn, target["id"], "triage")
        _check_cap(conn, list_id, "cards")
        recordings._check_cap(
            conn,
            list_id,
            adding=conn.execute(
                "SELECT COUNT(*) FROM recordings WHERE card_id = ? AND list_id = ? AND type = 'step' AND status = 'active'",
                (card_id, list_id),
            ).fetchone()[0],
        )
        new_id = _copy_card_in(conn, list_id, card, target["id"], col, title=title, source=source, client=client)
        _touch(conn, "boards", target["id"], {})
        _trail(
            conn,
            list_id,
            target["id"],
            "copied" if not card["template"] else "created",
            source,
            client,
            card_id=new_id,
            detail=col["name"],
        )
    _fire(list_id, target["id"], "card_added", new_id, col["id"])
    return get_card(list_id, new_id)
