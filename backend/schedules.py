"""Projects GTD — Calendar, Automatic Check-ins and the Lineup, read side.

Events (recordings of type 'schedule_entry') keep their first day in starts_on,
their last in due_on and a repeat rule in data; every occurrence is worked out
when a range is read, never stored, as Basecamp's per-date occurrences are. A
calendar can also show what is due: open to-dos, cards and subtasks with dates.

A check-in question (type 'question') is asked on its schedule to its people
(assignee_ids); it is due for someone on a scheduled day they have not answered.
The Lineup is the projects with dates, as bars across the weeks.

Everything is list-scoped; nothing here writes.
"""

import calendar as _calendar
import datetime
from typing import cast

from backend import boards, common, db, recordings
from backend.common import ValidationError

MAX_RANGE_DAYS = 400
MAX_OCCURRENCES = 2_000


def _date(value: str, field: str) -> datetime.date:
    text = common.validate_due(value, field)
    if text is None:
        raise ValidationError(f"{field} is required (YYYY-MM-DD)")
    return datetime.date.fromisoformat(text)


def _add_months(day: datetime.date, months: int) -> datetime.date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, _calendar.monthrange(year, month)[1]))


def occurrences(
    first: datetime.date, repeat: str | None, until: datetime.date | None, start: datetime.date, end: datetime.date
) -> list[datetime.date]:
    """The days an event that first happens on `first` happens on, from start to
    end (inclusive), under its repeat rule (recordings.REPEATS) and until date."""
    if not repeat:
        return [first] if start <= first <= end else []
    out: list[datetime.date] = []
    last = min(end, until) if until else end
    step_days = {"every_day": 1, "every_weekday": 1, "every_week": 7, "every_other_week": 14}.get(repeat)
    step_months = {"every_month": 1, "every_year": 12}.get(repeat)
    if step_days is None and step_months is None:
        return []
    # A supported repeat has a month interval whenever it has no day interval.
    # Start at the first occurrence that can reach the range, not at `first`: an
    # event that began long ago costs no more to read than a new one.
    if start <= first:
        n = 0
    elif step_days:
        n = (start - first).days // step_days
    else:
        n = max(0, ((start.year - first.year) * 12 + start.month - first.month) // cast(int, step_months) - 1)
    while len(out) < MAX_OCCURRENCES:
        try:
            day = (
                first + datetime.timedelta(days=step_days * n)
                if step_days
                else _add_months(first, cast(int, step_months) * n)
            )
        except (OverflowError, ValueError):
            break  # past the year 9999
        if day > last:
            break
        if day >= start and not (repeat == "every_weekday" and day.weekday() >= 5):
            out.append(day)
        n += 1
    return out


def calendar(list_id: int, start: str, end: str, *, board_ref=None, include_due: bool = True) -> dict:
    """What happens from `start` to `end` (YYYY-MM-DD, inclusive), in one project
    or (no board_ref) every active one: event occurrences, each with the day it
    falls on, and, with include_due, the open to-dos, subtasks and cards due then.
    The page shows them as a month grid or as an agenda."""
    first, last = _date(start, "start"), _date(end, "end")
    if last < first or (last - first).days > MAX_RANGE_DAYS:
        raise ValidationError(f"Ask for a range of 0 to {MAX_RANGE_DAYS} days")
    conn = db.get_db()
    where, args = (
        "r.list_id = ? AND r.type = 'schedule_entry' AND r.status = 'active' AND b.status = 'active'",
        [list_id],
    )
    board = None
    if board_ref is not None:
        board = boards._board(conn, list_id, board_ref)
        where += " AND r.board_id = ?"
        args.append(board["id"])
    else:
        where += " AND b.template = 0"  # a template's dates are not anyone's plans
    who = recordings._people(list_id)
    events = []
    for row in conn.execute(
        f"{recordings._SELECT} WHERE {where} AND r.starts_on <= ? ORDER BY r.starts_on, r.id", (*args, last.isoformat())
    ):
        event = recordings._shape(row, who)
        begins = datetime.date.fromisoformat(event["starts_on"])
        span = (datetime.date.fromisoformat(event["due_on"] or event["starts_on"]) - begins).days
        until = datetime.date.fromisoformat(event["repeat_until"]) if event.get("repeat_until") else None
        # An occurrence counts when any of its days fall in the range.
        for day in occurrences(begins, event.get("repeat"), until, first - datetime.timedelta(days=span), last):
            events.append({**event, "on": day.isoformat(), "until": (day + datetime.timedelta(days=span)).isoformat()})
    due: list[dict] = []
    if include_due:
        due = _due(conn, list_id, who, first.isoformat(), last.isoformat(), board["id"] if board is not None else None)
    return {"start": first.isoformat(), "end": last.isoformat(), "events": events, "due": due}


def _due(conn, list_id: int, who: dict, start: str, end: str, board_id: int | None) -> list[dict]:
    board_sql = " AND r.board_id = ?" if board_id is not None else " AND b.template = 0"
    out = []
    # Not what sits in something put away: up to three levels (a subtask's to-do, its
    # group, its list), or a subtask's card.
    for row in conn.execute(
        f"{recordings._SELECT} LEFT JOIN recordings p1 ON p1.id = r.parent_id "
        "LEFT JOIN recordings p2 ON p2.id = p1.parent_id LEFT JOIN recordings p3 ON p3.id = p2.parent_id "
        "WHERE r.list_id = ? AND r.type IN ('todo', 'step') AND r.status = 'active' "
        f"AND b.status = 'active' AND r.completed_at IS NULL AND r.due_on BETWEEN ? AND ?{board_sql} "
        "AND COALESCE(p1.status, 'active') = 'active' AND COALESCE(p2.status, 'active') = 'active' "
        "AND COALESCE(p3.status, 'active') = 'active' AND (r.card_id IS NULL OR EXISTS "
        "(SELECT 1 FROM cards c WHERE c.id = r.card_id AND c.list_id = r.list_id AND c.status = 'active')) "
        "ORDER BY r.due_on, r.id",
        (list_id, start, end, *([board_id] if board_id is not None else [])),
    ):
        item = recordings._shape(row, who)
        out.append(
            {
                "kind": item["type"],
                "id": item["id"],
                "card_id": item["card_id"],
                "title": item["title"],
                "on": item["due_on"],
                "board_id": item["board_id"],
                "board_name": item["board_name"],
                "assignees": item["assignees"],
                "parent_id": item["parent_id"],
            }
        )
    card_sql = " AND c.board_id = ?" if board_id is not None else " AND b.template = 0"
    for card in boards._shape_cards(
        conn,
        list_id,
        conn.execute(
            f"{boards._CARD} WHERE c.list_id = ? AND c.status = 'active' AND b.status = 'active' "
            f"AND c.completed_at IS NULL AND c.due_date BETWEEN ? AND ?{card_sql} ORDER BY c.due_date, c.id",
            (list_id, start, end, *([board_id] if board_id is not None else [])),
        ),
    ):
        out.append(
            {
                "kind": "card",
                "id": card["id"],
                "card_id": card["id"],
                "title": card["title"],
                "on": card["due_date"],
                "board_id": card["board_id"],
                "board_name": card["board_name"],
                "assignees": card["assignees"],
                "parent_id": None,
            }
        )
    return sorted(out, key=lambda x: (x["on"], x["title"]))


# ── Automatic Check-ins ───────────────────────────────────────────────────────


def asked_on(question: dict, day: datetime.date, tz: str = "UTC") -> bool:
    """Whether the question is asked on `day`: weekdays (0 = Sunday) from `days`
    for every_day; the first of them each week, or every other week from the
    week it began, for every_week and every_other_week; and on the day of the
    month it began for every_month. Never while paused."""
    if question.get("paused"):
        return False
    weekday = (day.weekday() + 1) % 7  # Python's Monday = 0; Basecamp's Sunday = 0
    days = question.get("days") or [1, 2, 3, 4, 5]
    began = common.local_date(question["created_at"], tz)  # the list's day it was asked first
    frequency = question.get("frequency") or "every_day"
    if day < began:
        return False
    if frequency == "every_day":
        return weekday in days
    if frequency == "every_week":
        return weekday == days[0]
    if frequency == "every_other_week":
        return weekday == days[0] and ((day - began).days // 7) % 2 == 0
    if frequency == "every_month":
        return day.day == min(began.day, _calendar.monthrange(day.year, day.month)[1])
    return False


def checkins_due(list_id: int, person_id: int | None, today: datetime.date | None = None) -> list[dict]:
    """The check-in questions this person is asked today and has not answered
    today: Basecamp's reminder, here shown in New for you and handed to AI tools."""
    if person_id is None:
        return []
    conn = db.get_db()
    if today is None:
        today = recordings._today(conn, list_id)
    who = recordings._people(list_id)
    tz = recordings._tz(conn, list_id)
    out = []
    for row in conn.execute(
        f"{recordings._SELECT} WHERE r.list_id = ? AND r.type = 'question' AND r.status = 'active' "
        "AND b.status = 'active' AND b.template = 0 "
        "AND EXISTS (SELECT 1 FROM json_each(r.assignee_ids) WHERE value = ?)",
        (list_id, person_id),
    ):
        question = recordings._shape(row, who)
        if not asked_on(question, today, tz):
            continue
        answered = conn.execute(
            "SELECT 1 FROM recordings WHERE list_id = ? AND parent_id = ? AND type = 'answer' AND status = 'active' "
            "AND creator_id = ? AND json_extract(data, '$.group_on') = ?",
            (list_id, question["id"], person_id, today.isoformat()),
        ).fetchone()
        if not answered:
            out.append(
                {
                    "id": question["id"],
                    "title": question["title"],
                    "board_id": question["board_id"],
                    "board_name": question["board_name"],
                    "group_on": today.isoformat(),
                    "time": question.get("time"),
                }
            )
    return out


def answers(list_id: int, question_id: int, *, person_id: int | None = None, limit_days: int = 30) -> list[dict]:
    """A question's answers, grouped by the day they answer, newest day first;
    one person's only, with person_id."""
    who = recordings._people(list_id)
    sql = f"{recordings._SELECT} WHERE r.list_id = ? AND r.parent_id = ? AND r.type = 'answer' AND r.status = 'active'"
    args: list = [list_id, question_id]
    if person_id is not None:
        sql += " AND r.creator_id = ?"
        args.append(person_id)
    days: dict[str, list] = {}
    for row in db.get_db().execute(f"{sql} ORDER BY json_extract(r.data, '$.group_on') DESC, r.id", args):
        answer = recordings._shape(row, who)
        answer["boosts"] = []
        days.setdefault(answer.get("group_on") or answer["created_at"][:10], []).append(answer)
    grouped = [{"day": d, "answers": a} for d, a in list(days.items())[:limit_days]]
    boosts = recordings._boosts(list_id, rec_ids=[a["id"] for g in grouped for a in g["answers"]])
    for g in grouped:
        for a in g["answers"]:
            a["boosts"] = boosts.get(("r", a["id"]), [])
    return grouped


# ── The Lineup ────────────────────────────────────────────────────────────────


def lineup(list_id: int, start: str, end: str) -> list[dict]:
    """Projects with both dates that overlap the window, current ones first, then
    upcoming, then ended: Basecamp's Lineup."""
    first, last = _date(start, "start"), _date(end, "end")
    conn = db.get_db()
    rows = conn.execute(
        "SELECT id, name, notes, starts_on, ends_on, pinned FROM boards WHERE list_id = ? AND status = 'active' AND template = 0 "
        "AND starts_on IS NOT NULL AND ends_on IS NOT NULL AND starts_on <= ? AND ends_on >= ? "
        "ORDER BY starts_on, id",
        (list_id, last.isoformat(), first.isoformat()),
    ).fetchall()
    today = recordings._today(conn, list_id).isoformat()

    def rank(b):
        return 0 if b["starts_on"] <= today <= b["ends_on"] else 1 if b["starts_on"] > today else 2

    return sorted((dict(b) for b in rows), key=lambda b: (rank(b), b["starts_on"]))
