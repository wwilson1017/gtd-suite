"""Projects GTD — the sample projects a new account starts with, so the app is never
empty on first look, and the switch that puts them away.

The web app seeds them the first time Home opens on an account with no projects at
all (`seed`). `lists.projects_sample` remembers the state: NULL never made, 'on'
shown, 'off' put away. Turning them off archives every sample project
(`boards.sample`); turning them on again restores those same projects. Nothing is
deleted, and sample projects do not count toward the account's projects cap
(boards._check_cap).

The rows are written here, in the seed's one ``db.transaction()``, the way
templates.py writes a copy. No activity trail rows: the samples are not news, so
they stay out of Activity and New for you.

# simplification: a seeded account has content, so cleanup.py keeps it like any used account; teach cleanup._unused to ignore sample-only accounts if dead seeded accounts pile up
"""

import datetime
import json

from backend import boards, common, db, people, recordings
from backend.common import ValidationError

STATES = ("on", "off")

_CONNECT = "/app/ai"

# Each project: its name, description, tools, whether it is starred, labels (name → colour), and per column
# (To do, Doing, Done) its cards. A card: title, and optional notes, labels, due (days
# from today), me (assigned to me), steps ([title, done]) and comment.
_PROJECTS = [
    {
        "name": "👋 Start here",
        "notes": "A sample project that shows how Projects works. Play with it, then turn the sample data off.",
        "tools": ["kanban_board"],
        "pinned": True,  # starred, so it is first on Home
        "labels": {"Try it": "green", "Tip": "blue"},
        "columns": {
            "To do": [
                {
                    "title": "Drag this card to Doing",
                    "labels": ["Try it"],
                    "notes": "Grab a card and drop it in another column. That's the whole idea: work "
                    "moves left to right until it's Done.",
                },
                {
                    "title": "Open me: checklists live inside cards",
                    "labels": ["Tip"],
                    "due": 3,
                    "notes": "A card holds notes, dates, labels, people and a checklist. Tick the "
                    "steps off below, or add one of your own.",
                    "steps": [["Open this card", True], ["Tick off a step", False], ["Add a step of your own", False]],
                },
                {
                    "title": "Ask your AI to add a card here",
                    "labels": ["Try it"],
                    "notes": f"Connect Claude, ChatGPT or another AI tool under [Connect your AI]({_CONNECT}). "
                    'Then ask it: "Add a card to Start here called Hello from my AI."',
                },
                {
                    "title": "Turn off the sample data when you're ready",
                    "labels": ["Tip"],
                    "notes": "When you've seen enough, press **Turn off sample data** in the yellow bar at "
                    "the top. The sample projects are archived; your own projects stay as they are.",
                },
            ],
            "Doing": [
                {
                    "title": "Give a card a label and a due date",
                    "labels": ["Tip"],
                    "due": 1,
                    "me": True,
                    "notes": "Labels colour-code cards. A due date shows on the card, in My Tasks and on the calendar.",
                },
            ],
            "Done": [
                {"title": "Make your account"},
            ],
        },
    },
    {
        "name": "Sample: Bakery website launch",
        "notes": "A sample project: a small bakery launching its new website.",
        "tools": ["kanban_board", "message_board", "todoset", "vault", "schedule"],
        "labels": {"Design": "purple", "Copy": "orange", "Photos": "pink", "Tech": "blue"},
        "columns": {
            "To do": [
                {
                    "title": "Shoot the seasonal cheesecakes",
                    "labels": ["Photos"],
                    "due": 4,
                    "steps": [["Pumpkin", False], ["Turtle", False], ["Key lime", False]],
                },
                {
                    "title": "Write the About page",
                    "labels": ["Copy"],
                    "due": 6,
                    "me": True,
                    "notes": "How the bakery started, in five short paragraphs. Warm, never salesy.",
                },
                {"title": "Pick the menu page layout", "labels": ["Design"]},
                {"title": "Set up the order email address", "labels": ["Tech"], "due": 9},
            ],
            "Doing": [
                {
                    "title": "Homepage hero photo",
                    "labels": ["Photos", "Design"],
                    "due": 2,
                    "me": True,
                    "steps": [["Shortlist three shots", True], ["Crop for phones", False], ["Get sign-off", False]],
                    "comment": "The overhead shot of the strawberry cheesecake is the front-runner.",
                },
                {
                    "title": "Menu page copy",
                    "labels": ["Copy"],
                    "due": 3,
                    "me": True,
                    "notes": "One line per cake: what's in it and what it goes with.",
                },
            ],
            "Done": [
                {"title": "Choose the colour palette", "labels": ["Design"]},
                {"title": "Register the domain", "labels": ["Tech"]},
            ],
        },
        "message": {
            "title": "Kickoff: the new website",
            "category": "📢 Announcement",
            "body": "We're building the new site this month.\n\n"
            "- **Board**: every task is a card. Move it along as it moves.\n"
            "- **To-dos**: the launch checklist.\n"
            "- **Docs**: the brand voice.\n\n"
            "Launch day is on the calendar.",
        },
        "todolist": {
            "title": "Launch checklist",
            "todos": [
                ["Test the order form on a phone", 7, True, False],
                ["Set up redirects from the old site", None, False, False],
                ["Tell the regulars on Instagram", 12, False, False],
                ["Check every page for typos", None, False, True],
            ],
        },
        "document": {
            "title": "Brand voice",
            "body": "# Brand voice\n\nWarm, short sentences. Say *cheesecake*, never "
            "*dessert product*. Every page ends with one clear next step: order, "
            "visit or call.",
        },
        "event": {"title": "Launch day", "in": 14},
    },
]


