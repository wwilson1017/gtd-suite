"""Projects GTD — Card Table automation, as Trello's Butler: rules that act on a
card when something happens to it, card buttons that act on one card when
pressed, and board buttons that act on every card in a column.

A rule's trigger is one of TRIGGERS, perhaps with a column; its actions (at most
MAX_ACTIONS) are ACTIONS. A scheduled rule (Trello's scheduled commands) acts on
every card in its column at a time of day, every day, weekday, week or month, in
the account's timezone (scheduled_tick, from the minute loop). The person sets them up; they are structure, so the
agent link reads none and writes none, but what an AI tool does to a card fires
them like anything else.

A rule runs right after the write that fired it, as its own writes through the
same functions the app uses, by the "Automation" person (people.actor_in), so the
trail says what it did. What a rule does never fires another rule (_running), so
rules cannot set each other off forever. A failing action stops that rule's run
and is kept in last_error for the page to show; it never undoes the write that
fired it.

# simplification: a rule runs in transactions of its own after the firing write
# commits, not inside it (db.transaction is not re-entrant), so a crash between the
# two leaves the card as the person left it; actions written against conn would
# make the pair atomic.
"""

import contextvars
import datetime
import json
import logging
from typing import TypedDict
from zoneinfo import ZoneInfo

from backend import boards, common, db, people, recordings
from backend.common import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

KINDS = ("rule", "card_button", "board_button")
TRIGGERS = ("card_added", "card_moved", "card_completed", "subtasks_done", "due_soon", "scheduled")
EVERY = ("day", "weekday", "week", "month")  # how often a scheduled rule runs
ACTIONS = (
    "move",
    "complete",
    "reopen",
    "assign",
    "unassign_all",
    "add_label",
    "remove_label",
    "add_subtasks",
    "comment",
    "set_due",
    "clear_due",
    "archive",
    "hold",
)
MAX_ACTIONS = 20
MAX_RULES = 50  # per project, archived ones not counted
MAX_BUTTON_CARDS = 500  # a board button acts on every card in its column, up to this many
ACTOR = "Automation"  # the AI-tool person rules write as

_running: contextvars.ContextVar[bool] = contextvars.ContextVar("automation_running", default=False)


def _shape(row) -> dict:
    out = dict(row)
    out["trigger"] = json.loads(out["trigger"] or "{}")
    out["actions"] = json.loads(out["actions"] or "[]")
    out.pop("list_id")
    return out


# ── Checking what the person set up ───────────────────────────────────────────


def _column_in(conn, list_id: int, board_id: int, ref) -> int:
    col = boards._column(conn, list_id, board_id, ref)
    return col["id"]


def _clean_trigger(conn, list_id: int, board_id: int, kind: str, trigger) -> dict:
    trigger = trigger or {}
    if not isinstance(trigger, dict):
        raise ValidationError("trigger must be an object")
    if kind == "card_button":
        return {}
    if kind == "board_button":
        if trigger.get("column") in (None, ""):
            raise ValidationError("A board button acts on the cards in a column: give it a column")
        return {"column": _column_in(conn, list_id, board_id, trigger["column"])}
    on = trigger.get("on")
    if on not in TRIGGERS:
        raise ValidationError(f"trigger.on must be one of {', '.join(TRIGGERS)}")
    out: dict = {"on": on}
    if on in ("card_added", "card_moved"):
        if trigger.get("column") not in (None, ""):
            out["column"] = _column_in(conn, list_id, board_id, trigger["column"])
        elif on == "card_moved":
            raise ValidationError("Moved into which column?")
    if on == "due_soon":
        days = trigger.get("days", 1)
        if not isinstance(days, int) or not 0 <= days <= 30:
            raise ValidationError("trigger.days must be 0 (due today) to 30")
        out["days"] = days
    if on == "scheduled":
        out.update(_clean_schedule(conn, list_id, board_id, trigger))
    return out


