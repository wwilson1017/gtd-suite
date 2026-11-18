"""Projects GTD — New for you, as Basecamp 5's sidebar: what everyone else (here,
mostly your AI tools) did lately, one entry per item with how many things happened
to it since you last looked; what you bubbled up to come back to; and what is due.
Also My Bar's other personal views: Up Next (your private order on My Tasks), My
Drafts and My Boosts.

Read state belongs to the account's person ("me"): `people.read_at` is the line
under which everything is read (Mark all read), and a `readings` row per item can
move it for that item, mark it unread by hand, or bubble it up to a later time.
Unread is worked out when read, from the activity trail; nothing is ever written
on a GET. A reading can also be muted (Basecamp's "Don't notify me"): a muted item,
or anything in a muted project, never counts as new; it lists with the read ones. Every write is one ``db.transaction()``; every query is list-scoped.

# simplification: the sidebar reads the newest INBOX_EVENTS events and groups them in Python — fine for one person's account; a per-item unread table if it ever needs more
"""

import datetime
import json
from typing import cast

from backend import boards, common, db, people, recordings, schedules
from backend.common import NotFoundError, ValidationError

INBOX_EVENTS = 1_000
PREVIOUS_SHOWN = 30
MAX_UP_NEXT = 100


def _target(rec_id=None, card_id=None, board_id=None) -> dict:
    given = {k: v for k, v in (("recording_id", rec_id), ("card_id", card_id), ("board_id", board_id)) if v is not None}
    if len(given) != 1:
        raise ValidationError("Name one thing: an item, a card or a project")
    return given


def _me(conn, list_id: int) -> dict | None:
    row = conn.execute("SELECT id, read_at FROM people WHERE list_id = ? AND kind = 'me'", (list_id,)).fetchone()
    return dict(row) if row else None


def _key(e) -> tuple:
    """Which item an event belongs to: its recording, its card, or the project."""
    if e["recording_id"] is not None:
        return ("r", e["recording_id"])
    if e["card_id"] is not None:
        return ("c", e["card_id"])
    return ("b", e["board_id"])


def _readings(conn, list_id: int) -> dict[tuple, dict]:
    out = {}
    for r in conn.execute("SELECT * FROM readings WHERE list_id = ?", (list_id,)):
        key = (
            ("r", r["recording_id"])
            if r["recording_id"]
            else ("c", r["card_id"])
            if r["card_id"]
            else ("b", r["board_id"])
        )
        out[key] = dict(r)
    return out