def _state(conn, list_id: int) -> str | None:
    return conn.execute("SELECT projects_sample FROM lists WHERE id = ?", (list_id,)).fetchone()[0]


def _projects(conn, list_id: int) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, status FROM boards WHERE list_id = ? AND sample = 1 ORDER BY id", (list_id,)
        )
    ]


def state(list_id: int) -> dict:
    """The samples' state (None, 'on' or 'off') and the sample projects, in any status."""
    conn = db.get_db()
    return {"state": _state(conn, list_id), "projects": _projects(conn, list_id)}


def seed(list_id: int) -> dict:
    """Make the sample projects, once: only on an account that has never had them and
    has no project at all. Otherwise nothing changes. Returns `state`."""
    with db.transaction() as conn:
        if (
            _state(conn, list_id) is None
            and not conn.execute("SELECT 1 FROM boards WHERE list_id = ?", (list_id,)).fetchone()
        ):
            me = people.me_in(conn, list_id)
            today = recordings._today(conn, list_id)
            for spec in _PROJECTS:
                _make_in(conn, list_id, spec, me, today)
            conn.execute("UPDATE lists SET projects_sample = 'on' WHERE id = ?", (list_id,))
    return state(list_id)


def turn(list_id: int, on: bool) -> dict:
    """Off: archive every active sample project. On: restore the archived ones. Their
    contents stay as they were either way. Returns `state`."""
    with db.transaction() as conn:
        if _state(conn, list_id) is None:
            raise ValidationError("This account has no sample projects.")
        conn.execute(
            "UPDATE boards SET status = ?, updated_at = ? WHERE list_id = ? AND sample = 1 AND status = ?",
            ("active" if on else "archived", common.now_iso(), list_id, "archived" if on else "active"),
        )
        conn.execute("UPDATE lists SET projects_sample = ? WHERE id = ?", ("on" if on else "off", list_id))
    return state(list_id)