def _clean_schedule(conn, list_id: int, board_id: int, trigger: dict) -> dict:
    """When a scheduled rule runs and on which column's cards: every day or weekday, a
    weekday of each week (0 Sunday to 6 Saturday) or a day of each month (1 to 28),
    at HH:MM in the account's timezone."""
    if trigger.get("column") in (None, ""):
        raise ValidationError("A scheduled rule acts on the cards in a column: give it a column")
    every = trigger.get("every", "week")
    if every not in EVERY:
        raise ValidationError(f"trigger.every must be one of {', '.join(EVERY)}")
    out = {"column": _column_in(conn, list_id, board_id, trigger["column"]), "every": every}
    day = trigger.get("day", 1)
    if every in ("week", "month"):
        low, high = (0, 6) if every == "week" else (1, 28)
        if not isinstance(day, int) or isinstance(day, bool) or not low <= day <= high:
            raise ValidationError(f"trigger.day must be {low} to {high} for every {every}")
        out["day"] = day
    time = str(trigger.get("time") or "09:00")
    if not recordings._TIME.match(time):
        raise ValidationError("trigger.time must be HH:MM, 24-hour")
    out["time"] = time
    return out


def _clean_actions(conn, list_id: int, board_id: int, actions) -> list[dict]:
    if not isinstance(actions, list) or not actions:
        raise ValidationError("A rule or button needs at least one action")
    if len(actions) > MAX_ACTIONS:
        raise ValidationError(f"At most {MAX_ACTIONS} actions")
    out = []
    for a in actions:
        if not isinstance(a, dict) or a.get("do") not in ACTIONS:
            raise ValidationError(f"Each action's do must be one of {', '.join(ACTIONS)}")
        do = a["do"]
        clean: dict = {"do": do}
        if do == "move":
            clean["column"] = _column_in(conn, list_id, board_id, a.get("column"))
            clean["position"] = a.get("position") if a.get("position") in ("top", "bottom") else "bottom"
        elif do == "assign":
            clean["people"] = people.resolve_in(conn, list_id, a.get("people") or [])
            if not clean["people"]:
                raise ValidationError("Assign whom?")
        elif do in ("add_label", "remove_label"):
            ids = boards._label_ids_in(conn, list_id, board_id, [a.get("label")])
            if not ids:
                raise ValidationError("Which label?")
            clean["label"] = ids[0]
        elif do == "add_subtasks":
            titles = [common.validate_short(t, "subtask") for t in (a.get("titles") or [])]
            titles = [t for t in titles if t]
            if not titles or len(titles) > 20:
                raise ValidationError("add_subtasks needs 1 to 20 titles")
            clean["titles"] = titles
        elif do == "comment":
            text = common.validate_notes(a.get("text") or "", "text").strip()
            if not text:
                raise ValidationError("A comment needs some text")
            clean["text"] = text
        elif do == "set_due":
            days = a.get("days")
            if not isinstance(days, int) or not 0 <= days <= 365:
                raise ValidationError("set_due.days must be 0 (today) to 365")
            clean["days"] = days
        elif do == "hold":
            clean["on"] = bool(a.get("on", True))
        out.append(clean)
    return out


# ── Reading and writing rules ─────────────────────────────────────────────────


def list_rules(list_id: int, board_ref, status: str = "active") -> list[dict]:
    """A project's rules and buttons, rules first, each in its order."""
    conn = db.get_db()
    board = boards._board(conn, list_id, board_ref)
    return [
        _shape(r)
        for r in conn.execute(
            "SELECT * FROM rules WHERE list_id = ? AND board_id = ? AND status = ? "
            "ORDER BY CASE kind WHEN 'rule' THEN 0 WHEN 'card_button' THEN 1 ELSE 2 END, position, id",
            (list_id, board["id"], boards._status(status)),
        )
    ]


def create_rule(list_id: int, board_ref, kind: str, name: str, trigger, actions) -> dict:
    if kind not in KINDS:
        raise ValidationError(f"kind must be one of {', '.join(KINDS)}")
    name = common.validate_short(name, "name").strip()
    if kind != "rule" and not name:
        raise ValidationError("A button needs a name: it is what the button says")
    with db.transaction() as conn:
        board = boards._board(conn, list_id, board_ref)
        n = conn.execute(
            "SELECT COUNT(*) FROM rules WHERE list_id = ? AND board_id = ? AND status = 'active'",
            (list_id, board["id"]),
        ).fetchone()[0]
        if n >= MAX_RULES:
            raise ValidationError(f"A project has at most {MAX_RULES} rules and buttons")
        now = common.now_iso()
        rule_id = conn.execute(
            "INSERT INTO rules (list_id, board_id, kind, name, trigger, actions, position, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                list_id,
                board["id"],
                kind,
                name,
                json.dumps(_clean_trigger(conn, list_id, board["id"], kind, trigger)),
                json.dumps(_clean_actions(conn, list_id, board["id"], actions)),
                n,
                now,
                now,
            ),
        ).lastrowid
        assert rule_id is not None  # A successful INSERT into a rowid table.
    return get_rule(list_id, rule_id)


