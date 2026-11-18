"""Projects GTD — everything in a project but its card table, as Basecamp models it.

A project (a `boards` row) has a dock of tools. Each tool holds recordings: the
Message Board its messages, To-dos its to-do lists, their groups and to-dos, and
so on. One table holds them all (`recordings`, with a `type`), so the things
every tool shares are written once: comments, boosts, the activity trail,
archive, trash, moving and copying. A card's comments are recordings too, tied
to the card by `card_id`.

Like boards.py, every function takes the `list_id` first and scopes every query
by it, every write is one ``db.transaction()``, and nothing is deleted:
archived and trashed are statuses, and both can be undone. A recording's
`version` goes up on every change, and an edit naming an older one is refused.

Writes take `source` ('ui' or 'agent') and the AI tool's name; people.actor_in
turns them into the person who did it, for the recording and the trail.
"""

import datetime
import json
import re
from typing import NamedTuple, cast

from backend.paid import caps as paid_caps
from backend.paid import plans
from backend.paid import billing
from backend import common, db, people, settings
from backend.common import ConflictError, NotFoundError, ValidationError

# 'drafted' is a message not yet posted: only its writer sees it, under Drafts.
STATUSES = ("active", "archived", "trashed", "drafted")
# Basecamp's palette for to-do lists, groups, folders and card columns.
COLORS = ("white", "red", "orange", "yellow", "green", "blue", "aqua", "purple", "gray", "pink", "brown")
MAX_PINNED = 10
MAX_BOOST_CHARS = 16
MAX_ASSIGNEES = 20
PREVIEW = 3  # items a tool's card on the project page shows


class Type(NamedTuple):
    label: str  # how the app names one: "To-do"
    tool: str | None  # the dock tool it lives in; None for a comment
    parents: tuple  # the types it may sit under; None = the top of its tool
    fields: frozenset  # what a create or an edit may set
    titled: bool  # a title is required


_COMMON = {"title", "body", "status", "spotlight"}
TYPES: dict[str, Type] = {
    "message": Type("Message", "message_board", (None,), frozenset(_COMMON | {"category", "pinned", "post_at"}), True),
    "todolist": Type("To-do list", "todoset", (None,), frozenset(_COMMON | {"color"}), True),
    "todolist_group": Type("Group", "todoset", ("todolist",), frozenset({"title", "status", "color"}), True),
    # A to-do with no parent is a loose one, at the top of the To-dos page.
    "todo": Type(
        "To-do",
        "todoset",
        (None, "todolist", "todolist_group"),
        frozenset(_COMMON | {"due_on", "starts_on", "assignee_ids", "repeat"}),
        True,
    ),
    # A subtask (Basecamp's "step") of a to-do or, by card_id, of a card.
    "step": Type("Subtask", None, ("todo",), frozenset({"title", "status", "due_on", "assignee_ids"}), True),
    "comment": Type("Comment", None, ("*",), frozenset({"body", "status"}), False),
    # Docs & Files: folders that nest, Markdown documents, and links to files elsewhere.
    "vault": Type("Folder", "vault", (None, "vault"), frozenset({"title", "status", "color", "spotlight"}), True),
    "document": Type("Document", "vault", (None, "vault"), frozenset(_COMMON | {"color"}), True),
    "link": Type("Link", "vault", (None, "vault"), frozenset(_COMMON | {"url", "color"}), True),
    # Calendar: an event, all day or timed, over one day or several, perhaps repeating.
    "schedule_entry": Type(
        "Event",
        "schedule",
        (None,),
        frozenset(
            _COMMON
            | {
                "starts_on",
                "ends_on",
                "starts_at",
                "ends_at",
                "all_day",
                "url",
                "highlighted",
                "assignee_ids",
                "repeat",
                "repeat_until",
            }
        ),
        True,
    ),
    # Automatic Check-ins: a question asked on a schedule, and the answers to it.
    "question": Type(
        "Check-in",
        "questionnaire",
        (None,),
        frozenset({"title", "status", "assignee_ids", "frequency", "days", "time", "paused", "spotlight"}),
        True,
    ),
    "answer": Type("Answer", "questionnaire", ("question",), frozenset({"body", "status", "group_on"}), False),
    # Chat (Basecamp 5's, once Campfire): a line said in the project's room.
    "chat_line": Type("Chat line", "chat", (None,), frozenset({"body", "status"}), False),
    # External links (Basecamp's Doors): a way out to a tool kept elsewhere.
    "door": Type("External link", "doors", (None,), frozenset({"title", "body", "status", "url", "color"}), True),
    # A wormhole (Basecamp 5's, on a Card Table): a column of another project's table;
    # a card dropped on it goes there. Its column is fixed: archive it to close it.
    "wormhole": Type("Wormhole", "kanban_board", (None,), frozenset({"status", "column_id"}), False),
    # The Needle: how the project is going, with a note; the latest is its state.
    "needle": Type("Needle", None, (None,), frozenset({"body", "status", "needle"}), False),
    # A Hill Chart update: where the tracked to-do lists stood, with a note (set_hill).
    "hill_update": Type("Hill Chart update", "todoset", (None,), frozenset({"body", "status"}), False),
}
# Types that cannot be commented on or boosted.
_QUIET = {"todolist_group", "comment", "step", "vault", "needle", "hill_update", "chat_line", "door", "wormhole"}
# The person's judgment of their own project: AI tools read these, never set them.
PERSON_ONLY = {"needle", "hill_update"}
NEEDLES = ("on_track", "some_risk", "concerned")
MAX_SPOTLIGHT = 12
MAX_WORMHOLES = 4  # Basecamp's limit per Card Table
MAX_IMPORT = 500  # lines in one Markdown import, as Basecamp's
# Types that can be checked off.
_COMPLETABLE = {"todo", "step"}
# Types a card can hold (by card_id).
_ON_CARDS = {"comment", "step"}

# The tools a project can have, in order: key, then the name a project shows
# until it renames one.
TOOLS = {
    "message_board": "Messages",
    "todoset": "To-dos",
    "vault": "Docs",
    "chat": "Chat",
    "schedule": "Calendar",
    "questionnaire": "Check-ins",
    "kanban_board": "Board",
    "doors": "Links",
}
# The names those tools had before (Basecamp's): a dock saved with one shows today's.
_OLD_TITLES = {"Message Board", "Docs & Files", "Automatic Check-ins", "Card Table", "External links"}
# How an event repeats, and how often a check-in question is asked.
REPEATS = ("", "every_day", "every_weekday", "every_week", "every_other_week", "every_month", "every_year")
FREQUENCIES = ("every_day", "every_week", "every_other_week", "every_month")

# What a trail row says a person did ("Claude completed …").
ACTIONS = {
    "created": "added",
    "posted": "posted",
    "commented": "commented on",
    "edited": "edited",
    "completed": "completed",
    "reopened": "re-opened",
    "archived": "archived",
    "trashed": "trashed",
    "restored": "restored",
    "moved": "moved",
    "boosted": "reacted to",
    "assigned": "assigned",
    "started": "started the project",
    "copied": "copied",
    "chatted": "chatted in",
}


# ── Checks ────────────────────────────────────────────────────────────────────


def _type(kind) -> Type:
    if kind not in TYPES:
        raise ValidationError(f"Unknown type '{kind}'. Valid: {', '.join(TYPES)}")
    return TYPES[kind]


def _status(status) -> str:
    if status not in STATUSES:
        raise ValidationError(f"Invalid status '{status}'. Valid: {', '.join(STATUSES)}")
    return status


def _check_cap(conn, list_id: int, adding: int = 1) -> None:
    row = conn.execute(
        f"SELECT email_verified_at, {paid_caps.PLAN_COLUMNS} FROM lists WHERE id = ?", (list_id,)
    ).fetchone()
    verified, hosted = bool(row and row["email_verified_at"]), settings.open_signup()
    plan = plans.of(row) if row else None
    cap = common.recording_cap_for(verified, hosted, plan)
    # Boosts count with the recordings: each is a row someone wrote.
    n = conn.execute(
        "SELECT (SELECT COUNT(*) FROM recordings WHERE list_id = ?) + (SELECT COUNT(*) FROM boosts WHERE list_id = ?)",
        (list_id, list_id),
    ).fetchone()[0]
    if n + adding <= cap:
        return
    if hosted and not verified:
        raise ValidationError(
            f"This account holds {cap} items until an email is confirmed under Connect. Nothing was changed."
        )
    raise ValidationError(
        f"An account holds at most {cap} items.{billing.upsell(hosted and not plan)} Nothing was changed."
    )


def _board(conn, list_id: int, ref) -> dict:
    from backend import boards  # here: boards imports this module for the card trail

    return boards._board(conn, list_id, ref)


def _clean(conn, list_id: int, kind: str, fields: dict, *, creating: bool) -> dict:
    """`fields` checked for a recording of type `kind`, as columns to write."""
    spec = _type(kind)
    unknown = sorted(set(fields) - spec.fields)
    if unknown:
        raise ValidationError(
            f"A {spec.label.lower()} has no {', '.join(unknown)}. Valid: {', '.join(sorted(spec.fields))}"
        )
    out: dict = {}
    if "title" in fields or (creating and spec.titled):
        out["title"] = common.validate_short(fields.get("title"), "title")
        if spec.titled and not out["title"]:
            raise ValidationError("title is required")
    if "body" in fields:
        out["body"] = common.validate_notes(fields["body"], "body")
        if kind in ("comment", "answer", "chat_line") and not out["body"].strip():
            raise ValidationError(f"A {spec.label.lower()} needs some text")
    elif creating and kind in ("comment", "answer", "chat_line"):
        raise ValidationError(f"A {spec.label.lower()} needs some text")
    if "status" in fields:
        out["status"] = _status(fields["status"])
        if out["status"] == "drafted" and kind != "message":
            raise ValidationError("Only a message can be a draft")
    if "category" in fields:
        out["category"] = common.validate_short(fields["category"], "category")
    if "color" in fields:
        if fields["color"] not in ("", *COLORS):
            raise ValidationError(f"color must be one of {', '.join(COLORS)}, or empty")
        out["color"] = fields["color"]
    for date in ("due_on", "starts_on"):
        if date in fields:
            out[date] = common.validate_due(fields[date], date)
    if out.get("starts_on") and out.get("due_on") and out["starts_on"] > out["due_on"]:
        raise ValidationError("starts_on must not be after due_on")
    if "assignee_ids" in fields:
        ids = people.resolve_in(conn, list_id, fields["assignee_ids"])
        if len(ids) > MAX_ASSIGNEES:
            raise ValidationError(f"At most {MAX_ASSIGNEES} people")
        out["assignee_ids"] = json.dumps(ids)
    _clean_extras(kind, fields, out)
    if "body" in out and kind in _MENTIONABLE:
        out["data_mentions"] = _mentions_in(conn, list_id, out["body"]) or None
    if "pinned" in fields:
        # When it was pinned: pinned messages list in the order they were pinned.
        # `pin` is the per-board sequence that orders them (set where the board is known).
        out["data_pinned_at"] = common.now_iso() if fields["pinned"] else None
        if not fields["pinned"]:
            out["data_pin"] = None
    return out


_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# What can @mention people: what is written to someone.
_MENTIONABLE = {"message", "comment", "chat_line", "answer", "document", "todo"}