def sidebar(list_id: int, now: datetime.datetime | None = None) -> dict:
    """The sidebar: bubbled up (items whose time to come back has come), new for
    you (unread items, newest first, each with what happened and who did it),
    previous (the latest read ones), due (my open to-dos and cards due tomorrow
    or before), and the unread count."""
    conn = db.get_db()
    now_iso = common.to_iso(now or common.utcnow())
    me = _me(conn, list_id)
    me_id, line = (me["id"], me["read_at"] or "") if me else (None, "")
    readings = _readings(conn, list_id)
    rows = conn.execute(
        f"SELECT e.*, b.name AS board_name, r.type AS recording_type, {recordings.TITLE_SQL} AS recording_title, "
        "r.status AS recording_status, c.title AS card_title, c.status AS card_status, "
        "p.name AS creator_name, p.kind AS creator_kind, p.color AS creator_color "
        "FROM events e JOIN boards b ON b.id = e.board_id "
        "LEFT JOIN recordings r ON r.id = e.recording_id AND r.list_id = e.list_id "
        "LEFT JOIN recordings pr ON pr.id = r.parent_id AND pr.list_id = r.list_id "
        "LEFT JOIN cards c ON c.id = e.card_id AND c.list_id = e.list_id "
        "LEFT JOIN people p ON p.id = e.creator_id "
        "WHERE e.list_id = ? AND (e.creator_id IS NULL OR e.creator_id IS NOT ?) "
        "ORDER BY e.id DESC LIMIT ?",
        (list_id, me_id, INBOX_EVENTS),
    ).fetchall()
    items: dict[tuple, dict] = {}
    for e in rows:
        key = _key(e)
        item = items.get(key)
        if item is None:
            if e["recording_status"] in ("trashed", "drafted") or e["card_status"] == "archived":
                continue  # nothing to open
            item = items[key] = {
                "key": f"{key[0]}{key[1]}",
                "recording_id": e["recording_id"],
                "card_id": e["card_id"],
                "board_id": e["board_id"],
                "board_name": e["board_name"],
                "title": e["recording_title"] or e["card_title"] or e["board_name"],
                "type": e["recording_type"] or ("card" if e["card_id"] else "project"),
                "last": {
                    "verb": recordings.verb(e["action"], e["recording_type"]),
                    "action": e["action"],
                    "detail": e["detail"],
                    "created_at": e["created_at"],
                    "creator": {
                        "id": e["creator_id"],
                        "name": e["creator_name"],
                        "kind": e["creator_kind"],
                        "color": e["creator_color"],
                    },
                },
                "events": [],
                "people": [],
            }
        item["events"].append(e["created_at"])
        if e["creator_name"] and e["creator_name"] not in item["people"]:
            item["people"].append(e["creator_name"])
    unread, previous, bubbled = [], [], []
    for key, item in items.items():
        reading = readings.get(key, {})
        seen = max(line, reading.get("read_at") or "")
        # simplification: millisecond stamps, so an event in the very millisecond of a read
        # counts as read; an event-id cursor in readings would make it exact.
        fresh = [t for t in item.pop("events") if t > seen]
        # simplification: a mute is total; Basecamp's "only when someone @mentions me" is
        # what My Tasks' mentions are for.
        item["project_muted"] = bool(readings.get(("b", item["board_id"]), {}).get("muted"))
        item["muted"] = bool(reading.get("muted")) or item["project_muted"]
        if item["muted"]:
            fresh = []
        item["unread_count"] = len(fresh) if fresh else (1 if reading.get("unread") else 0)
        item["bubble_up_at"] = reading.get("bubble_up_at")
        if item["bubble_up_at"] and item["bubble_up_at"] <= now_iso:
            bubbled.append(item)
        elif item["unread_count"]:
            unread.append(item)
        else:
            previous.append(item)
    # A bubbled-up or hand-marked unread item with no event in the window above
    # (old, or only my own work) is still listed from its reading.
    for key, reading in readings.items():
        if key in items:
            continue
        if reading.get("bubble_up_at") and reading["bubble_up_at"] <= now_iso:
            bubbled.append(_reading_item(conn, list_id, key, reading))
        elif reading.get("unread") and (item := _reading_item(conn, list_id, key, reading)):
            unread.append({**item, "unread_count": 1})
    scheduled = sorted(
        (r for r in readings.values() if r.get("bubble_up_at") and r["bubble_up_at"] > now_iso),
        key=lambda r: r["bubble_up_at"],
    )
    return {
        "bubbled": [b for b in bubbled if b],
        "unread": unread,
        "previous": previous[:PREVIOUS_SHOWN],
        "scheduled_bubble_ups": len(scheduled),
        "due": due(list_id),
        "unread_count": len(unread) + len([b for b in bubbled if b]),
    }