def get_rule(list_id: int, rule_id: int) -> dict:
    row = db.get_db().execute("SELECT * FROM rules WHERE id = ? AND list_id = ?", (rule_id, list_id)).fetchone()
    if row is None:
        raise NotFoundError(f"Rule not found: {rule_id}")
    return _shape(row)


def update_rule(list_id: int, rule_id: int, fields: dict) -> dict:
    """Rename it, change what fires it or what it does, archive or restore it."""
    unknown = set(fields) - {"name", "trigger", "actions", "status"}
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(sorted(unknown))}")
    with db.transaction() as conn:
        rule = conn.execute("SELECT * FROM rules WHERE id = ? AND list_id = ?", (rule_id, list_id)).fetchone()
        if rule is None:
            raise NotFoundError(f"Rule not found: {rule_id}")
        sets: dict = {}
        if "name" in fields:
            sets["name"] = common.validate_short(fields["name"], "name").strip()
            if rule["kind"] != "rule" and not sets["name"]:
                raise ValidationError("A button needs a name")
        if "trigger" in fields:
            sets["trigger"] = json.dumps(
                _clean_trigger(conn, list_id, rule["board_id"], rule["kind"], fields["trigger"])
            )
        if "actions" in fields:
            sets["actions"] = json.dumps(_clean_actions(conn, list_id, rule["board_id"], fields["actions"]))
        if "status" in fields:
            sets["status"] = boards._status(fields["status"])
            sets["last_error"] = None
            if (
                sets["status"] == "active"
                and rule["status"] != "active"
                and conn.execute(
                    "SELECT COUNT(*) FROM rules WHERE list_id = ? AND board_id = ? AND status = 'active'",
                    (list_id, rule["board_id"]),
                ).fetchone()[0]
                >= MAX_RULES
            ):
                raise ValidationError(f"A project has at most {MAX_RULES} rules and buttons: archive one first")
        sets["updated_at"] = common.now_iso()
        conn.execute(
            f"UPDATE rules SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ? AND list_id = ?",
            (*sets.values(), rule_id, list_id),
        )
    return get_rule(list_id, rule_id)


# ── Running ───────────────────────────────────────────────────────────────────


class _Actor(TypedDict):
    source: str
    client: str


def _act(list_id: int, card_id: int, action: dict) -> None:
    """One action on one card, through the app's own writes, as the Automation person."""
    who: _Actor = {"source": "agent", "client": ACTOR}
    do = action["do"]
    card = boards.get_card(list_id, card_id)
    if card["status"] != "active" and do != "archive":
        return  # an earlier action archived it
    if do == "move":
        boards.move_card(list_id, card_id, action["column"], action.get("position"), **who)
    elif do in ("complete", "reopen"):
        boards.update_card(list_id, card_id, {"completed": do == "complete"}, **who)
    elif do == "assign":
        # Keep who is on it now, but not someone archived since (they can't be assigned again).
        live = {
            r["id"]
            for r in db.get_db().execute("SELECT id FROM people WHERE list_id = ? AND status = 'active'", (list_id,))
        }
        ids = [a["id"] for a in card["assignees"] if a["id"] in live]
        boards.update_card(
            list_id, card_id, {"assignee_ids": ids + [p for p in action["people"] if p not in ids]}, **who
        )
    elif do == "unassign_all":
        boards.update_card(list_id, card_id, {"assignee_ids": []}, **who)
    elif do in ("add_label", "remove_label"):
        ids = [lbl["id"] for lbl in card["labels"]]
        ids = (
            (ids + [action["label"]] if action["label"] not in ids else ids)
            if do == "add_label"
            else [i for i in ids if i != action["label"]]
        )
        boards.update_card(list_id, card_id, {"labels": ids}, **who)
    elif do == "add_subtasks":
        for title in action["titles"]:
            recordings.create(list_id, None, "step", {"title": title}, card_id=card_id, **who)
    elif do == "comment":
        recordings.comment(list_id, action["text"], card_id=card_id, **who)
    elif do == "set_due":
        today = recordings._today(db.get_db(), list_id)
        boards.update_card(
            list_id, card_id, {"due_date": (today + datetime.timedelta(days=action["days"])).isoformat()}, **who
        )
    elif do == "clear_due":
        boards.update_card(list_id, card_id, {"due_date": None}, **who)
    elif do == "archive":
        boards.update_card(list_id, card_id, {"status": "archived"}, **who)
    elif do == "hold":
        boards.update_card(list_id, card_id, {"on_hold": action["on"]}, **who)