def _mentions_in(conn, list_id: int, body: str) -> list[int]:
    """The people a text @mentions by name (case aside, longest name first, so
    "@Ann Lee" is Ann Lee, not Ann): Basecamp's @mentions, kept as ids."""
    found: list[int] = []
    rest = body
    for person in sorted(
        conn.execute("SELECT id, name FROM people WHERE list_id = ? AND status = 'active'", (list_id,)).fetchall(),
        key=lambda p: -len(p["name"]),
    ):
        # After a space or an opening bracket or quote only: not in an address (x@Ann, …/@Ann).
        pattern = re.compile(r"(?<![^\s(\[{\"'])@" + re.escape(person["name"]) + r"(?![\w])", re.IGNORECASE)
        if pattern.search(rest):
            found.append(person["id"])
            rest = pattern.sub(" ", rest)
    return found


def _clean_extras(kind: str, fields: dict, out: dict) -> None:
    """The fields of Docs & Files, Calendar and Check-ins. Dates are the list's own
    calendar dates and times its wall clock ("HH:MM"), as Basecamp shows them."""
    if "url" in fields:
        url = common.validate_short(fields["url"], "url")
        if url and not re.match(r"^https?://", url, re.I):
            raise ValidationError("url must start with http:// or https://")
        if kind in ("link", "door") and not url:
            raise ValidationError(f"A {TYPES[kind].label.lower()} needs a url")
        out["data_url"] = url
    if "ends_on" in fields:  # an event's last day lives in due_on
        out["due_on"] = common.validate_due(fields["ends_on"], "ends_on")
    for name in ("starts_at", "ends_at", "time"):
        if name in fields:
            value = str(fields[name] or "").strip()
            if value and not _TIME.match(value):
                raise ValidationError(f"{name} must be HH:MM, 24-hour")
            out[f"data_{name}"] = value or None
    for name in ("all_day", "highlighted", "paused"):
        if name in fields:
            out[f"data_{name}"] = bool(fields[name])
    if "repeat" in fields:
        if fields["repeat"] not in (None, *REPEATS):  # None or "": does not repeat
            raise ValidationError(f"repeat must be one of {', '.join(r for r in REPEATS if r)}, or empty")
        out["data_repeat"] = fields["repeat"] or None
    if "repeat_until" in fields:
        out["data_repeat_until"] = common.validate_due(fields["repeat_until"], "repeat_until")
    if "frequency" in fields:
        if fields["frequency"] not in FREQUENCIES:
            raise ValidationError(f"frequency must be one of {', '.join(FREQUENCIES)}")
        out["data_frequency"] = fields["frequency"]
    if "days" in fields:
        days = fields["days"]
        if not isinstance(days, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
            raise ValidationError("days must be a list of weekdays, 0 (Sunday) to 6 (Saturday)")
        out["data_days"] = sorted(set(days))
    if "group_on" in fields:
        out["data_group_on"] = common.validate_due(fields["group_on"], "group_on")
    if "post_at" in fields:
        # A draft posts itself then (the background loop, publish_scheduled); None cancels.
        out["data_post_at"] = _when(fields["post_at"]) if fields["post_at"] else None
    if "needle" in fields:
        if fields["needle"] not in NEEDLES:
            raise ValidationError(f"needle must be one of {', '.join(NEEDLES)}")
        out["data_needle"] = fields["needle"]
    if "spotlight" in fields:
        out["data_spotlight"] = bool(fields["spotlight"]) or None
    if "column_id" in fields:
        col = fields["column_id"]
        if not isinstance(col, int) or isinstance(col, bool) or not 0 < col < 2**62:
            raise ValidationError("column_id must be a column's id")
        out["data_column_id"] = col


def _when(value) -> str:
    """An ISO date-time (with its offset, or UTC) as the app's stamp, at least a minute from now."""
    try:
        at = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        raise ValidationError("post_at must be an ISO date and time, like 2026-11-02T09:00:00Z") from None
    if at.tzinfo is None:
        at = at.replace(tzinfo=datetime.timezone.utc)
    if at < common.utcnow() + datetime.timedelta(seconds=30):
        raise ValidationError("post_at must be in the future")
    return common.to_iso(at)


def next_due(repeat: str, due: str | None, today: datetime.date) -> str:
    """The next due day of a repeating to-do or card (REPEATS), from its due day
    (today when it has none); never one already past, so finishing late does not
    leave the next one overdue."""
    from backend import schedules

    days = {"every_day": 1, "every_weekday": 1, "every_week": 7, "every_other_week": 14}.get(repeat)
    months = {"every_month": 1, "every_year": 12}.get(repeat)
    if not (days or months):
        raise ValidationError(f"repeat must be one of {', '.join(r for r in REPEATS if r)}")

    def step(day: datetime.date) -> datetime.date:
        # A validated repeat has either a day interval or a month interval.
        day = day + datetime.timedelta(days=days) if days else schedules._add_months(day, cast(int, months))
        while repeat == "every_weekday" and day.weekday() >= 5:
            day += datetime.timedelta(days=1)
        return day

    try:
        nxt = step(datetime.date.fromisoformat(due) if due else today)
        return (step(today) if nxt < today else nxt).isoformat()
    except (OverflowError, ValueError):
        raise ValidationError("The next due date is out of range. Clear the repeat first.") from None


def next_and_shift(repeat: str, due: str | None, today: datetime.date) -> tuple[str, int]:
    """next_due, and how many days on from `due` it is (0 with no due date): what a
    repeating to-do's or card's next one moves its other dates by."""
    nxt = next_due(repeat, due, today)
    return nxt, (datetime.date.fromisoformat(nxt) - datetime.date.fromisoformat(due)).days if due else 0


def _tz(conn, list_id: int) -> str:
    return conn.execute("SELECT tz FROM lists WHERE id = ?", (list_id,)).fetchone()["tz"]


def _today(conn, list_id: int) -> datetime.date:
    return common.business_today(_tz(conn, list_id))


def _defaults(conn, list_id: int, kind: str, cols: dict) -> None:
    """What a new event, check-in question or answer starts with when not told."""
    if kind in ("link", "door") and not cols.get("data_url"):
        raise ValidationError(f"A {TYPES[kind].label.lower()} needs a url")
    if kind == "schedule_entry":
        if not cols.get("starts_on"):
            raise ValidationError("An event needs starts_on (YYYY-MM-DD)")
        cols.setdefault("due_on", cols["starts_on"])
        if cols["due_on"] is None or cols["due_on"] < cols["starts_on"]:
            raise ValidationError("An event can't end before it starts")
        cols.setdefault("data_all_day", not cols.get("data_starts_at"))
    elif kind == "question":
        # Basecamp's own example: "What did you work on today?", weekdays at 9 am, asking me.
        cols.setdefault("data_frequency", "every_day")
        cols.setdefault("data_days", [1, 2, 3, 4, 5])
        cols.setdefault("data_time", "09:00")
        if "assignee_ids" not in cols:
            cols["assignee_ids"] = json.dumps([people.me_in(conn, list_id)])
    elif kind == "answer" and not cols.get("data_group_on"):
        cols["data_group_on"] = _today(conn, list_id).isoformat()
    elif kind == "needle" and not cols.get("data_needle"):
        raise ValidationError(f"The Needle needs needle: {', '.join(NEEDLES)}")


# ── Reading ───────────────────────────────────────────────────────────────────


def _people(list_id: int) -> dict[int, dict]:
    return {
        r["id"]: {"id": r["id"], "name": r["name"], "kind": r["kind"], "color": r["color"]}
        for r in db.get_db().execute("SELECT id, name, kind, color FROM people WHERE list_id = ?", (list_id,))
    }


def _shape(row, who: dict[int, dict]) -> dict:
    """A recording as the app and the agent see it: people as {id, name, kind,
    color}, `data` unpacked onto it."""
    rec = dict(row)
    data = json.loads(rec.pop("data") or "{}")
    ids = json.loads(rec.pop("assignee_ids") or "[]")
    rec["assignees"] = [who[i] for i in ids if i in who]
    rec["creator"] = who.get(rec.pop("creator_id"))
    rec["completer"] = who.get(rec.pop("completer_id"))
    rec["completed"] = rec["completed_at"] is not None
    rec.pop("list_id", None)
    rec.update(data)
    return rec


_SELECT = (
    "SELECT r.*, b.name AS board_name, "
    "(SELECT COUNT(*) FROM recordings c WHERE c.parent_id = r.id AND c.type = 'comment' "
    " AND c.list_id = r.list_id AND c.status = 'active') AS comments_count "
    "FROM recordings r JOIN boards b ON b.id = r.board_id"
)


def _get_row(conn, list_id: int, rec_id: int):
    row = conn.execute(f"{_SELECT} WHERE r.id = ? AND r.list_id = ?", (rec_id, list_id)).fetchone()
    if row is None:
        raise NotFoundError(f"Not found: {rec_id}")
    return row


def get(list_id: int, rec_id: int) -> dict:
    return _shape(_get_row(db.get_db(), list_id, rec_id), _people(list_id))


def _boosts(list_id: int, *, rec_ids=(), card_ids=()) -> dict:
    """Active boosts as {('r', id) or ('c', id): [boost, …]}, oldest first."""
    who = _people(list_id)
    out: dict = {}
    for column, key, ids in (("recording_id", "r", rec_ids), ("card_id", "c", card_ids)):
        ids = list(ids)
        if not ids:
            continue
        marks = ",".join("?" * len(ids))
        for row in db.get_db().execute(
            f"SELECT id, {column} AS target, content, booster_id, created_at FROM boosts "
            f"WHERE list_id = ? AND status = 'active' AND {column} IN ({marks}) ORDER BY id",
            (list_id, *ids),
        ):
            out.setdefault((key, row["target"]), []).append(
                {
                    "id": row["id"],
                    "content": row["content"],
                    "booster": who.get(row["booster_id"]),
                    "created_at": row["created_at"],
                }
            )
    return out


def children(list_id: int, parent_id: int, status: str = "active") -> list[dict]:
    """A recording's children but its comments, in order."""
    who = _people(list_id)
    return [
        _shape(r, who)
        for r in db.get_db().execute(
            f"{_SELECT} WHERE r.list_id = ? AND r.parent_id = ? AND r.type != 'comment' "
            "AND r.status = ? ORDER BY r.position, r.id",
            (list_id, parent_id, status),
        )
    ]


def card_steps(list_id: int, card_id: int) -> list[dict]:
    """A card's subtasks, in order."""
    who = _people(list_id)
    return [
        _shape(r, who)
        for r in db.get_db().execute(
            f"{_SELECT} WHERE r.list_id = ? AND r.card_id = ? AND r.type = 'step' AND r.status = 'active' "
            "ORDER BY r.position, r.id",
            (list_id, card_id),
        )
    ]


def comments(list_id: int, *, rec_id: int | None = None, card_id: int | None = None) -> list[dict]:
    """The active comments on a recording or a card, oldest first, with their boosts."""
    who = _people(list_id)
    column, target = ("parent_id", rec_id) if rec_id is not None else ("card_id", card_id)
    rows = [
        _shape(r, who)
        for r in db.get_db().execute(
            f"{_SELECT} WHERE r.list_id = ? AND r.{column} = ? AND r.type = 'comment' "
            "AND r.status = 'active' ORDER BY r.id",
            (list_id, target),
        )
    ]
    boosts = _boosts(list_id, rec_ids=[c["id"] for c in rows])
    for c in rows:
        c["boosts"] = boosts.get(("r", c["id"]), [])
    return rows


def _ancestors(conn, list_id: int, rec: dict) -> list[dict]:
    """The recordings above `rec`, the topmost first: the breadcrumb."""
    out, parent = [], rec.get("parent_id")
    while parent:
        row = conn.execute(
            "SELECT id, type, title, parent_id FROM recordings WHERE id = ? AND list_id = ?", (parent, list_id)
        ).fetchone()
        if row is None:
            break
        out.insert(0, {"id": row["id"], "type": row["type"], "title": row["title"]})
        parent = row["parent_id"]
    return out


def _private(conn, list_id: int, rec: dict, source: str, client: str | None) -> bool:
    """A draft is its writer's, and the person's when an AI tool wrote it (an AI's
    draft waits for the person to post it): True when this reader is neither."""
    if rec["status"] != "drafted":
        return False
    creator = rec["creator"] or {}
    return not (
        creator.get("id") == people.viewer(conn, list_id, client, source)
        or (source == "ui" and creator.get("kind") == "ai")
    )


def thread(list_id: int, rec_id: int, *, source: str = "ui", client: str | None = None) -> dict:
    """One recording as its page shows it: the recording, the breadcrumb above
    it, its children (a to-do list's to-dos and groups, a group's to-dos), its
    comments and boosts, and whether it is bookmarked."""
    conn = db.get_db()
    rec = get(list_id, rec_id)
    if _private(conn, list_id, rec, source, client):
        raise NotFoundError(f"Not found: {rec_id}")
    rec["boosts"] = _boosts(list_id, rec_ids=[rec_id]).get(("r", rec_id), [])
    rec["bookmarked"] = (
        conn.execute(
            "SELECT 1 FROM bookmarks WHERE list_id = ? AND recording_id = ? AND status = 'active'", (list_id, rec_id)
        ).fetchone()
        is not None
    )
    out = {"recording": rec, "ancestors": _ancestors(conn, list_id, rec), "comments": comments(list_id, rec_id=rec_id)}
    if rec["type"] in ("todolist", "todolist_group"):
        out["children"] = _with_todos(list_id, children(list_id, rec_id))
        out["completed"] = [r for r in children(list_id, rec_id) if r["type"] == "todo" and r["completed"]]
        progress = _progress(conn, list_id, [rec_id])
        rec["completed_count"], rec["todos_count"] = progress.get(rec_id, (0, 0))
    elif rec["type"] == "todo":
        out["children"] = children(list_id, rec_id)  # its subtasks
    return out


def _with_todos(list_id: int, kids: list[dict]) -> list[dict]:
    """A to-do list's children with each group's open to-dos inside it, and each
    to-do list or group's progress (done / total)."""
    for kid in kids:
        if kid["type"] == "todolist_group":
            todos = children(list_id, kid["id"])
            kid["todos"] = [t for t in todos if not t["completed"]]
            kid["completed_todos"] = [t for t in todos if t["completed"]]
    return [k for k in kids if not (k["type"] == "todo" and k["completed"])]


def _progress(conn, list_id: int, rec_ids: list[int]) -> dict[int, tuple[int, int]]:
    """{to-do list or group id: (completed, total)} over its active to-dos, a
    list counting its groups' too."""
    if not rec_ids:
        return {}
    marks = ",".join("?" * len(rec_ids))
    out = {i: (0, 0) for i in rec_ids}
    for row in conn.execute(
        f"SELECT COALESCE(g.parent_id, t.parent_id) AS top, t.parent_id AS direct, "
        f"t.completed_at IS NOT NULL AS done FROM recordings t "
        f"LEFT JOIN recordings g ON g.id = t.parent_id AND g.type = 'todolist_group' "
        f"AND g.status = 'active' "
        f"WHERE t.list_id = ? AND t.type = 'todo' AND t.status = 'active' "
        f"AND (t.parent_id IN ({marks}) OR g.parent_id IN ({marks}))",
        (list_id, *rec_ids, *rec_ids),
    ):
        for key in {row["top"], row["direct"]} & set(out):
            done, total = out[key]
            out[key] = (done + row["done"], total + 1)
    return out


# How a message board can be sorted (Basecamp's three).
SORTS = {
    "newest": "r.created_at DESC, r.id DESC",
    "activity": "COALESCE((SELECT MAX(c.created_at) FROM recordings c WHERE c.parent_id = r.id "
    "AND c.type = 'comment' AND c.status = 'active'), r.created_at) DESC, r.id DESC",
    "alpha": "lower(r.title), r.id",
}


def list_items(
    list_id: int,
    board_ref,
    kind: str,
    status: str = "active",
    parent_id: int | None = None,
    sort: str = "newest",
    *,
    source: str = "ui",
    client: str | None = None,
) -> list[dict]:
    """A project's recordings of one type. Messages: pinned first (in the order
    they were pinned), then by `sort`; to-do lists in order, with their progress.
    Under `parent_id` when given; to-dos with no parent are the loose ones."""
    _type(kind)
    _status(status)
    if sort not in SORTS:
        raise ValidationError(f"sort must be one of {', '.join(SORTS)}")
    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    where, args = (
        "r.list_id = ? AND r.board_id = ? AND r.type = ? AND r.status = ?",
        [list_id, board["id"], kind, status],
    )
    if status == "drafted":  # the reader's own drafts, and the person sees the AI tools' too
        where += (
            " AND (r.creator_id IS ? OR (? AND r.creator_id IN "
            "(SELECT id FROM people WHERE list_id = r.list_id AND kind = 'ai')))"
        )
        args += [people.viewer(conn, list_id, client, source) or -1, source == "ui"]
    if parent_id is not None:
        where += " AND r.parent_id = ?"
        args.append(parent_id)
    elif None in TYPES[kind].parents:
        where += " AND r.parent_id IS NULL AND r.card_id IS NULL"
    order = (
        f"json_extract(r.data, '$.pin') IS NULL, json_extract(r.data, '$.pin'), {SORTS[sort]}"
        if kind == "message"
        else "r.position, r.id"
    )
    who = _people(list_id)
    rows = [_shape(r, who) for r in conn.execute(f"{_SELECT} WHERE {where} ORDER BY {order}", args)]
    if kind in ("todolist", "todolist_group"):
        progress = _progress(conn, list_id, [r["id"] for r in rows])
        for r in rows:
            r["completed_count"], r["todos_count"] = progress.get(r["id"], (0, 0))
    return rows


def todoset(list_id: int, board_ref, status: str = "active") -> dict:
    """The To-dos tool whole: the loose to-dos (open, then the completed), and
    each to-do list in order with its progress, its open to-dos and groups (each
    group with its own), and its completed to-dos."""
    loose = list_items(list_id, board_ref, "todo")
    lists = list_items(list_id, board_ref, "todolist", status)
    for tl in lists:
        kids = children(list_id, tl["id"])
        tl["completed_todos"] = [k for k in kids if k["type"] == "todo" and k["completed"]]
        tl["children"] = _with_todos(list_id, kids)
    return {
        "loose": [t for t in loose if not t["completed"]],
        "loose_completed": [t for t in loose if t["completed"]],
        "lists": lists,
    }


FOLDER_SORTS = {
    "name": "lower(r.title), r.id",
    "created": "r.created_at DESC, r.id DESC",
    "modified": "r.updated_at DESC, r.id DESC",
}


def folder(list_id: int, board_ref, folder_id: int | None = None, sort: str = "name", status: str = "active") -> dict:
    """Docs & Files: what one folder holds (the top when folder_id is None) —
    its folders first, each with how many things are in it, then its documents
    and links — and the folders above it, for the breadcrumb."""
    if sort not in FOLDER_SORTS:
        raise ValidationError(f"sort must be one of {', '.join(FOLDER_SORTS)}")
    _status(status)
    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    above: list = []
    if folder_id is not None:
        row = dict(_get_row(conn, list_id, folder_id))
        if row["type"] != "vault" or row["board_id"] != board["id"]:
            raise NotFoundError(f"Folder not found: {folder_id}")
        above = _ancestors(conn, list_id, row) + [{"id": row["id"], "type": "vault", "title": row["title"]}]
    where = "r.parent_id = ?" if folder_id is not None else "r.parent_id IS NULL"
    who = _people(list_id)
    items = [
        _shape(r, who)
        for r in conn.execute(
            f"{_SELECT} WHERE r.list_id = ? AND r.board_id = ? AND r.type IN ('vault', 'document', 'link') "
            f"AND r.status = ? AND {where} ORDER BY r.type != 'vault', {FOLDER_SORTS[sort]}",
            (list_id, board["id"], status, *([folder_id] if folder_id is not None else [])),
        )
    ]
    counts = {
        r["parent_id"]: r["n"]
        for r in conn.execute(
            "SELECT parent_id, COUNT(*) AS n FROM recordings WHERE list_id = ? AND board_id = ? AND status = 'active' "
            "AND type IN ('vault', 'document', 'link') AND parent_id IS NOT NULL GROUP BY parent_id",
            (list_id, board["id"]),
        )
    }
    for item in items:
        if item["type"] == "vault":
            item["items_count"] = counts.get(item["id"], 0)
    return {"folder_id": folder_id, "above": above, "items": items}


# ── The trail ─────────────────────────────────────────────────────────────────


def _excerpt(text: str, n: int = 140) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def event_in(
    conn,
    list_id: int,
    board_id: int,
    action: str,
    creator_id: int | None,
    *,
    rec_id: int | None = None,
    card_id: int | None = None,
    detail: str = "",
) -> None:
    """One row of the activity trail, inside the caller's write. The item's title
    comes from the item when the trail is read; `detail` is the extra (a comment's
    words, where a thing moved to, a boost)."""
    conn.execute(
        "INSERT INTO events (list_id, board_id, recording_id, card_id, action, detail, creator_id, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (list_id, board_id, rec_id, card_id, action, detail[:200], creator_id, common.now_iso()),
    )


def activity(
    list_id: int,
    *,
    board_id: int | None = None,
    person_id: int | None = None,
    rec_id: int | None = None,
    before: int | None = None,
    since: int | None = None,
    limit: int = 50,
) -> dict:
    """The trail, newest first, a page at a time (`before` = the last page's
    next_before): who did what to which item, in which project. `since` keeps only
    what came after that event (an agent's cursor: the answer's `latest`); `rec_id`
    only one item's own history (Basecamp's change log)."""
    limit = max(1, min(int(limit), 200))
    where, args = ["e.list_id = ?"], [list_id]
    for column, value in (("e.board_id", board_id), ("e.creator_id", person_id), ("e.recording_id", rec_id)):
        if value is not None:
            where.append(f"{column} = ?")
            args.append(value)
    if before is not None:
        where.append("e.id < ?")
        args.append(before)
    if since is not None:
        where.append("e.id > ?")
        args.append(since)
    who = _people(list_id)
    rows = (
        db.get_db()
        .execute(
            f"SELECT e.*, b.name AS board_name, r.type AS recording_type, {TITLE_SQL} AS recording_title, "
            "r.parent_id AS recording_parent_id, c.title AS card_title, c.board_id AS card_board_id "
            "FROM events e JOIN boards b ON b.id = e.board_id "
            "LEFT JOIN recordings r ON r.id = e.recording_id AND r.list_id = e.list_id "
            "LEFT JOIN recordings pr ON pr.id = r.parent_id AND pr.list_id = r.list_id "
            "LEFT JOIN cards c ON c.id = e.card_id AND c.list_id = e.list_id "
            f"WHERE {' AND '.join(where)} ORDER BY e.id DESC LIMIT ?",
            (*args, limit + 1),
        )
        .fetchall()
    )
    events = []
    for row in rows[:limit]:
        e = dict(row)
        e["creator"] = who.get(e.pop("creator_id"))
        e["verb"] = verb(e["action"], e["recording_type"])
        e.pop("list_id")
        events.append(e)
    latest = db.get_db().execute("SELECT MAX(id) FROM events WHERE list_id = ?", (list_id,)).fetchone()[0]
    return {"events": events, "next_before": events[-1]["id"] if len(rows) > limit else None, "latest": latest or 0}


# An answer has no title of its own: the activity names the question it answers
# (with `pr` the recording's parent, joined by the query).
TITLE_SQL = "CASE WHEN r.type = 'answer' THEN pr.title ELSE r.title END"


def verb(action: str, recording_type: str | None) -> str:
    """The activity line's verb: "answered" for a new answer, else ACTIONS'."""
    if action == "created" and recording_type in _NEW_VERBS:
        return _NEW_VERBS[recording_type]
    return ACTIONS.get(action, action)


_NEW_VERBS = {"answer": "answered", "needle": "updated the status of", "hill_update": "updated the Hill Chart on"}


# ── Writing ───────────────────────────────────────────────────────────────────


def _place(ids: list[int], item: int, position) -> list[int]:
    from backend import boards

    return boards._place(ids, item, position)


def _sibling_ids(conn, list_id: int, board_id: int, kind: str, parent_id, card_id) -> list[int]:
    if parent_id is not None:
        where, args = "parent_id = ?", [parent_id]
    elif card_id is not None:
        where, args = "card_id = ?", [card_id]
    else:
        where, args = "board_id = ? AND parent_id IS NULL AND card_id IS NULL AND type = ?", [board_id, kind]
    return [
        r["id"]
        for r in conn.execute(
            f"SELECT id FROM recordings WHERE list_id = ? AND {where} AND status = 'active' "
            "AND type != 'comment' ORDER BY position, id",
            (list_id, *args),
        )
    ]


def _parent(conn, list_id: int, kind: str, parent_id, card_id) -> tuple[int | None, dict | None]:
    """The board the new recording belongs to (from its parent or card), and the
    parent's row; checks the parent may hold this type."""
    spec = _type(kind)
    if card_id is not None:
        if parent_id is not None:
            raise ValidationError("Put it on one thing: an item or a card")
        if kind not in _ON_CARDS:
            raise ValidationError(f"A card can't hold a {spec.label.lower()}")
        card = conn.execute(
            "SELECT board_id, status FROM cards WHERE id = ? AND list_id = ?", (card_id, list_id)
        ).fetchone()
        if card is None:
            raise NotFoundError(f"Card not found: {card_id}")
        if card["status"] != "active":
            raise ValidationError("That card is archived. Restore it first.")
        return card["board_id"], None
    if parent_id is None:
        if kind == "step":
            raise ValidationError("A subtask goes on a to-do or a card")
        if None not in spec.parents:
            raise ValidationError(
                f"A {spec.label.lower()} goes inside a "
                f"{' or '.join(TYPES[p].label.lower() for p in spec.parents if p != '*')}"
            )
        return None, None
    parent = conn.execute("SELECT * FROM recordings WHERE id = ? AND list_id = ?", (parent_id, list_id)).fetchone()
    if parent is None:
        raise NotFoundError(f"Not found: {parent_id}")
    if spec.parents == ("*",):
        if parent["type"] in _QUIET:
            raise ValidationError(f"A {TYPES[parent['type']].label.lower()} can't take comments")
    elif parent["type"] not in spec.parents:
        raise ValidationError(f"A {spec.label.lower()} can't go inside a {TYPES[parent['type']].label.lower()}")
    if parent["status"] != "active":
        raise ValidationError("That item is archived or in the trash. Restore it first.")
    return parent["board_id"], dict(parent)


def _apply_data(conn, rec_id: int, cols: dict) -> dict:
    """Moves `data_*` keys out of `cols` into the recording's data JSON."""
    extra = {k[5:]: cols.pop(k) for k in list(cols) if k.startswith("data_")}
    if extra:
        row = conn.execute("SELECT data FROM recordings WHERE id = ?", (rec_id,)).fetchone()
        data = {**json.loads(row["data"] or "{}"), **extra}
        conn.execute("UPDATE recordings SET data = ? WHERE id = ?", (json.dumps(data), rec_id))
    return cols


def create(
    list_id: int,
    board_ref,
    kind: str,
    fields: dict,
    *,
    parent_id: int | None = None,
    card_id: int | None = None,
    position=None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """A new recording of type `kind` in a project (by id or name), under
    `parent_id` or on `card_id` when the type sits there."""
    if source == "agent" and kind in PERSON_ONLY:
        raise ValidationError(f"The {TYPES[kind].label} is the person's to set. You can read it.")
    with db.transaction() as conn:
        board_from_parent, parent = _parent(conn, list_id, kind, parent_id, card_id)
        board = _board(conn, list_id, board_from_parent if board_from_parent is not None else board_ref)
        if board["status"] != "active":
            raise ValidationError("This project is archived. Restore it first.")
        cols = _clean(conn, list_id, kind, fields, creating=True)
        _defaults(conn, list_id, kind, cols)
        _switch_on(conn, board, TYPES[kind].tool)
        if cols.get("data_pinned_at"):
            _check_pins(conn, list_id, board["id"])
            cols["data_pin"] = _next_pin(conn, list_id, board["id"])
        if cols.get("data_spotlight"):
            _check_spotlight(conn, list_id, board["id"])
        if kind == "wormhole":
            _check_wormhole(conn, list_id, board["id"], cols.get("data_column_id"))
        _check_cap(conn, list_id)
        actor = people.actor_in(conn, list_id, client, source)
        now = common.now_iso()
        siblings = [] if kind == "comment" else _sibling_ids(conn, list_id, board["id"], kind, parent_id, card_id)
        base = {
            "list_id": list_id,
            "board_id": board["id"],
            "parent_id": parent_id,
            "card_id": card_id,
            "type": kind,
            "position": len(siblings),
            "creator_id": actor,
            "source": source,
            "source_client": common.clean_source_client(client),
            "created_at": now,
            "updated_at": now,
        }
        data_cols = {k: cols.pop(k) for k in list(cols) if k.startswith("data_")}
        row = {**base, **cols}
        rec_id = conn.execute(
            f"INSERT INTO recordings ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
        ).lastrowid
        assert rec_id is not None  # A successful INSERT into a rowid table.
        _apply_data(conn, rec_id, data_cols)
        if kind != "comment":
            _renumber(conn, _place(siblings + [rec_id], rec_id, position))
        if kind == "comment":
            # The trail points at what was commented on, and quotes the comment.
            event_in(
                conn,
                list_id,
                board["id"],
                "commented",
                actor,
                rec_id=parent_id,
                card_id=card_id,
                detail=_excerpt(cols["body"]),
            )
        elif kind == "chat_line":
            # The room, not each line, is what is new: one trail row on the project.
            event_in(conn, list_id, board["id"], "chatted", actor, detail=_excerpt(cols["body"]))
        elif cols.get("status") != "drafted":
            event_in(conn, list_id, board["id"], "posted" if kind == "message" else "created", actor, rec_id=rec_id)
        _touch_board(conn, board["id"])
    return get(list_id, rec_id)


def _next_pin(conn, list_id: int, board_id: int) -> int:
    """The next place in the board's pin order (pinned_at ties within a second)."""
    top = conn.execute(
        "SELECT MAX(json_extract(data, '$.pin')) FROM recordings WHERE list_id = ? "
        "AND board_id = ? AND type = 'message'",
        (list_id, board_id),
    ).fetchone()[0]
    return 0 if top is None else top + 1


def _check_pins(conn, list_id: int, board_id: int) -> None:
    n = conn.execute(
        "SELECT COUNT(*) FROM recordings WHERE list_id = ? AND board_id = ? AND type = 'message' "
        "AND status = 'active' AND json_extract(data, '$.pinned_at') IS NOT NULL",
        (list_id, board_id),
    ).fetchone()[0]
    if n >= MAX_PINNED:
        raise ValidationError(f"At most {MAX_PINNED} messages can be pinned. Unpin one first.")


def _check_wormhole(conn, list_id: int, board_id: int, column_id) -> None:
    """A wormhole goes to an open column of another open project, once, and a
    table has at most MAX_WORMHOLES."""
    if column_id is None:
        raise ValidationError("A wormhole needs column_id: a column of another project's board")
    target = conn.execute(
        "SELECT c.board_id FROM board_columns c JOIN boards b ON b.id = c.board_id "
        "WHERE c.id = ? AND c.list_id = ? AND c.status = 'active' AND b.status = 'active'",
        (column_id, list_id),
    ).fetchone()
    if target is None:
        raise ValidationError("No such column in an open project")
    if target["board_id"] == board_id:
        raise ValidationError("A wormhole goes to another project; within this one, drag the card")
    open_ = [
        r[0]
        for r in conn.execute(
            "SELECT json_extract(data, '$.column_id') FROM recordings WHERE list_id = ? AND board_id = ? "
            "AND type = 'wormhole' AND status = 'active'",
            (list_id, board_id),
        )
    ]
    if column_id in open_:
        raise ValidationError("This table has a wormhole to that column already")
    if len(open_) >= MAX_WORMHOLES:
        raise ValidationError(f"A board has at most {MAX_WORMHOLES} wormholes. Archive one first.")


def _check_spotlight(conn, list_id: int, board_id: int) -> None:
    n = conn.execute(
        "SELECT COUNT(*) FROM recordings WHERE list_id = ? AND board_id = ? AND status = 'active' "
        "AND json_extract(data, '$.spotlight') = 1",
        (list_id, board_id),
    ).fetchone()[0]
    if n >= MAX_SPOTLIGHT:
        raise ValidationError(f"At most {MAX_SPOTLIGHT} things can be in a project's Spotlight. Take one out first.")


def _renumber(conn, ids: list[int]) -> None:
    conn.executemany("UPDATE recordings SET position = ? WHERE id = ?", [(n, i) for n, i in enumerate(ids)])


def _touch_board(conn, board_id: int) -> None:
    conn.execute("UPDATE boards SET updated_at = ? WHERE id = ?", (common.now_iso(), board_id))


def _write(conn, rec_id: int, cols: dict) -> None:
    cols = {**cols, "updated_at": common.now_iso()}
    conn.execute(
        f"UPDATE recordings SET {', '.join(f'{k} = ?' for k in cols)}, version = version + 1 WHERE id = ?",
        (*cols.values(), rec_id),
    )


def update(
    list_id: int,
    rec_id: int,
    fields: dict,
    version: int | None = None,
    *,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """Edit a recording; a status of archived or trashed puts it away, active
    brings it back. With `version`, refused when it has changed since."""
    with db.transaction() as conn:
        row = dict(_get_row(conn, list_id, rec_id))
        if source == "agent" and row["type"] in PERSON_ONLY:
            raise ValidationError(f"The {TYPES[row['type']].label} is the person's to set. You can read it.")
        if version is not None and version != row["version"]:
            raise ConflictError("This changed since it was opened. Nothing was saved; reload it to see the change.")
        cols = _clean(conn, list_id, row["type"], fields, creating=False)
        if set(cols.get("data_mentions") or []) - set(json.loads(row["data"] or "{}").get("mentions") or []):
            cols["data_mentioned_at"] = common.now_iso()  # someone newly mentioned hears it now
        if cols.get("data_spotlight") and not json.loads(row["data"] or "{}").get("spotlight"):
            _check_spotlight(conn, list_id, row["board_id"])
        if row["type"] == "wormhole":
            if "data_column_id" in cols:
                raise ValidationError("A wormhole's column is fixed: archive this one and add another")
            if cols.get("status") == "active" and row["status"] != "active":
                _check_wormhole(conn, list_id, row["board_id"], json.loads(row["data"] or "{}").get("column_id"))
        # One date at a time (the web app saves each on its own): check the range
        # the edit leaves, not just the dates it sends.
        starts, due = cols.get("starts_on", row["starts_on"]), cols.get("due_on", row["due_on"])
        if starts and due and starts > due:
            raise ValidationError("starts_on must not be after due_on")
        if not cols:
            return get(list_id, rec_id)
        if cols.get("data_pinned_at") and json.loads(row["data"] or "{}").get("pinned_at"):
            cols.pop("data_pinned_at")  # pinned already: keep its place
        elif cols.get("data_pinned_at"):
            _check_pins(conn, list_id, row["board_id"])
            cols["data_pin"] = _next_pin(conn, list_id, row["board_id"])
        actor = people.actor_in(conn, list_id, client, source)
        if row["status"] == "drafted" and _private(conn, list_id, _shape(row, _people(list_id)), source, client):
            raise NotFoundError(f"Not found: {rec_id}")  # someone else's draft
        status = cols.get("status", row["status"])
        if (
            status == "active"
            and row["status"] != "active"
            and row["type"] == "message"
            and json.loads(row["data"] or "{}").get("pinned_at")
            and "pinned" not in fields
        ):
            # Back from the archive or trash while the board has its ten pins: it comes
            # back unpinned rather than over the cap.
            try:
                _check_pins(conn, list_id, row["board_id"])
            except ValidationError:
                _apply_data(conn, rec_id, {"data_pinned_at": None, "data_pin": None})
        if (
            status == "active"
            and row["status"] != "active"
            and json.loads(row["data"] or "{}").get("spotlight")
            and "spotlight" not in fields
        ):
            # The same for the Spotlight: back out of it when it is full.
            try:
                _check_spotlight(conn, list_id, row["board_id"])
            except ValidationError:
                _apply_data(conn, rec_id, {"data_spotlight": None})
        if status == "drafted" and row["status"] != "drafted":
            raise ValidationError("A posted message can't go back to being a draft")
        if row["status"] == "drafted" and status == "active":
            action = "posted"
        elif status != row["status"]:
            action = {"archived": "archived", "trashed": "trashed", "active": "restored"}[status]
        else:
            action = "edited"
        if "assignee_ids" in cols and cols["assignee_ids"] != row["assignee_ids"] and action == "edited":
            action = "assigned"
        cols = _apply_data(conn, rec_id, cols)
        _write(conn, rec_id, cols)
        pin_only = set(fields) <= {"pinned", "spotlight"}  # placement, not an edit: no trail
        if (row["type"] != "comment" or action != "edited") and status != "drafted" and not pin_only:
            event_in(
                conn,
                list_id,
                row["board_id"],
                action,
                actor,
                rec_id=rec_id,
                card_id=row["card_id"],
                detail=_excerpt(row["body"]) if row["type"] == "comment" else "",
            )
        _touch_board(conn, row["board_id"])
    return get(list_id, rec_id)


def _check_live(conn, list_id: int, row: dict) -> None:
    """Refuse new work on a recording that is put away, or sits under something
    put away (its parents, its card, its project): restore that first."""
    if row["status"] != "active":
        raise ValidationError("This is archived or in the trash. Restore it first.")
    parent = row["parent_id"]
    while parent:
        up = conn.execute(
            "SELECT status, parent_id FROM recordings WHERE id = ? AND list_id = ?", (parent, list_id)
        ).fetchone()
        if up is None:
            break
        if up["status"] != "active":
            raise ValidationError("What this sits in is archived or in the trash. Restore it first.")
        parent = up["parent_id"]
    if row["card_id"] is not None:
        card = conn.execute(
            "SELECT status FROM cards WHERE id = ? AND list_id = ?", (row["card_id"], list_id)
        ).fetchone()
        if card is not None and card["status"] != "active":
            raise ValidationError("That card is archived. Restore it first.")
    board = conn.execute("SELECT status FROM boards WHERE id = ?", (row["board_id"],)).fetchone()
    if board is not None and board["status"] != "active":
        raise ValidationError("This project is archived. Restore it first.")


def complete(list_id: int, rec_id: int, done: bool = True, *, source: str = "ui", client: str | None = None) -> dict:
    """Check off a to-do, or (done=False) re-open it."""
    with db.transaction() as conn:
        row = dict(_get_row(conn, list_id, rec_id))
        if row["type"] not in _COMPLETABLE:
            raise ValidationError("Only a to-do or a subtask can be completed")
        _check_live(conn, list_id, row)
        if bool(row["completed_at"]) == bool(done):
            return get(list_id, rec_id)
        actor = people.actor_in(conn, list_id, client, source)
        _write(
            conn, rec_id, {"completed_at": common.now_iso() if done else None, "completer_id": actor if done else None}
        )
        event_in(
            conn,
            list_id,
            row["board_id"],
            "completed" if done else "reopened",
            actor,
            rec_id=rec_id,
            card_id=row["card_id"],
        )
        repeat = json.loads(row["data"] or "{}").get("repeat")
        if done and row["type"] == "todo" and repeat:
            # Basecamp's repeating to-do: finishing one adds the next, due on the next day
            # of its rule; the repeat moves to the new one, so re-opening this adds none.
            nxt, shift = next_and_shift(repeat, row["due_on"], _today(conn, list_id))
            # At the cap the next one has nowhere to go: refused, so nothing is lost silently.
            _check_cap(conn, list_id, adding=len(_subtree(conn, list_id, rec_id)))
            new_id = _copy_in(
                conn, list_id, row, row["board_id"], row["parent_id"], actor, source, client, reset=True, shift=shift
            )
            if not row["due_on"]:
                _write(conn, new_id, {"due_on": nxt})
            _apply_data(conn, rec_id, {"data_repeat": None})
            event_in(conn, list_id, row["board_id"], "created", actor, rec_id=new_id)
        _touch_board(conn, row["board_id"])
        all_done = bool(
            done
            and row["card_id"]
            and not conn.execute(
                "SELECT 1 FROM recordings WHERE card_id = ? AND list_id = ? AND type = 'step' AND status = 'active' "
                "AND completed_at IS NULL",
                (row["card_id"], list_id),
            ).fetchone()
        )
    if all_done:  # a card's last subtask: the Card Table's "all subtasks done" rules
        from backend import boards  # here: boards imports this module

        boards._fire(list_id, row["board_id"], "subtasks_done", row["card_id"])
    return get(list_id, rec_id)


def move(
    list_id: int,
    rec_id: int,
    *,
    parent_id: int | None = None,
    board=None,
    position=None,
    before: int | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """Reorder a recording among its siblings, or move it under another parent
    (a to-do to another list or group) or, at the top of its tool, to another
    project. Its comments go with it. `before` puts it just above that sibling
    (what a drop names, whatever else the page hides)."""
    with db.transaction() as conn:
        row = dict(_get_row(conn, list_id, rec_id))
        if row["type"] == "comment":
            raise ValidationError("A comment stays where it was written")
        if row["type"] == "wormhole":
            raise ValidationError("A wormhole stays on its table: archive it and add one where you want it")
        if row["card_id"] is not None:
            raise ValidationError("A card's subtask stays on its card")
        if row["status"] != "active":
            raise ValidationError("This is archived or in the trash. Restore it first.")
        new_parent = row["parent_id"] if parent_id is None else parent_id
        if new_parent != row["parent_id"]:
            # A folder can't go inside itself or a folder within it.
            up = new_parent
            while up is not None:
                if up == rec_id:
                    raise ValidationError("A folder can't go inside itself")
                above = conn.execute(
                    "SELECT parent_id FROM recordings WHERE id = ? AND list_id = ?", (up, list_id)
                ).fetchone()
                up = above["parent_id"] if above else None
            board_id, _ = _parent(conn, list_id, row["type"], new_parent, None)
            if board_id is None:
                raise ValidationError("Pick where to move it")
        else:
            board_id = row["board_id"]
        if board not in (None, ""):
            if new_parent is not None and parent_id is not None:
                raise ValidationError("Move it to a project, or under a parent; not both")
            # Top-of-tool things go to a project; so do folders, documents and links
            # (to the top of its Docs & Files). A to-do goes under a list.
            if TYPES[row["type"]].parents != (None,) and TYPES[row["type"]].tool != "vault":
                raise ValidationError(f"Move a {TYPES[row['type']].label.lower()} under a parent instead")
            target = _board(conn, list_id, board)
            if target["status"] != "active":
                raise ValidationError("That project is archived. Restore it first.")
            board_id, new_parent = target["id"], None
        if board_id != row["board_id"]:
            _switch_on(conn, _board(conn, list_id, board_id), TYPES[row["type"]].tool)
        actor = people.actor_in(conn, list_id, client, source)
        moved = board_id != row["board_id"] or new_parent != row["parent_id"]
        _write(conn, rec_id, {"parent_id": new_parent, "board_id": board_id})
        if board_id != row["board_id"]:
            _move_subtree(conn, list_id, rec_id, board_id)
        siblings = _sibling_ids(conn, list_id, board_id, row["type"], new_parent, None)
        if before is not None:
            rest = [i for i in siblings if i != rec_id]
            if before not in rest:
                raise ValidationError("before must be another item in the same place")
            position = rest.index(before)
        _renumber(
            conn,
            _place(
                siblings, rec_id, position if position not in (None, "") else ("bottom" if moved else row["position"])
            ),
        )
        if moved:
            where = (
                conn.execute("SELECT title FROM recordings WHERE id = ?", (new_parent,)).fetchone()
                if new_parent
                else conn.execute("SELECT name AS title FROM boards WHERE id = ?", (board_id,)).fetchone()
            )
            event_in(conn, list_id, board_id, "moved", actor, rec_id=rec_id, detail=where["title"])
        for b in {row["board_id"], board_id}:
            _touch_board(conn, b)
    return get(list_id, rec_id)


def _move_subtree(conn, list_id: int, rec_id: int, board_id: int) -> None:
    """Everything under `rec_id` (children, comments, theirs) follows it to `board_id`."""
    level = [rec_id]
    while level:
        marks = ",".join("?" * len(level))
        kids = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM recordings WHERE list_id = ? AND parent_id IN ({marks})", (list_id, *level)
            )
        ]
        if kids:
            conn.execute(
                f"UPDATE recordings SET board_id = ? WHERE id IN ({','.join('?' * len(kids))})", (board_id, *kids)
            )
        level = kids


def comment(
    list_id: int,
    body: str,
    *,
    rec_id: int | None = None,
    card_id: int | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """Add a comment to a recording or a card."""
    if (rec_id is None) == (card_id is None):
        raise ValidationError("Comment on one item: a recording or a card")
    return create(
        list_id, None, "comment", {"body": body}, parent_id=rec_id, card_id=card_id, source=source, client=client
    )


def boost(
    list_id: int,
    content: str,
    *,
    rec_id: int | None = None,
    card_id: int | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """A boost: up to 16 characters (an emoji, "Nice!") on a recording or a card."""
    content = str(content or "").strip()
    if not content:
        raise ValidationError("A boost needs a few characters or an emoji")
    if len(content) > MAX_BOOST_CHARS:
        raise ValidationError(f"A boost is at most {MAX_BOOST_CHARS} characters")
    if (rec_id is None) == (card_id is None):
        raise ValidationError("Boost one item: a recording or a card")
    with db.transaction() as conn:
        if rec_id is not None:
            target = dict(_get_row(conn, list_id, rec_id))
            if target["type"] == "todolist_group":
                raise ValidationError("A group can't be boosted")
            _check_live(conn, list_id, target)
        else:
            target = conn.execute(
                "SELECT board_id, title, status FROM cards WHERE id = ? AND list_id = ?", (card_id, list_id)
            ).fetchone()
            if target is None:
                raise NotFoundError(f"Card not found: {card_id}")
            if target["status"] != "active":
                raise ValidationError("That card is archived. Restore it first.")
            target = dict(target)
        _check_cap(conn, list_id)
        actor = people.actor_in(conn, list_id, client, source)
        boost_id = conn.execute(
            "INSERT INTO boosts (list_id, recording_id, card_id, content, booster_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (list_id, rec_id, card_id, content, actor, common.now_iso()),
        ).lastrowid
        event_in(conn, list_id, target["board_id"], "boosted", actor, rec_id=rec_id, card_id=card_id, detail=content)
    return {"id": boost_id, "content": content, "booster": _people(list_id).get(actor)}


def unboost(list_id: int, boost_id: int) -> dict:
    """Take a boost back (status 'removed')."""
    with db.transaction() as conn:
        n = conn.execute(
            "UPDATE boosts SET status = 'removed' WHERE id = ? AND list_id = ?", (boost_id, list_id)
        ).rowcount
        if not n:
            raise NotFoundError(f"Boost not found: {boost_id}")
    return {"id": boost_id, "status": "removed"}


def card_thread(list_id: int, card_id: int) -> dict:
    """A card's comments, subtasks and boosts (its own fields come from boards.get_card)."""
    if db.get_db().execute("SELECT 1 FROM cards WHERE id = ? AND list_id = ?", (card_id, list_id)).fetchone() is None:
        raise NotFoundError(f"Card not found: {card_id}")
    return {
        "comments": comments(list_id, card_id=card_id),
        "subtasks": card_steps(list_id, card_id),
        "boosts": _boosts(list_id, card_ids=[card_id]).get(("c", card_id), []),
    }


# ── Bookmarks ─────────────────────────────────────────────────────────────────


def bookmark(
    list_id: int, on: bool, *, rec_id: int | None = None, card_id: int | None = None, board_id: int | None = None
) -> dict:
    """Bookmark an item (or a project), or (on=False) take the bookmark off."""
    targets = {"recording_id": rec_id, "card_id": card_id, "board_id": board_id}
    given = {k: v for k, v in targets.items() if v is not None}
    if len(given) != 1:
        raise ValidationError("Bookmark one thing: a recording, a card or a project")
    ((column, value),) = given.items()
    table = {"recording_id": "recordings", "card_id": "cards", "board_id": "boards"}[column]
    with db.transaction() as conn:
        if conn.execute(f"SELECT 1 FROM {table} WHERE id = ? AND list_id = ?", (value, list_id)).fetchone() is None:
            raise NotFoundError(f"Not found: {value}")
        row = conn.execute(f"SELECT id FROM bookmarks WHERE list_id = ? AND {column} = ?", (list_id, value)).fetchone()
        now, status = common.now_iso(), "active" if on else "removed"
        if row:
            conn.execute("UPDATE bookmarks SET status = ?, updated_at = ? WHERE id = ?", (status, now, row["id"]))
        elif on:
            conn.execute(
                f"INSERT INTO bookmarks (list_id, {column}, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (list_id, value, now, now),
            )
    return {"bookmarked": bool(on)}


def bookmarks(list_id: int) -> list[dict]:
    """My Bookmarks, newest first: each with what it points at."""
    rows = db.get_db().execute(
        "SELECT k.id, k.board_id, k.recording_id, k.card_id, k.created_at, "
        "COALESCE(r.title, c.title, b.name) AS title, r.type AS recording_type, "
        "COALESCE(rb.name, cb.name, b.name) AS board_name, COALESCE(r.board_id, c.board_id, b.id) AS project_id "
        "FROM bookmarks k LEFT JOIN recordings r ON r.id = k.recording_id "
        "LEFT JOIN boards rb ON rb.id = r.board_id LEFT JOIN cards c ON c.id = k.card_id "
        "LEFT JOIN boards cb ON cb.id = c.board_id LEFT JOIN boards b ON b.id = k.board_id "
        "WHERE k.list_id = ? AND k.status = 'active' ORDER BY k.updated_at DESC, k.id DESC",
        (list_id,),
    )
    return [dict(r) for r in rows]


# ── Projects: the dock and the project page ──────────────────────────────────

# A board made before the dock existed (the beta's) keeps its Card Table, and
# nothing else until a tool is added.
_BETA_DOCK = [{"tool": "kanban_board", "enabled": True}]


def dock(board: dict) -> list[dict]:
    """The project's tools in order: its saved dock, then every tool it has not
    saved, switched off (Basecamp 5: a tool is added with the + button)."""
    saved = json.loads(board["dock"]) if board.get("dock") else _BETA_DOCK
    seen, out = set(), []
    for entry in saved:
        if entry.get("tool") in TOOLS and entry["tool"] not in seen:
            seen.add(entry["tool"])
            title = entry.get("title")
            out.append(
                {
                    "tool": entry["tool"],
                    "title": TOOLS[entry["tool"]] if not title or title in _OLD_TITLES else title,
                    "enabled": bool(entry.get("enabled", True)),
                }
            )
    out += [{"tool": t, "title": title, "enabled": False} for t, title in TOOLS.items() if t not in seen]
    return out


def _switch_on(conn, board: dict, tool: str | None) -> None:
    """Turn a tool on when something is added to it (an agent posting a message
    to a project whose Message Board is off), so nothing sits in a hidden tool."""
    if tool is None:
        return
    entries = dock(board)
    if all(e["enabled"] for e in entries if e["tool"] == tool):
        return
    entries = [{**e, "enabled": True} if e["tool"] == tool else e for e in entries]
    conn.execute("UPDATE boards SET dock = ? WHERE id = ?", (json.dumps(entries), board["id"]))


def set_dock(list_id: int, board_ref, entries: list[dict]) -> list[dict]:
    """Save the project's tools: their order, names and which are on."""
    if not isinstance(entries, list) or not entries:
        raise ValidationError("dock must be a list of tools")
    clean = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("tool") not in TOOLS:
            raise ValidationError(f"Each tool is one of {', '.join(TOOLS)}")
        title = common.validate_short(entry.get("title") or TOOLS[entry["tool"]], "title")
        clean.append({"tool": entry["tool"], "title": title, "enabled": bool(entry.get("enabled", True))})
    if len({e["tool"] for e in clean}) != len(clean):
        raise ValidationError("Each tool once")
    with db.transaction() as conn:
        board = _board(conn, list_id, board_ref)
        conn.execute(
            "UPDATE boards SET dock = ?, updated_at = ? WHERE id = ?",
            (json.dumps(clean), common.now_iso(), board["id"]),
        )
    return dock({"dock": json.dumps(clean)})


def project(list_id: int, board_ref) -> dict:
    """A project's page: the project, its dock, and a preview of each tool (the
    latest messages, the to-do lists with progress, the card table's columns)."""
    from backend import boards, project_links

    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    board["dock"] = dock(board)
    board["sample"] = bool(board["sample"])
    previews: dict = {}
    for entry in board["dock"]:
        tool = entry["tool"]
        if not entry["enabled"]:
            continue
        if tool == "message_board":
            previews[tool] = list_items(list_id, board["id"], "message")[:PREVIEW]
        elif tool == "todoset":
            previews[tool] = list_items(list_id, board["id"], "todolist")[: PREVIEW * 2]
            previews["hill"] = hill_chart(list_id, board["id"], updates=0)["lists"]
        elif tool == "vault":
            previews[tool] = folder(list_id, board["id"])["items"][: PREVIEW * 2]
        elif tool == "schedule":
            from backend import schedules

            today = _today(conn, list_id)
            previews[tool] = schedules.calendar(
                list_id, today.isoformat(), (today + datetime.timedelta(days=30)).isoformat(), board_ref=board["id"]
            )
        elif tool == "questionnaire":
            previews[tool] = list_items(list_id, board["id"], "question")[:PREVIEW]
        elif tool == "chat":
            previews[tool] = chat(list_id, board["id"])["lines"][-PREVIEW:]
        elif tool == "doors":
            previews[tool] = list_items(list_id, board["id"], "door")
        elif tool == "kanban_board":
            summary = next((b for b in boards.list_boards(list_id, board["status"]) if b["id"] == board["id"]), None)
            previews[tool] = summary["columns"] if summary else []
    board["previews"] = previews
    who = _people(list_id)
    # What the person put in the Spotlight, and the Needle's latest reading.
    board["spotlight"] = [
        _shape(r, who)
        for r in conn.execute(
            f"{_SELECT} WHERE r.list_id = ? AND r.board_id = ? AND r.status = 'active' "
            "AND json_extract(r.data, '$.spotlight') = 1 ORDER BY r.updated_at DESC",
            (list_id, board["id"]),
        )
    ]
    needle = conn.execute(
        f"{_SELECT} WHERE r.list_id = ? AND r.board_id = ? AND r.type = 'needle' "
        "AND r.status = 'active' ORDER BY r.created_at DESC, r.id DESC LIMIT 1",
        (list_id, board["id"]),
    ).fetchone()
    board["needle"] = _shape(needle, who) if needle else None
    board["bookmarked"] = (
        conn.execute(
            "SELECT 1 FROM bookmarks WHERE list_id = ? AND board_id = ? AND status = 'active'", (list_id, board["id"])
        ).fetchone()
        is not None
    )
    board["people"] = _project_people(conn, list_id, board["id"])
    # The Todo project this one is the home of, when there is one (project_links.py).
    if linked := project_links.todo_project(list_id, board["id"]):
        board["todo_project"] = linked
    return board


def _project_people(conn, list_id: int, board_id: int) -> list[dict]:
    """Who has done anything in the project, most active first."""
    who = _people(list_id)
    return [
        who[r["creator_id"]]
        for r in conn.execute(
            "SELECT creator_id, COUNT(*) AS n FROM events WHERE list_id = ? AND board_id = ? "
            "AND creator_id IS NOT NULL GROUP BY creator_id ORDER BY n DESC LIMIT 12",
            (list_id, board_id),
        )
        if r["creator_id"] in who
    ]


def _me_id(conn, list_id: int) -> int | None:
    row = conn.execute("SELECT id FROM people WHERE list_id = ? AND kind = 'me'", (list_id,)).fetchone()
    return row["id"] if row else None


def assignments(list_id: int, person_id: int | None = None) -> list[dict]:
    """Open to-dos assigned to a person (me by default), soonest due first."""
    conn = db.get_db()
    person_id = person_id or _me_id(conn, list_id)
    if person_id is None:
        return []
    who = _people(list_id)
    return [
        _shape(r, who)
        for r in conn.execute(
            f"{_SELECT} WHERE r.list_id = ? AND {OPEN_TODO} "
            "AND EXISTS (SELECT 1 FROM json_each(r.assignee_ids) WHERE value = ?) "
            "ORDER BY r.due_on IS NULL, r.due_on, r.id",
            (list_id, person_id),
        )
    ]


# An open to-do in a live project whose list and group (if any) are live too (with _SELECT's r and b).
OPEN_TODO = (
    "r.type = 'todo' AND r.status = 'active' AND r.completed_at IS NULL AND b.status = 'active' "
    "AND b.template = 0 "
    "AND (r.parent_id IS NULL OR EXISTS (SELECT 1 FROM recordings p WHERE p.id = r.parent_id "
    " AND p.status = 'active' AND (p.parent_id IS NULL OR EXISTS "
    " (SELECT 1 FROM recordings g WHERE g.id = p.parent_id AND g.status = 'active'))))"
)


def home(list_id: int) -> dict:
    """Home: the projects (pinned first, then the most recently changed), each with
    who has worked in it; the latest activity; and my open assignments."""
    from backend import boards

    conn = db.get_db()
    projects = sorted(boards.list_boards(list_id), key=lambda b: not b["pinned"])
    for board in projects:
        board["people"] = _project_people(conn, list_id, board["id"])
    return {
        "projects": projects,
        "activity": activity(list_id, limit=20)["events"],
        "assignments": assignments(list_id),
    }


# ── Hill Charts, the Needle, and what is put away ────────────────────────────

HILL_UPDATES = 20
STALE_HILL_DAYS = 14


def _hill_lists(conn, list_id: int, board_id: int) -> list[dict]:
    """The project's to-do lists on its Hill Chart, in their order, with their places."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, title, color, json_extract(data, '$.hill') AS hill FROM recordings WHERE list_id = ? "
            "AND board_id = ? AND type = 'todolist' AND status = 'active' AND json_extract(data, '$.hill') IS NOT NULL "
            "ORDER BY position, id",
            (list_id, board_id),
        )
    ]


def hill_chart(list_id: int, board_ref, updates: int = HILL_UPDATES) -> dict:
    """A project's Hill Chart: the to-do lists it tracks, each with its place on
    the hill (0 is the bottom left, 50 the top, 100 done), the latest updates
    (each a snapshot with a note), newest first, and whether nobody has moved it
    in STALE_HILL_DAYS ("It's been a while")."""
    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    who = _people(list_id)
    lists = _hill_lists(conn, list_id, board["id"])
    rows = [
        _shape(r, who)
        for r in conn.execute(
            f"{_SELECT} WHERE r.list_id = ? AND r.board_id = ? AND r.type = 'hill_update' AND r.status = 'active' "
            "ORDER BY r.created_at DESC, r.id DESC LIMIT ?",
            (list_id, board["id"], max(updates, 1)),
        )
    ]
    last = rows[0]["created_at"] if rows else None
    tz = _tz(conn, list_id)
    stale_before = _today(conn, list_id) - datetime.timedelta(days=STALE_HILL_DAYS)
    return {
        "lists": lists,
        "updates": rows[:updates],
        "updated_at": last,
        "stale": bool(lists) and (last is None or common.local_date(last, tz) < stale_before),
    }


def set_hill(
    list_id: int, board_ref, positions: dict, note: str = "", *, source: str = "ui", client: str | None = None
) -> dict:
    """Move to-do lists on the project's Hill Chart and save the chart as an
    update: `positions` maps a list's id to its place (0–100), or to None to stop
    tracking it. Moved by the person only, as Basecamp's: a dot that doesn't move
    is a raised hand."""
    if source == "agent":
        raise ValidationError("The Hill Chart is moved by the person. You can read it.")
    if not isinstance(positions, dict) or not positions or len(positions) > 50:
        raise ValidationError("positions maps 1 to 50 to-do list ids to a place, 0 to 100, or null")
    note = common.validate_notes(note or "", "note")
    with db.transaction() as conn:
        board = _board(conn, list_id, board_ref)
        if board["status"] != "active":
            raise ValidationError("This project is archived. Restore it first.")
        for key, place in positions.items():
            if not (str(key).isascii() and str(key).isdigit()):
                raise ValidationError("positions maps to-do list ids to places")
            rec_id = int(key)
            row = conn.execute(
                "SELECT type, board_id, status FROM recordings WHERE id = ? AND list_id = ?", (rec_id, list_id)
            ).fetchone()
            if row is None or row["type"] != "todolist" or row["board_id"] != board["id"] or row["status"] != "active":
                raise NotFoundError(f"No to-do list {rec_id} in this project")
            if place is not None and not (isinstance(place, (int, float)) and 0 <= place <= 100):
                raise ValidationError("A place on the hill is 0 to 100")
            _apply_data(conn, rec_id, {"data_hill": None if place is None else round(place, 1)})
            _write(conn, rec_id, {})
        _check_cap(conn, list_id)
        actor = people.actor_in(conn, list_id, client, source)
        snapshot = _hill_lists(conn, list_id, board["id"])
        now = common.now_iso()
        rec_id = conn.execute(
            "INSERT INTO recordings (list_id, board_id, type, body, data, creator_id, source, source_client, "
            "created_at, updated_at) VALUES (?, ?, 'hill_update', ?, ?, ?, ?, ?, ?, ?)",
            (
                list_id,
                board["id"],
                note,
                json.dumps({"lists": snapshot}),
                actor,
                source,
                common.clean_source_client(client),
                now,
                now,
            ),
        ).lastrowid
        event_in(conn, list_id, board["id"], "created", actor, rec_id=rec_id)
        _touch_board(conn, board["id"])
    return hill_chart(list_id, board["id"])


def needles(list_id: int, board_ref) -> list[dict]:
    """The Needle's history in a project, newest first."""
    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    who = _people(list_id)
    return [
        _shape(r, who)
        for r in conn.execute(
            f"{_SELECT} WHERE r.list_id = ? AND r.board_id = ? AND r.type = 'needle' AND r.status = 'active' "
            "ORDER BY r.created_at DESC, r.id DESC LIMIT 100",
            (list_id, board["id"]),
        )
    ]


def put_away(list_id: int, board_ref) -> dict:
    """A project's archived and trashed things (Basecamp's "Archived …" and the
    trash, which here never empties), newest change first; archived cards too.
    Restore brings each back where it was."""
    from backend import boards

    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    who = _people(list_id)
    out: dict = {}
    for status in ("archived", "trashed"):
        out[status] = [
            _shape(r, who)
            for r in conn.execute(
                f"{_SELECT} WHERE r.list_id = ? AND r.board_id = ? AND r.status = ? "
                "AND r.type NOT IN ('needle', 'hill_update') ORDER BY r.updated_at DESC, r.id DESC LIMIT 500",
                (list_id, board["id"], status),
            )
        ]
    out["cards"] = boards._shape_cards(
        conn,
        list_id,
        conn.execute(
            f"{boards._CARD} WHERE c.list_id = ? AND c.board_id = ? AND c.status = 'archived' "
            "ORDER BY c.updated_at DESC, c.id DESC LIMIT 500",
            (list_id, board["id"]),
        ),
    )
    return out


# ── Copies, and drafts that post themselves ──────────────────────────────────

# What a copy leaves behind: where the original sits on the project page and the hill.
_NOT_COPIED = ("pinned_at", "pin", "spotlight", "hill", "post_at")
# Kept out of a copy's subtree: the conversation stays with the original.
_SUBTREE_SKIP = ("comment", "answer", "needle", "hill_update")


def _copy_in(
    conn,
    list_id: int,
    row: dict,
    board_id: int,
    parent_id,
    actor,
    source: str,
    client: str | None,
    *,
    reset: bool = False,
    shift: int = 0,
    position=None,
    only: set | None = None,
) -> int:
    """Copy one recording and what is under it (a list's groups, to-dos and their
    subtasks, a folder's contents) into `board_id` under `parent_id`; never its
    comments or answers. `reset` re-opens what was completed; `shift` moves every
    date that many days. Returns the new id."""

    def moved(day):
        return (datetime.date.fromisoformat(day) + datetime.timedelta(days=shift)).isoformat() if day and shift else day

    # `only`: the ids under the original, read before anything was copied, so a folder
    # copied into itself (or into a folder inside it) copies what was there, once.
    kids = conn.execute(
        "SELECT * FROM recordings WHERE parent_id = ? AND list_id = ? AND status = 'active' "
        f"AND type NOT IN ({', '.join('?' * len(_SUBTREE_SKIP))}) ORDER BY position, id",
        (row["id"], list_id, *_SUBTREE_SKIP),
    ).fetchall()
    data = {k: v for k, v in json.loads(row["data"] or "{}").items() if k not in _NOT_COPIED}
    if data.get("repeat_until") and shift:
        data["repeat_until"] = moved(data["repeat_until"])
    now = common.now_iso()
    siblings = _sibling_ids(conn, list_id, board_id, row["type"], parent_id, None)
    new = {
        "list_id": list_id,
        "board_id": board_id,
        "parent_id": parent_id,
        "card_id": None,
        "type": row["type"],
        "title": row["title"],
        "body": row["body"],
        "status": "drafted" if row["status"] == "drafted" else "active",
        "position": len(siblings),
        "category": row["category"],
        "color": row["color"],
        "starts_on": moved(row["starts_on"]),
        "due_on": moved(row["due_on"]),
        "completed_at": None if reset else row["completed_at"],
        "completer_id": None if reset else row["completer_id"],
        "assignee_ids": row["assignee_ids"],
        "data": json.dumps(data),
        "creator_id": actor,
        "source": source,
        "source_client": common.clean_source_client(client),
        "created_at": now,
        "updated_at": now,
    }
    new_id = conn.execute(
        f"INSERT INTO recordings ({', '.join(new)}) VALUES ({', '.join('?' * len(new))})", tuple(new.values())
    ).lastrowid
    _renumber(conn, _place(siblings + [new_id], new_id, position))
    for kid in kids:
        if only is None or kid["id"] in only:
            _copy_in(
                conn, list_id, dict(kid), board_id, new_id, actor, source, client, reset=reset, shift=shift, only=only
            )
    return new_id


def _subtree(conn, list_id: int, rec_id: int) -> set:
    """The ids a copy of `rec_id` copies: it and what is under it."""
    return {
        r[0]
        for r in conn.execute(
            "WITH RECURSIVE t(id) AS (SELECT ? UNION SELECT r.id FROM recordings r JOIN t ON r.parent_id = t.id "
            "WHERE r.list_id = ? AND r.status = 'active' "
            f"AND r.type NOT IN ({', '.join('?' * len(_SUBTREE_SKIP))})) SELECT id FROM t",
            (rec_id, list_id, *_SUBTREE_SKIP),
        )
    }


def copy(
    list_id: int,
    rec_id: int,
    *,
    board=None,
    parent_id: int | None = None,
    source: str = "ui",
    client: str | None = None,
) -> dict:
    """Copy a message, document, link, folder, event, check-in question, to-do list,
    group or to-do (with what is under it) into a project (by id or name: the top
    of its tool) or under a parent there; to the same place by default. Basecamp's
    Copy: the comments stay with the original."""
    with db.transaction() as conn:
        row = dict(_get_row(conn, list_id, rec_id))
        if row["type"] in _SUBTREE_SKIP or row["type"] in ("step", "wormhole") or row["card_id"] is not None:
            raise ValidationError(f"A {TYPES[row['type']].label.lower()} can't be copied")
        if row["status"] == "trashed":
            raise ValidationError("This is in the trash. Restore it first.")
        if parent_id is not None:
            board_id, _ = _parent(conn, list_id, row["type"], parent_id, None)
        elif board not in (None, ""):
            target = _board(conn, list_id, board)
            if None not in TYPES[row["type"]].parents:
                raise ValidationError(f"Copy a {TYPES[row['type']].label.lower()} under a parent instead")
            board_id = target["id"]
        else:
            board_id, parent_id = row["board_id"], row["parent_id"]
        assert board_id is not None  # Copies exclude card steps; their parent is in a project.
        target = _board(conn, list_id, board_id)
        if target["status"] != "active":
            raise ValidationError("That project is archived. Restore it first.")
        subtree = _subtree(conn, list_id, rec_id)
        _check_cap(conn, list_id, adding=len(subtree))
        _switch_on(conn, target, TYPES[row["type"]].tool)
        actor = people.actor_in(conn, list_id, client, source)
        new_id = _copy_in(conn, list_id, row, board_id, parent_id, actor, source, client, only=subtree)
        event_in(conn, list_id, board_id, "copied", actor, rec_id=new_id, detail=row["board_name"])
        _touch_board(conn, board_id)
    return get(list_id, new_id)


def publish_scheduled(now: datetime.datetime | None = None) -> int:
    """Post every drafted message whose post_at has come, in every account, as
    its writer would have: the background loop runs this each minute."""
    now_iso = common.to_iso(now or common.utcnow())
    due = (
        db.get_db()
        .execute(
            "SELECT id, list_id FROM recordings WHERE type = 'message' AND status = 'drafted' "
            "AND json_extract(data, '$.post_at') IS NOT NULL AND json_extract(data, '$.post_at') <= ?",
            (now_iso,),
        )
        .fetchall()
    )
    posted = 0
    for rec in due:
        with db.transaction() as conn:
            # Read again under the lock: it may have been posted, cancelled or put off since.
            row = conn.execute(
                "SELECT * FROM recordings WHERE id = ? AND list_id = ? AND status = 'drafted' "
                "AND json_extract(data, '$.post_at') IS NOT NULL AND json_extract(data, '$.post_at') <= ?",
                (rec["id"], rec["list_id"], now_iso),
            ).fetchone()
            if row is None:
                continue
            board = conn.execute("SELECT status FROM boards WHERE id = ?", (row["board_id"],)).fetchone()
            if board is None or board["status"] != "active":
                continue  # posts when its project comes back
            _apply_data(conn, row["id"], {"data_post_at": None})
            _write(conn, row["id"], {"status": "active"})
            event_in(conn, rec["list_id"], row["board_id"], "posted", row["creator_id"], rec_id=row["id"])
            _touch_board(conn, row["board_id"])
            posted += 1
    return posted


# ── Chat ──────────────────────────────────────────────────────────────────────

CHAT_PAGE = 50


def chat(list_id: int, board_ref, *, since: int | None = None, before: int | None = None) -> dict:
    """A project's chat, oldest first: the latest CHAT_PAGE lines, or those after
    `since` (what a page that is open polls for), or the page before `before`.
    `latest` is the cursor for the next poll."""
    for name, cursor in (("since", since), ("before", before)):
        if cursor is not None and not (isinstance(cursor, int) and 0 <= cursor <= 2**62):
            raise ValidationError(f"{name} must be a line id")
    conn = db.get_db()
    board = _board(conn, list_id, board_ref)
    who = _people(list_id)
    where, args = (
        "r.list_id = ? AND r.board_id = ? AND r.type = 'chat_line' AND r.status = 'active'",
        [list_id, board["id"]],
    )
    if since is not None:
        rows = conn.execute(
            f"{_SELECT} WHERE {where} AND r.id > ? ORDER BY r.id LIMIT ?", (*args, since, CHAT_PAGE * 4)
        ).fetchall()
    else:
        cursor = " AND r.id < ?" if before is not None else ""
        rows = list(
            reversed(
                conn.execute(
                    f"{_SELECT} WHERE {where}{cursor} ORDER BY r.id DESC LIMIT ?",
                    (*args, *([before] if before is not None else []), CHAT_PAGE),
                ).fetchall()
            )
        )
    lines = [_shape(r, who) for r in rows]
    boosts = _boosts(list_id, rec_ids=[x["id"] for x in lines])
    for x in lines:
        x["boosts"] = boosts.get(("r", x["id"]), [])
    # The cursor is the last line handed over, never a newer one read apart from them: a
    # poll carries on from exactly there, skipping none (more waiting, or a line just added).
    latest = lines[-1]["id"] if lines else (since or 0)
    return {
        "lines": lines,
        "latest": latest,
        "earlier": bool(lines)
        and since is None
        and conn.execute(f"SELECT 1 FROM recordings r WHERE {where} AND r.id < ?", (*args, lines[0]["id"])).fetchone()
        is not None,
    }


# ── Mentions and shifting dates ───────────────────────────────────────────────

# When the mentions were made: on an edit that added someone, then; else when it was written.
_MENTIONED_AT = "COALESCE(json_extract(r.data, '$.mentioned_at'), r.created_at)"


def mentions_of(list_id: int, person_id: int | None = None, days: int = 14, limit: int = 20) -> list[dict]:
    """What @mentioned a person (me by default) lately, newest first: where it is and what it says."""
    conn = db.get_db()
    person_id = person_id or _me_id(conn, list_id)
    since = common.to_iso(common.utcnow() - datetime.timedelta(days=days))
    who = _people(list_id)
    out = []
    for row in conn.execute(
        f"{_SELECT} WHERE r.list_id = ? AND r.status = 'active' AND b.status = 'active' AND {_MENTIONED_AT} >= ? "
        "AND EXISTS (SELECT 1 FROM json_each(r.data, '$.mentions') WHERE value = ?) "
        f"ORDER BY {_MENTIONED_AT} DESC, r.id DESC LIMIT ?",
        (list_id, since, person_id, limit),
    ):
        item = _shape(row, who)
        out.append(
            {
                "id": item["id"],
                "type": item["type"],
                "board_id": item["board_id"],
                "board_name": item["board_name"],
                "parent_id": item["parent_id"],
                "card_id": item["card_id"],
                "excerpt": _excerpt(item["body"]),
                "creator": item["creator"],
                "created_at": item.get("mentioned_at") or item["created_at"],
            }
        )
    return out


def shift_dates(list_id: int, rec_id: int, days: int, *, source: str = "ui", client: str | None = None) -> dict:
    """Basecamp's "Change dates": move every date of a to-do list's (or group's)
    open to-dos and their subtasks by `days`, earlier or later."""
    if not isinstance(days, int) or isinstance(days, bool) or not -3650 <= days <= 3650 or days == 0:
        raise ValidationError("days must be a whole number of days, not 0, at most ten years either way")
    with db.transaction() as conn:
        row = dict(_get_row(conn, list_id, rec_id))
        if row["type"] not in ("todolist", "todolist_group"):
            raise ValidationError("Shift the dates of a to-do list or a group")
        _check_live(conn, list_id, row)
        ids = [
            r[0]
            for r in conn.execute(
                "WITH RECURSIVE t(id) AS (SELECT ? UNION SELECT r.id FROM recordings r JOIN t ON r.parent_id = t.id "
                "WHERE r.list_id = ? AND r.status = 'active') "
                "SELECT r.id FROM recordings r JOIN t ON t.id = r.id WHERE r.type IN ('todo', 'step') "
                "AND r.completed_at IS NULL AND (r.due_on IS NOT NULL OR r.starts_on IS NOT NULL)",
                (rec_id, list_id),
            )
        ]
        delta = datetime.timedelta(days=days)
        try:
            for item_id in ids:
                cur = conn.execute(
                    "SELECT starts_on, due_on FROM recordings WHERE id = ? AND list_id = ?", (item_id, list_id)
                ).fetchone()
                _write(
                    conn,
                    item_id,
                    {
                        k: (datetime.date.fromisoformat(cur[k]) + delta).isoformat()
                        for k in ("starts_on", "due_on")
                        if cur[k]
                    },
                )
        except (OverflowError, ValueError):
            raise ValidationError("That would move a date out of range") from None
        actor = people.actor_in(conn, list_id, client, source)
        event_in(
            conn,
            list_id,
            row["board_id"],
            "edited",
            actor,
            rec_id=rec_id,
            detail=f"moved {len(ids)} date{'s' if len(ids) != 1 else ''} {days:+d} day{'s' if abs(days) != 1 else ''}",
        )
        _touch_board(conn, row["board_id"])
    return {"shifted": len(ids), "item": get(list_id, rec_id)}


# ── Markdown import ───────────────────────────────────────────────────────────

_MD_HEADING = re.compile(r"^#{1,6}\s+(.+)$")
_MD_LINE = re.compile(r"^(?:[-*+•]|\d+[.)])?\s*(?:\[([ xX])\])?\s*(.*)$")


def import_todos(
    list_id: int, board_ref, text, *, parent_id: int | None = None, source: str = "ui", client: str | None = None
) -> dict:
    """Basecamp's Markdown import onto To-dos: a heading starts a to-do list (a group,
    inside a list), each other line is a to-do, an indented one a subtask of the
    to-do above it, and "[x]" marks one done. At most MAX_IMPORT lines."""
    text = common.validate_notes(text, "markdown")
    plan = []  # (kind, title, done)
    for raw in text.splitlines():
        line = raw.expandtabs(4)
        m = _MD_HEADING.match(line.strip())
        if m:  # its closing hashes dropped ("## Plan ##"), not a title's own ("C#")
            title = re.sub(r"(^|\s+)#+\s*$", "", m[1]).strip()[: common.MAX_SHORT_CHARS]
            if title:
                plan.append(("heading", title, False))
            continue
        m = _MD_LINE.match(line.strip())
        assert m is not None  # Every part of the prefix is optional; (.*) matches the rest.
        if m[2].strip():
            indented = len(line) - len(line.lstrip()) >= 2
            plan.append(("step" if indented else "todo", m[2].strip()[: common.MAX_SHORT_CHARS], m[1] in ("x", "X")))
    if not any(kind != "heading" for kind, _, _ in plan):
        raise ValidationError("Nothing to import: write one to-do on each line")
    if len(plan) > MAX_IMPORT:
        raise ValidationError(f"At most {MAX_IMPORT} lines in one import")
    with db.transaction() as conn:
        parent = None
        if parent_id is not None:
            parent = dict(_get_row(conn, list_id, parent_id))
            if parent["type"] not in ("todolist", "todolist_group"):
                raise ValidationError("Import into a to-do list or a group")
            _check_live(conn, list_id, parent)
            board_ref = parent["board_id"]
        _check_cap(conn, list_id, adding=len(plan))
    # simplification: one create per line, each in its own transaction, so a write that
    # races the import can stop it at the cap partway, keeping what was added; an
    # import inside one transaction is the way up.
    made = {"lists": 0, "groups": 0, "todos": 0, "subtasks": 0, "completed": 0}
    who = {"source": source, "client": client}
    container, last = parent_id, None
    for kind, title, done in plan:
        if kind == "heading" and (parent is None or parent["type"] == "todolist"):
            sub = "todolist" if parent is None else "todolist_group"
            container = create(list_id, board_ref, sub, {"title": title}, parent_id=parent_id, **who)["id"]
            made["lists" if parent is None else "groups"] += 1
            last = None
            continue
        if kind == "step" and last is not None:
            rec = create(list_id, board_ref, "step", {"title": title}, parent_id=last, **who)
            made["subtasks"] += 1
        else:  # a to-do; a heading inside a group is one too
            rec = create(list_id, board_ref, "todo", {"title": title}, parent_id=container, **who)
            made["todos"] += 1
            last = rec["id"]
        if done:
            complete(list_id, rec["id"], **who)
            made["completed"] += 1
    return made