def _reading_item(conn, list_id: int, key: tuple, reading: dict) -> dict | None:
    kind, ref = key
    if kind == "r":
        row = conn.execute(
            "SELECT r.id, r.title, r.type, r.board_id, b.name AS board_name FROM recordings r "
            "JOIN boards b ON b.id = r.board_id WHERE r.id = ? AND r.list_id = ? "
            "AND r.status NOT IN ('trashed', 'drafted')",
            (ref, list_id),
        ).fetchone()
    elif kind == "c":
        row = conn.execute(
            "SELECT c.id, c.title, 'card' AS type, c.board_id, b.name AS board_name FROM cards c "
            "JOIN boards b ON b.id = c.board_id WHERE c.id = ? AND c.list_id = ? "
            "AND c.status != 'archived'",
            (ref, list_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, name AS title, 'project' AS type, id AS board_id, name AS board_name "
            "FROM boards WHERE id = ? AND list_id = ?",
            (ref, list_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "key": f"{kind}{ref}",
        "recording_id": ref if kind == "r" else None,
        "card_id": ref if kind == "c" else None,
        "board_id": row["board_id"],
        "board_name": row["board_name"],
        "title": row["title"],
        "type": row["type"],
        "last": None,
        "people": [],
        "unread_count": 0,
        "bubble_up_at": reading.get("bubble_up_at"),
    }


def unread_count(list_id: int) -> int:
    return sidebar(list_id)["unread_count"]


def due(list_id: int) -> list[dict]:
    """My open to-dos and cards due tomorrow or earlier, soonest first: what
    Basecamp's reminders would have said."""
    conn = db.get_db()
    me = _me(conn, list_id)
    if me is None:
        return []
    tz = conn.execute("SELECT tz FROM lists WHERE id = ?", (list_id,)).fetchone()["tz"]
    tomorrow = (common.business_today(tz) + datetime.timedelta(days=1)).isoformat()
    todos = [
        {
            "recording_id": t["id"],
            "card_id": None,
            "board_id": t["board_id"],
            "board_name": t["board_name"],
            "title": t["title"],
            "due": t["due_on"],
        }
        for t in recordings.assignments(list_id, me["id"])
        if t["due_on"] and t["due_on"] <= tomorrow
    ]
    cards = [
        {
            "recording_id": None,
            "card_id": c["id"],
            "board_id": c["board_id"],
            "board_name": c["board_name"],
            "title": c["title"],
            "due": c["due_date"],
        }
        for c in boards.assigned_cards(list_id, me["id"])
        if c["due_date"] and c["due_date"] <= tomorrow
    ]
    checkins = [
        {
            "recording_id": q["id"],
            "card_id": None,
            "board_id": q["board_id"],
            "board_name": q["board_name"],
            "title": f"Check-in: {q['title']}",
            "due": q["group_on"],
        }
        for q in schedules.checkins_due(list_id, me["id"])
    ]
    return sorted(todos + cards + checkins, key=lambda x: x["due"])


def _reading_in(conn, list_id: int, target: dict) -> dict:
    """The item's readings row, made when missing."""
    column, value = next(iter(target.items()))
    table = {"recording_id": "recordings", "card_id": "cards", "board_id": "boards"}[column]
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ? AND list_id = ?", (value, list_id)).fetchone() is None:
        raise NotFoundError(f"Not found: {value}")
    row = conn.execute(f"SELECT * FROM readings WHERE list_id = ? AND {column} = ?", (list_id, value)).fetchone()
    if row:
        return dict(row)
    now = common.now_iso()
    conn.execute(
        f"INSERT INTO readings (list_id, {column}, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (list_id, value, now, now),
    )
    return dict(conn.execute(f"SELECT * FROM readings WHERE list_id = ? AND {column} = ?", (list_id, value)).fetchone())


def _set(conn, list_id: int, reading_id: int, **sets) -> None:
    sets["updated_at"] = common.now_iso()
    conn.execute(
        f"UPDATE readings SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ? AND list_id = ?",
        (*sets.values(), reading_id, list_id),
    )


def mark(list_id: int, read: bool, *, rec_id=None, card_id=None, board_id=None) -> dict:
    """Mark one item read (everything on it so far) or unread."""
    target = _target(rec_id, card_id, board_id)
    with db.transaction() as conn:
        reading = _reading_in(conn, list_id, target)
        now = common.now_iso()
        if read:
            # Reading a bubbled-up item is what it came back for: it leaves Bubbled up.
            due = reading["bubble_up_at"] and reading["bubble_up_at"] <= now
            _set(conn, list_id, reading["id"], read_at=now, unread=0, **({"bubble_up_at": None} if due else {}))
        else:
            _set(conn, list_id, reading["id"], read_at="", unread=1)
    return {"read": read}


def mute(list_id: int, muted: bool, *, rec_id=None, card_id=None, board_id=None) -> dict:
    """Basecamp's "Don't notify me" on an item, a card or a whole project (its bell):
    what happens there stops counting as new. Either way the item is read from now:
    muting takes it out of New for you at once, and unmuting it does not bring back
    what happened while it was muted. Unmuting a project lists what its items had
    meanwhile, to catch up on: only the project's own entry is read."""
    target = _target(rec_id, card_id, board_id)
    with db.transaction() as conn:
        reading = _reading_in(conn, list_id, target)
        now = common.now_iso()
        # Bubbled up already: muting means "stop", so it leaves Bubbled up too (as reading it does).
        due = muted and reading["bubble_up_at"] and reading["bubble_up_at"] <= now
        _set(
            conn,
            list_id,
            reading["id"],
            muted=int(bool(muted)),
            read_at=now,
            unread=0,
            **({"bubble_up_at": None} if due else {}),
        )
    return {"muted": bool(muted)}


def muted(list_id: int, *, rec_id=None, card_id=None, board_id=None) -> bool:
    """Whether that one item (or project) is muted itself."""
    column, value = next(iter(_target(rec_id, card_id, board_id).items()))
    row = (
        db.get_db()
        .execute(f"SELECT muted FROM readings WHERE list_id = ? AND {column} = ?", (list_id, value))
        .fetchone()
    )
    return bool(row and row["muted"])


def mark_all_read(list_id: int) -> dict:
    """Mark all read: move the person's line to now, and clear hand-marked unreads."""
    with db.transaction() as conn:
        me = people.me_in(conn, list_id)
        now = common.now_iso()
        conn.execute(
            "UPDATE people SET read_at = ?, updated_at = ? WHERE id = ? AND list_id = ?", (now, now, me, list_id)
        )
        conn.execute("UPDATE readings SET unread = 0, updated_at = ? WHERE list_id = ? AND unread = 1", (now, list_id))
        # …and the bubble-ups whose time has come are read too.
        conn.execute(
            "UPDATE readings SET bubble_up_at = NULL, updated_at = ? WHERE list_id = ? "
            "AND bubble_up_at IS NOT NULL AND bubble_up_at <= ?",
            (now, list_id, now),
        )
    return {"read_at": now}


BUBBLE_TIMES = ("now", "later_today", "tomorrow", "this_weekend", "next_week")


def bubble_up_at(when: str | None, tz: str, now: datetime.datetime | None = None) -> str | None:
    """Basecamp's Bubble Up choices as an instant: now, later today (in three hours),
    tomorrow, this weekend (Saturday) or next week (Monday), at 9 am in the list's
    time zone; or a YYYY-MM-DD at 9 am; "" or None takes the bubble-up off."""
    from zoneinfo import ZoneInfo

    if when in (None, ""):
        return None
    now = now or common.utcnow()
    zone = ZoneInfo(common.validate_tz(tz))
    local = now.astimezone(zone)
    at_nine = lambda d: datetime.datetime(d.year, d.month, d.day, 9, tzinfo=zone)  # noqa: E731
    if when == "now":
        moment = now
    elif when == "later_today":
        moment = now + datetime.timedelta(hours=3)
    elif when == "tomorrow":
        moment = at_nine(local.date() + datetime.timedelta(days=1))
    elif when == "this_weekend":
        moment = at_nine(local.date() + datetime.timedelta(days=(5 - local.weekday()) % 7 or 7))
    elif when == "next_week":
        moment = at_nine(local.date() + datetime.timedelta(days=7 - local.weekday()))
    else:
        # Empty choices returned above; validate_due returns a date string or raises.
        moment = at_nine(datetime.date.fromisoformat(cast(str, common.validate_due(when, "when"))))
    return common.to_iso(moment.astimezone(datetime.timezone.utc))


def bubble_up(list_id: int, when: str | None, *, rec_id=None, card_id=None, board_id=None) -> dict:
    """Bubble an item up to come back at `when` (BUBBLE_TIMES or a date), or take
    the bubble-up off (None or "")."""
    if when not in (None, "", *BUBBLE_TIMES):
        common.validate_due(when, "when")
    target = _target(rec_id, card_id, board_id)
    with db.transaction() as conn:
        tz = conn.execute("SELECT tz FROM lists WHERE id = ?", (list_id,)).fetchone()["tz"]
        reading = _reading_in(conn, list_id, target)
        at = bubble_up_at(when, tz)
        # Coming back reads it: it shows under Bubbled up, not again under New for you.
        _set(conn, list_id, reading["id"], bubble_up_at=at, read_at=common.now_iso(), unread=0)
    return {"bubble_up_at": at}


# ── Up Next, My Drafts, My Boosts ─────────────────────────────────────────────


def up_next(list_id: int) -> list[dict]:
    """My private Up Next order: the open to-dos and cards still mine (assigned to
    me, in a live list and project), in the order I put them."""
    conn = db.get_db()
    row = conn.execute("SELECT id, up_next FROM people WHERE list_id = ? AND kind = 'me'", (list_id,)).fetchone()
    if row is None:
        return []
    mine = {("r", t["id"]): ("todo", t) for t in recordings.assignments(list_id, row["id"])}
    mine.update({("c", c["id"]): ("card", c) for c in boards.assigned_cards(list_id, row["id"])})
    return [{"kind": mine[key][0], **mine[key][1]} for key in map(tuple, json.loads(row["up_next"])) if key in mine]


def set_up_next(list_id: int, items: list) -> list[dict]:
    """Save Up Next: [["r", to-do id] or ["c", card id], …] in order."""
    if not isinstance(items, list) or len(items) > MAX_UP_NEXT:
        raise ValidationError(f"Up Next is a list of at most {MAX_UP_NEXT} items")
    clean = []
    with db.transaction() as conn:
        for entry in items:
            if not (
                isinstance(entry, list) and len(entry) == 2 and entry[0] in ("r", "c") and isinstance(entry[1], int)
            ):
                raise ValidationError('Each Up Next item is ["r", to-do id] or ["c", card id]')
            table = "recordings" if entry[0] == "r" else "cards"
            if (
                conn.execute(f"SELECT 1 FROM {table} WHERE id = ? AND list_id = ?", (entry[1], list_id)).fetchone()
                is None
            ):
                raise NotFoundError(f"Not found: {entry[1]}")
            if entry not in clean:
                clean.append(entry)
        me = people.me_in(conn, list_id)
        conn.execute(
            "UPDATE people SET up_next = ?, updated_at = ? WHERE id = ? AND list_id = ?",
            (json.dumps(clean), common.now_iso(), me, list_id),
        )
    return up_next(list_id)


def drafts(list_id: int) -> list[dict]:
    """My Drafts: unposted messages, mine and my AI tools' (theirs wait for me to
    post them), the most recently changed first."""
    conn = db.get_db()
    who = recordings._people(list_id)
    return [
        recordings._shape(r, who)
        for r in conn.execute(
            f"{recordings._SELECT} WHERE r.list_id = ? AND r.status = 'drafted' ORDER BY r.updated_at DESC, r.id DESC",
            (list_id,),
        )
    ]


def my_boosts(list_id: int) -> list[dict]:
    """My Boosts: the boosts others gave what I wrote, newest first."""
    conn = db.get_db()
    me = _me(conn, list_id)
    if me is None:
        return []
    who = recordings._people(list_id)
    rows = conn.execute(
        "SELECT x.id, x.content, x.booster_id, x.created_at, x.recording_id, x.card_id, "
        "COALESCE(r.board_id, c.board_id) AS board_id, COALESCE(r.title, c.title) AS title, "
        "r.type AS recording_type, r.parent_id AS recording_parent_id, r.body AS recording_body "
        "FROM boosts x LEFT JOIN recordings r ON r.id = x.recording_id AND r.list_id = x.list_id "
        "LEFT JOIN cards c ON c.id = x.card_id AND c.list_id = x.list_id "
        "WHERE x.list_id = ? AND x.status = 'active' AND x.booster_id != ? "
        "AND (r.creator_id = ? OR (c.id IS NOT NULL AND c.source = 'ui')) "
        "ORDER BY x.id DESC LIMIT 200",
        (list_id, me["id"], me["id"]),
    ).fetchall()
    return [
        {
            **dict(r),
            "booster": who.get(r["booster_id"]),
            "title": r["title"] or recordings._excerpt(r["recording_body"] or "", 80),
        }
        for r in rows
    ]