def _run(list_id: int, rule: dict, card_ids: list[int]) -> int:
    """Run a rule's actions on each card, outside any other rule; returns cards acted on."""
    token = _running.set(True)
    done, error = 0, None
    try:
        for card_id in card_ids:
            try:
                for action in rule["actions"]:
                    _act(list_id, card_id, action)
                done += 1
            except (ValidationError, NotFoundError) as e:
                error = str(e)
                break
    finally:
        _running.reset(token)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE rules SET runs = runs + ?, last_run_at = ?, last_error = ? WHERE id = ? AND list_id = ?",
            (done, common.now_iso(), error, rule["id"], list_id),
        )
    return done


def fire(list_id: int, board_id: int, event: str, card_id: int, column_id: int | None = None) -> None:
    """After a write: run every active rule of the project whose trigger is `event`
    (and, when it names one, `column_id`) on the card. Inside a rule's own run this
    does nothing: a rule never sets off another."""
    if _running.get():
        return
    rules = [
        _shape(r)
        for r in db.get_db().execute(
            "SELECT * FROM rules WHERE list_id = ? AND board_id = ? AND kind = 'rule' AND status = 'active' "
            "AND json_extract(trigger, '$.on') = ? ORDER BY position, id",
            (list_id, board_id, event),
        )
    ]
    for rule in rules:
        if rule["trigger"].get("column") not in (None, column_id):
            continue
        try:
            _run(list_id, rule, [card_id])
        except Exception:  # never let a rule break the write that fired it
            logger.exception("Rule %s failed", rule["id"])


def _column_cards(list_id: int, column_id: int) -> list[int]:
    """The active cards in a column, for a board button or a scheduled rule."""
    ids = [
        r["id"]
        for r in db.get_db().execute(
            "SELECT id FROM cards WHERE list_id = ? AND column_id = ? AND status = 'active' ORDER BY position, id "
            "LIMIT ?",
            (list_id, column_id, MAX_BUTTON_CARDS + 1),
        )
    ]
    if len(ids) > MAX_BUTTON_CARDS:
        # Every card or none: half a column done, and the same half again next time, helps nobody.
        raise ValidationError(f"That column holds more than {MAX_BUTTON_CARDS} cards: move some out first")
    return ids


def press(list_id: int, rule_id: int, card_id: int | None = None) -> dict:
    """Press a button: a card button acts on `card_id`, a board button on every
    active card in its column. Returns how many cards it acted on."""
    rule = get_rule(list_id, rule_id)
    if rule["status"] != "active":
        raise ValidationError("This button is archived. Restore it first.")
    if rule["kind"] == "card_button":
        if card_id is None:
            raise ValidationError("Which card?")
        card = boards.get_card(list_id, card_id)
        if card["board_id"] != rule["board_id"]:
            raise NotFoundError(f"Card not found: {card_id}")
        ids = [card_id]
    elif rule["kind"] == "board_button":
        ids = _column_cards(list_id, rule["trigger"]["column"])
    else:
        raise ValidationError("A rule runs by itself; only a button is pressed")
    done = _run(list_id, rule, ids)
    return {"rule": get_rule(list_id, rule_id), "cards": done}


