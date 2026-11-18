"""Projects GTD — the views across every project: Everything (key 4), Reports
(key 3: overdue, upcoming, unassigned, added and completed, someone's tasks,
Mission Control, the Hilltop View) and search.

Basecamp's are account-wide; here they are the one account's. Like
schedules.py, which they build on for what is due, everything is list-scoped
and nothing here writes.
"""

import datetime
import re

from backend import boards, common, db, recordings, schedules
from backend.common import ValidationError

PAGE = 50
# Overdue work grouped as Basecamp's API groups it: the most days late in each.
LATE = (
    ("Under a week late", 6),
    ("A week to a month late", 29),
    ("One to three months late", 89),
    ("Over three months late", None),
)
QUIET_DAYS = 14  # a project with no activity this long is "gone quiet" in Mission Control
MAX_QUERY = 200
CANDIDATES = 200  # rows search reads from each table before ranking
MAX_TERMS = 8

# Everything's tabs: the recording types each lists (tasks add the cards).
EVERYTHING = {
    "messages": ("message",),
    "docs": ("vault", "document", "link"),
    "tasks": ("todo",),
    "comments": ("comment",),
    "checkins": ("answer",),
}
# What search can be narrowed to: a recording type, or 'card'.
SEARCH_KINDS = (
    "message",
    "document",
    "link",
    "vault",
    "todolist",
    "todo",
    "comment",
    "schedule_entry",
    "question",
    "answer",
    "card",
)


def _today(list_id: int) -> datetime.date:
    return recordings._today(db.get_db(), list_id)


def _brief(row, who: dict) -> dict:
    """A recording as a report line: what it is, where, who, when."""
    item = recordings._shape(row, who)
    return {
        k: item.get(k)
        for k in (
            "id",
            "type",
            "title",
            "body",
            "board_id",
            "board_name",
            "parent_id",
            "card_id",
            "status",
            "due_on",
            "starts_on",
            "assignees",
            "creator",
            "completer",
            "completed_at",
            "created_at",
            "comments_count",
        )
    }


# ── Everything ────────────────────────────────────────────────────────────────


def everything(list_id: int, kind: str, *, before: str | None = None, subtasks: bool = False) -> dict:
    """Everything of one kind in every live project, newest first, a page at a
    time: `before` is the last page's next_before (a created_at)."""
    if kind not in EVERYTHING:
        raise ValidationError(f"kind must be one of {', '.join(EVERYTHING)}")
    types = EVERYTHING[kind] + (("step",) if kind == "tasks" and subtasks else ())
    conn = db.get_db()
    who = recordings._people(list_id)
    marks = ",".join("?" * len(types))
    cursor = " AND r.created_at < ?" if before else ""
    rows = conn.execute(
        f"{recordings._SELECT} WHERE r.list_id = ? AND r.type IN ({marks}) AND r.status = 'active' "
        f"AND b.status = 'active' AND b.template = 0{cursor} ORDER BY r.created_at DESC, r.id DESC LIMIT ?",
        (list_id, *types, *([before] if before else []), PAGE + 1),
    ).fetchall()
    items = [_brief(r, who) for r in rows]
    if kind == "tasks":
        cards = boards._shape_cards(
            conn,
            list_id,
            conn.execute(
                f"{boards._CARD} WHERE c.list_id = ? AND c.status = 'active' AND b.status = 'active' AND b.template = 0"
                f"{cursor.replace('r.', 'c.')} "
                "ORDER BY c.created_at DESC, c.id DESC LIMIT ?",
                (list_id, *([before] if before else []), PAGE + 1),
            ),
        )
        items += [{**c, "type": "card"} for c in cards]
        items.sort(key=lambda i: (i["created_at"], i["id"]), reverse=True)
    if kind in ("comments", "checkins"):
        _what_on(conn, list_id, items)
    page = items[:PAGE]
    # simplification: the cursor is a created_at, so two things made in the same
    # millisecond across a page edge can skip one; an (at, kind, id) cursor fixes it.
    return {"kind": kind, "items": page, "next_before": page[-1]["created_at"] if len(items) > PAGE else None}