def _make_in(conn, list_id: int, spec: dict, me: int, today: datetime.date) -> int:
    def day(n):
        return None if n is None else (today + datetime.timedelta(days=n)).isoformat()

    now = common.now_iso()
    mine = json.dumps([me])
    board_id = conn.execute(
        "INSERT INTO boards (list_id, name, notes, dock, pinned, sample, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (
            list_id,
            spec["name"],
            spec["notes"],
            json.dumps([{"tool": t, "enabled": True} for t in spec["tools"]]),
            1 if spec.get("pinned") else 0,
            now,
            now,
        ),
    ).lastrowid
    boards._add_fixed_in(conn, list_id, board_id, now)
    labels = {
        name: boards._new_label_in(conn, list_id, board_id, name, color) for name, color in spec["labels"].items()
    }
    names = list(spec["columns"])
    for n, (column, cards) in enumerate(spec["columns"].items()):
        done = n == len(names) - 1
        column_id = conn.execute(
            "INSERT INTO board_columns (list_id, board_id, name, position, kind, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (list_id, board_id, column, n, "done" if done else "column", now, now),
        ).lastrowid
        for position, card in enumerate(cards):
            card_id = conn.execute(
                "INSERT INTO cards (list_id, board_id, column_id, title, notes, due_date, position, source, "
                "created_at, updated_at, assignee_ids, label_ids, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'ui', ?, ?, ?, ?, ?)",
                (
                    list_id,
                    board_id,
                    column_id,
                    card["title"],
                    card.get("notes", ""),
                    day(card.get("due")),
                    position,
                    now,
                    now,
                    mine if card.get("me") else "[]",
                    json.dumps([labels[name] for name in card.get("labels", [])]),
                    now if done else None,
                ),
            ).lastrowid
            for step_at, (title, ticked) in enumerate(card.get("steps", [])):
                _rec(
                    conn,
                    list_id,
                    board_id,
                    me,
                    now,
                    "step",
                    title,
                    card_id=card_id,
                    position=step_at,
                    completed_at=now if ticked else None,
                    completer_id=me if ticked else None,
                )
            if card.get("comment"):
                _rec(conn, list_id, board_id, me, now, "comment", body=card["comment"], card_id=card_id)
    if "message" in spec:
        m = spec["message"]
        _rec(conn, list_id, board_id, me, now, "message", m["title"], body=m["body"], category=m["category"])
    if "todolist" in spec:
        t = spec["todolist"]
        list_rec = _rec(conn, list_id, board_id, me, now, "todolist", t["title"])
        for at, (title, due, assigned, ticked) in enumerate(t["todos"]):
            _rec(
                conn,
                list_id,
                board_id,
                me,
                now,
                "todo",
                title,
                parent_id=list_rec,
                position=at,
                due_on=day(due),
                assignee_ids=mine if assigned else "[]",
                completed_at=now if ticked else None,
                completer_id=me if ticked else None,
            )
    if "document" in spec:
        d = spec["document"]
        _rec(conn, list_id, board_id, me, now, "document", d["title"], body=d["body"])
    if "event" in spec:
        e = spec["event"]
        on = day(e["in"])
        _rec(
            conn,
            list_id,
            board_id,
            me,
            now,
            "schedule_entry",
            e["title"],
            starts_on=on,
            due_on=on,
            data=json.dumps({"all_day": True}),
        )
    return board_id


def _rec(
    conn,
    list_id: int,
    board_id: int,
    me: int,
    now: str,
    kind: str,
    title: str = "",
    *,
    body: str = "",
    parent_id: int | None = None,
    card_id: int | None = None,
    position: int = 0,
    **cols,
) -> int:
    row = {
        "list_id": list_id,
        "board_id": board_id,
        "parent_id": parent_id,
        "card_id": card_id,
        "type": kind,
        "title": title,
        "body": body,
        "position": position,
        "creator_id": me,
        "source": "ui",
        "created_at": now,
        "updated_at": now,
        **cols,
    }
    return conn.execute(
        f"INSERT INTO recordings ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
    ).lastrowid