def due_tick(now: datetime.datetime | None = None) -> int:
    """The background loop's part: every active due-soon rule, in every account,
    on each open card due within its days (today included) that it has not acted
    on for that due date. Returns how many cards were acted on."""
    conn = db.get_db()
    acted = 0
    for row in conn.execute(
        "SELECT r.* FROM rules r JOIN boards b ON b.id = r.board_id WHERE r.kind = 'rule' "
        "AND r.status = 'active' AND b.status = 'active' AND b.template = 0 "
        "AND json_extract(r.trigger, '$.on') = 'due_soon'"
    ).fetchall():
        list_id, rule = row["list_id"], _shape(row)
        today = recordings._today(conn, list_id) if now is None else now.date()
        until = (today + datetime.timedelta(days=rule["trigger"].get("days", 1))).isoformat()
        cards = conn.execute(
            "SELECT c.id, c.due_date FROM cards c WHERE c.list_id = ? AND c.board_id = ? AND c.status = 'active' "
            "AND c.completed_at IS NULL AND c.template = 0 AND c.due_date IS NOT NULL AND c.due_date <= ? "
            "AND NOT EXISTS (SELECT 1 FROM rule_fired f WHERE f.rule_id = ? AND f.card_id = c.id AND f.key = c.due_date)",
            (list_id, rule["board_id"], until, rule["id"]),
        ).fetchall()
        for card in cards:
            with db.transaction() as tx:
                tx.execute(
                    "INSERT OR IGNORE INTO rule_fired (list_id, rule_id, card_id, key, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (list_id, rule["id"], card["id"], card["due_date"], common.now_iso()),
                )
            acted += _run(list_id, rule, [card["id"]])
    return acted


def occurrence(trigger: dict, tz: str, now: datetime.datetime) -> str | None:
    """When today's run of a scheduled rule is (a UTC stamp), once its day and time
    have come in the account's timezone; None on a day it does not run, or before."""
    zone = ZoneInfo(common.validate_tz(tz))
    local = now.astimezone(zone)
    day, every = local.date(), trigger.get("every")
    if (
        every == "weekday"
        and day.weekday() >= 5
        or every == "week"
        and (day.weekday() + 1) % 7 != trigger.get("day")
        or every == "month"
        and day.day != trigger.get("day")
    ):
        return None
    hour, minute = (int(x) for x in trigger.get("time", "09:00").split(":"))
    # As a real instant, compared as one: a time the clocks skip (02:30 when they spring
    # forward) is the instant it would have been, so it still runs once.
    at = datetime.datetime.combine(day, datetime.time(hour, minute), zone).astimezone(datetime.timezone.utc)
    return common.to_iso(at) if now.astimezone(datetime.timezone.utc) >= at else None


def scheduled_tick(now: datetime.datetime | None = None) -> int:
    """The background loop's part for scheduled rules, in every account: once the
    day and time of a rule's run have come, it acts on every card in its column,
    once (a rule made after today's time first runs at the next one). Returns how
    many cards were acted on."""
    now = now or common.utcnow()
    acted = 0
    for row in (
        db.get_db()
        .execute(
            "SELECT r.*, l.tz FROM rules r JOIN boards b ON b.id = r.board_id JOIN lists l ON l.id = r.list_id "
            "WHERE r.kind = 'rule' AND r.status = 'active' AND b.status = 'active' AND b.template = 0 "
            "AND json_extract(r.trigger, '$.on') = 'scheduled'"
        )
        .fetchall()
    ):
        list_id, rule = row["list_id"], _shape(row)
        due = occurrence(rule["trigger"], row["tz"], now)
        if due is None or max(rule["last_run_at"] or "", rule["created_at"]) >= due:
            continue
        try:
            acted += _run(list_id, rule, _column_cards(list_id, rule["trigger"]["column"]))
        except Exception as e:  # one rule's failure never stops another's: this run is spent, said once
            if not isinstance(e, ValidationError):
                logger.exception("Scheduled rule %s failed", rule["id"])
            error = str(e) if isinstance(e, ValidationError) else "Something went wrong; it will run again next time."
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE rules SET last_run_at = ?, last_error = ? WHERE id = ? AND list_id = ?",
                    (common.now_iso(), error, rule["id"], list_id),
                )
    return acted