def _what_on(conn, list_id: int, comments: list[dict]) -> None:
    """Name what each comment (or answer) is on: its recording's title, or its card's."""
    recs = (
        {
            r["id"]: r
            for r in conn.execute(
                f"SELECT id, type, title FROM recordings WHERE list_id = ? AND id IN ({','.join('?' * len(comments))})",
                (list_id, *[c["parent_id"] or 0 for c in comments]),
            )
        }
        if comments
        else {}
    )
    cards = (
        {
            r["id"]: r["title"]
            for r in conn.execute(
                f"SELECT id, title FROM cards WHERE list_id = ? AND id IN ({','.join('?' * len(comments))})",
                (list_id, *[c["card_id"] or 0 for c in comments]),
            )
        }
        if comments
        else {}
    )
    for c in comments:
        on = recs.get(c["parent_id"])
        c["on_title"] = on["title"] if on else cards.get(c["card_id"], "")
        c["on_type"] = on["type"] if on else ("card" if c["card_id"] else None)


# ── Reports ───────────────────────────────────────────────────────────────────


def overdue(list_id: int) -> dict:
    """Open to-dos, subtasks and cards past their due date, in Basecamp's four
    groups by how late they are, the latest first within each."""
    today = _today(list_id)
    conn = db.get_db()
    late = schedules._due(
        conn, list_id, recordings._people(list_id), "0001-01-01", (today - datetime.timedelta(days=1)).isoformat(), None
    )
    groups = [{"label": label, "items": []} for label, _ in LATE]
    for item in sorted(late, key=lambda x: x["on"], reverse=True):
        days = (today - datetime.date.fromisoformat(item["on"])).days
        item["days_late"] = days
        n = next(i for i, (_, most) in enumerate(LATE) if most is None or days <= most)
        groups[n]["items"].append(item)
    return {"today": today.isoformat(), "groups": groups, "count": len(late)}


def upcoming(list_id: int, days: int = 14) -> dict:
    """Open to-dos, subtasks and cards due from today through the next `days`."""
    if not 1 <= days <= 90:
        raise ValidationError("days must be 1 to 90")
    today = _today(list_id)
    items = schedules._due(
        db.get_db(),
        list_id,
        recordings._people(list_id),
        today.isoformat(),
        (today + datetime.timedelta(days=days)).isoformat(),
        None,
    )
    return {"today": today.isoformat(), "items": items}


def unassigned(list_id: int) -> dict:
    """Open to-dos and cards (not in Done) that nobody is assigned to, by project."""
    conn = db.get_db()
    who = recordings._people(list_id)
    todos = [
        _brief(r, who)
        for r in conn.execute(
            f"{recordings._SELECT} WHERE r.list_id = ? AND {recordings.OPEN_TODO} AND r.assignee_ids = '[]' "
            "ORDER BY b.name, r.due_on IS NULL, r.due_on, r.id",
            (list_id,),
        )
    ]
    cards = boards._shape_cards(
        conn,
        list_id,
        conn.execute(
            f"{boards._CARD} WHERE c.list_id = ? AND c.status = 'active' AND c.completed_at IS NULL "
            "AND b.status = 'active' AND b.template = 0 AND c.assignee_ids = '[]' "
            "ORDER BY b.name, c.due_date IS NULL, c.due_date, c.id",
            (list_id,),
        ),
    )
    return {"todos": todos, "cards": cards}


def progress(list_id: int, start: str, end: str) -> dict:
    """To-dos and cards added, and completed, from start to end (inclusive dates
    in the account's time zone, as the app shows them), newest first."""
    first, last = schedules._date(start, "start"), schedules._date(end, "end")
    if last < first or (last - first).days > schedules.MAX_RANGE_DAYS:
        raise ValidationError(f"Ask for a range of 0 to {schedules.MAX_RANGE_DAYS} days")
    # simplification: compared as UTC timestamps, so a late-evening entry can fall a
    # day off in a far-from-UTC zone; converting each stamp to the list's zone fixes it.
    lo, hi = first.isoformat(), (last + datetime.timedelta(days=1)).isoformat()
    conn = db.get_db()
    who = recordings._people(list_id)
    out = {}
    for name, column in (("added", "created_at"), ("completed", "completed_at")):
        todos = [
            _brief(r, who)
            for r in conn.execute(
                f"{recordings._SELECT} WHERE r.list_id = ? AND r.type = 'todo' AND r.status = 'active' AND b.template = 0 "
                f"AND r.{column} >= ? AND r.{column} < ? ORDER BY r.{column} DESC LIMIT 500",
                (list_id, lo, hi),
            )
        ]
        cards = [
            {**c, "type": "card"}
            for c in boards._shape_cards(
                conn,
                list_id,
                conn.execute(
                    f"{boards._CARD} WHERE c.list_id = ? AND c.status = 'active' AND b.template = 0 "
                    f"AND c.{column} >= ? AND c.{column} < ? "
                    f"ORDER BY c.{column} DESC LIMIT 500",
                    (list_id, lo, hi),
                ),
            )
        ]
        out[name] = sorted(todos + cards, key=lambda i: i[column] or "", reverse=True)
    return {"start": first.isoformat(), "end": last.isoformat(), **out}


def person_tasks(list_id: int, person_id: int) -> dict:
    """Someone's tasks: the open to-dos and cards assigned to one person (an AI
    tool too), soonest due first."""
    person = next((p for p in recordings._people(list_id).values() if p["id"] == person_id), None)
    if person is None:
        raise ValidationError(f"No such person: {person_id}")
    return {
        "person": person,
        "todos": recordings.assignments(list_id, person_id),
        "cards": boards.assigned_cards(list_id, person_id),
    }


def mission_control(list_id: int) -> dict:
    """Every live project with its latest Needle and when anything last happened
    in it; a project nothing has touched in QUIET_DAYS has gone quiet."""
    conn = db.get_db()
    today = _today(list_id)
    who = recordings._people(list_id)
    needles = {}
    for row in conn.execute(
        f"{recordings._SELECT} WHERE r.list_id = ? AND r.type = 'needle' AND r.status = 'active' "
        "ORDER BY r.created_at, r.id",
        (list_id,),
    ):
        needles[row["board_id"]] = recordings._shape(row, who)  # the latest wins
    last = {
        r["board_id"]: r["at"]
        for r in conn.execute(
            "SELECT board_id, MAX(created_at) AS at FROM events WHERE list_id = ? GROUP BY board_id", (list_id,)
        )
    }
    tz = recordings._tz(conn, list_id)
    quiet_before = today - datetime.timedelta(days=QUIET_DAYS)
    projects = []
    for board in (b for b in boards.list_boards(list_id) if not b["template"]):
        at = last.get(board["id"])
        projects.append(
            {
                "id": board["id"],
                "name": board["name"],
                "pinned": board["pinned"],
                "needle": needles.get(board["id"]),
                "last_activity_at": at,
                "quiet": not at or common.local_date(at, tz) < quiet_before,
            }
        )
    return {"projects": projects}


def hilltop(list_id: int) -> dict:
    """The Hilltop View: every live project's Hill Chart (the to-do lists it
    tracks and where each sits), and whether it has gone stale."""
    projects = []
    for board in (b for b in boards.list_boards(list_id) if not b["template"]):
        chart = recordings.hill_chart(list_id, board["id"], updates=1)
        if chart["lists"]:
            projects.append({"id": board["id"], "name": board["name"], **chart})
    return {"projects": projects}


# ── Search ────────────────────────────────────────────────────────────────────


def _like(term: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", term) + "%"


def _snippet(text: str, terms: list[str], n: int = 160) -> str:
    """The stretch of `text` around the first term found, on one line."""
    flat = " ".join((text or "").split())
    at = min((i for i in (flat.lower().find(t.lower()) for t in terms) if i >= 0), default=0)
    start = max(0, at - n // 3)
    return ("…" if start else "") + flat[start : start + n] + ("…" if start + n < len(flat) else "")


def _title_rank(column: str, terms: list[str], sort: str) -> tuple[str, list]:
    """For best match, an ORDER BY prefix putting rows whose title holds every term first."""
    if sort != "best":
        return "", []
    every = " AND ".join(f"{column} LIKE ? ESCAPE '\\'" for _ in terms)
    return f"CASE WHEN {every} THEN 0 ELSE 1 END, ", [_like(t) for t in terms]


def search(
    list_id: int,
    q: str,
    *,
    kind: str | None = None,
    board_id: int | None = None,
    person_id: int | None = None,
    since: str | None = None,
    sort: str = "best",
) -> dict:
    """Find text in every project, archived ones and archived items too (not the
    trash, not drafts): every word must appear in the title or the body. Narrow by
    kind, project, who wrote it and since a date; `best` puts title matches
    first, then the newest; `recent` is newest first."""
    terms = (q or "").split()[:MAX_TERMS]
    if not terms or len(q) > MAX_QUERY:
        raise ValidationError(f"Search for some words (at most {MAX_QUERY} characters)")
    if kind not in (None, "", *SEARCH_KINDS):
        raise ValidationError(f"kind must be one of {', '.join(SEARCH_KINDS)}")
    if sort not in ("best", "recent"):
        raise ValidationError("sort must be best or recent")
    if since:
        since = schedules._date(since, "since").isoformat()
    conn = db.get_db()
    who = recordings._people(list_id)
    results: list[dict] = []
    if kind != "card":
        where = ["r.list_id = ?", "r.status IN ('active', 'archived')", "r.type NOT IN ('needle', 'hill_update')"]
        args: list = [list_id]
        for t in terms:
            where.append("(r.title LIKE ? ESCAPE '\\' OR r.body LIKE ? ESCAPE '\\')")
            args += [_like(t), _like(t)]
        for cond, value in (
            ("r.type = ?", kind or None),
            ("r.board_id = ?", board_id),
            ("r.creator_id = ?", person_id),
            ("r.created_at >= ?", since),
        ):
            if value is not None:
                where.append(cond)
                args.append(value)
        # Best match ranks title matches first before the cap, so none is cut for newer text matches.
        rank, rank_args = _title_rank("r.title", terms, sort)
        for row in conn.execute(
            f"{recordings._SELECT} WHERE {' AND '.join(where)} ORDER BY {rank}r.created_at DESC LIMIT ?",
            [*args, *rank_args, CANDIDATES],
        ):
            results.append(_brief(row, who))
    if kind in (None, "", "card") and person_id is None:
        where = ["c.list_id = ?", "c.status IN ('active', 'archived')"]
        args = [list_id]
        for t in terms:
            where.append("(c.title LIKE ? ESCAPE '\\' OR c.notes LIKE ? ESCAPE '\\')")
            args += [_like(t), _like(t)]
        for cond, value in (("c.board_id = ?", board_id), ("c.created_at >= ?", since)):
            if value is not None:
                where.append(cond)
                args.append(value)
        rank, rank_args = _title_rank("c.title", terms, sort)
        for card in boards._shape_cards(
            conn,
            list_id,
            conn.execute(
                f"{boards._CARD} WHERE {' AND '.join(where)} ORDER BY {rank}c.created_at DESC LIMIT ?",
                [*args, *rank_args, CANDIDATES],
            ),
        ):
            results.append(
                {
                    "id": card["id"],
                    "type": "card",
                    "title": card["title"],
                    "body": card["notes"],
                    "board_id": card["board_id"],
                    "board_name": card["board_name"],
                    "parent_id": None,
                    "card_id": card["id"],
                    "status": card["status"],
                    "creator": None,
                    "created_at": card["created_at"],
                    "column_name": card["column_name"],
                }
            )
    # A comment or an answer has no title: it is named for what it is on.
    talk = [r for r in results if r["type"] in ("comment", "answer")]
    _what_on(conn, list_id, talk)
    for r in talk:
        r["title"] = r["title"] or (f"Re: {r['on_title']}" if r["on_title"] else "")
    for r in results:
        r["snippet"] = _snippet(r.pop("body", "") or "", terms)
        r["title_match"] = all(t.lower() in (r["title"] or "").lower() for t in terms)
    results.sort(key=lambda r: r["created_at"], reverse=True)
    if sort == "best":
        results.sort(key=lambda r: not r["title_match"])  # stable: newest first within each
    return {"q": q, "results": results[:PAGE], "count": len(results)}
