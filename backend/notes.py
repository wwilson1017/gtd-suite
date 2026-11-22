"""Notes GTD — one list's notes: Keep-style cards holding markdown.

Like boards.py, every function takes the `list_id` first and scopes every query
by it, and every write is one ``db.transaction()``. Nothing is deleted: a note is
archived (status 'archived') and can be brought back.

A note's ``version`` goes up on every write. Changing the title or body through
`update` names the version it was read at, and an older one is refused
(ConflictError), so a browser's autosave never overwrites what an agent just
wrote, nor an agent's rewrite the person's typing. `edit` (an exact string that
occurs once) and `append` change only what they name, so they need no version.

Tags are the body's inline #hashtags, derived on every write and never written
directly: the body is the one source of truth.

# simplification: search is AND-ed LIKE over title and body — fine for one person's notes; FTS5 when ranking matters
"""

import json
import re

from backend.paid import caps as paid_caps
from backend.paid import plans
from backend.paid import billing
from backend import apps, common, db, settings
from backend.common import ConflictError, NotFoundError, ValidationError

STATUSES = ("active", "archived")
COLORS = ("", "red", "orange", "yellow", "green", "teal", "blue", "purple", "gray")
FIELDS = frozenset({"title", "body", "color", "pinned", "status"})
PAGE = 500  # notes per search page, at most
SNIPPET_CHARS = 160

_COLS = (
    "id, title, body, tags, color, pinned, status, version, source, source_client, edited_by, created_at, updated_at"
)
# Fenced code blocks (to their closing fence, or the end) and inline code spans:
# a # inside them is code, not a tag.
_CODE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?(?:^[ \t]*\1[ \t]*$|\Z)|`[^`\n]*`", re.M | re.S)
# A # at a line's start or after whitespace, then letters, digits, _, / or -. A
# heading's "# " has a space after it, so it is not a tag.
_TAG = re.compile(r"(?<!\S)#([\w/-]+)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def tags_of(body: str) -> list[str]:
    """The body's #hashtags outside code, lowercased, in first-seen order. Digits
    alone (#1, an issue number) are not a tag."""
    tags: list[str] = []
    for match in _TAG.finditer(_CODE.sub(" ", body)):
        tag = match.group(1).strip("/-").lower()
        if tag and not tag.isdigit() and tag not in tags:
            tags.append(tag)
    return tags


def snippet(note: dict, query: str = "") -> str:
    """About SNIPPET_CHARS of the body, on one line: around the first word of
    `query` it holds, else from the start."""
    body = note["body"]
    low = body.lower()
    hits = [i for word in str(query or "").split() if (i := low.find(word.lower())) >= 0]
    start = max(0, min(hits) - SNIPPET_CHARS // 3) if hits else 0
    text = " ".join(body[start : start + SNIPPET_CHARS].split())
    return ("…" if start else "") + text + ("…" if start + SNIPPET_CHARS < len(body) else "")


# ── Checks ────────────────────────────────────────────────────────────────────


def _color(value) -> str:
    color = str(value or "").strip().lower()
    if color not in COLORS:
        raise ValidationError(f"Invalid color '{value}'. Valid: {', '.join(c for c in COLORS if c)}, or empty for none")
    return color


def _status(status) -> str:
    if status not in STATUSES:
        raise ValidationError(f"Invalid status '{status}'. Valid: {', '.join(STATUSES)}")
    return status


def _check_cap(conn, list_id: int) -> None:
    """Refuse one more note once the list holds its cap (common.note_cap_for).
    Archived notes count: nothing is ever deleted."""
    row = conn.execute(f"SELECT {paid_caps.PLAN_COLUMNS} FROM lists WHERE id = ?", (list_id,)).fetchone()
    verified, hosted = bool(row and row["email_verified_at"]), settings.open_signup()
    plan = plans.of(row) if row else None
    cap = common.note_cap_for(verified, hosted, plan)
    n = conn.execute("SELECT COUNT(*) FROM notes WHERE list_id = ?", (list_id,)).fetchone()[0]
    if n < cap:
        return
    if hosted and not verified:
        raise ValidationError(
            f"This list holds {cap} notes until an email is confirmed in {apps.settings_page()}. Nothing was changed."
        )
    raise ValidationError(
        f"A list holds at most {cap} notes.{billing.upsell(hosted and not plan)} Nothing was changed."
    )


def _out(row) -> dict:
    return {**dict(row), "tags": json.loads(row["tags"]), "pinned": bool(row["pinned"])}


def _get(conn, list_id: int, note_id: int) -> dict:
    row = conn.execute(f"SELECT {_COLS} FROM notes WHERE id = ? AND list_id = ?", (note_id, list_id)).fetchone()
    if row is None:
        raise NotFoundError(f"Note not found: {note_id}")
    return _out(row)


def _write(conn, note_id: int, sets: dict, by: str | None) -> None:
    """Write `sets` (the body's tags with it), stamp who and when, and bump the
    version. `by` is the AI tool making the change; None is the app."""
    if "body" in sets:
        sets["tags"] = json.dumps(tags_of(sets["body"]))
    sets = {**sets, "edited_by": by, "updated_at": common.now_iso()}
    conn.execute(
        f"UPDATE notes SET {', '.join(f'{k} = ?' for k in sets)}, version = version + 1 WHERE id = ?",
        (*sets.values(), note_id),
    )


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ── Reads ─────────────────────────────────────────────────────────────────────


def get(list_id: int, note_id: int) -> dict:
    return _get(db.get_db(), list_id, note_id)


def search(
    list_id: int, query: str = "", tag: str = "", status: str = "active", limit: int = 100, offset: int = 0
) -> dict:
    """Notes holding every word of `query` (title or body, any case) and `tag`:
    pinned first, then those with every word in the title, then the most recently
    changed. `status` is active, archived or all."""
    if status != "all":
        _status(status)
    if not 1 <= limit <= PAGE:
        raise ValidationError(f"limit must be between 1 and {PAGE}")
    if offset < 0:
        raise ValidationError("offset must be 0 or more")
    params: list[int | str] = [list_id]
    where = ["list_id = ?"]
    if status != "all":
        where.append("status = ?")
        params.append(status)
    words = str(query or "").split()
    for word in words:
        where.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
        params += [_like(word)] * 2
    tag = str(tag or "").strip().lstrip("#").lower()
    if tag:
        where.append("EXISTS (SELECT 1 FROM json_each(notes.tags) WHERE value = ?)")
        params.append(tag)
    in_title = " AND ".join(["title LIKE ? ESCAPE '\\'"] * len(words))
    rows = (
        db.get_db()
        .execute(
            f"SELECT {_COLS} FROM notes WHERE {' AND '.join(where)} ORDER BY pinned DESC, "
            + (f"({in_title}) DESC, " if words else "")
            + "updated_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, *[_like(w) for w in words], limit, offset),
        )
        .fetchall()
    )
    notes = [_out(r) for r in rows]
    return {"notes": notes, "count": len(notes), "next_offset": offset + limit if len(notes) == limit else None}


def tag_counts(list_id: int) -> list[dict]:
    """Each tag of the active notes with how many carry it, the most used first."""
    return [
        dict(r)
        for r in db.get_db().execute(
            "SELECT t.value AS tag, COUNT(*) AS count FROM notes n, json_each(n.tags) t "
            "WHERE n.list_id = ? AND n.status = 'active' GROUP BY t.value ORDER BY count DESC, tag",
            (list_id,),
        )
    ]


# ── Writes ────────────────────────────────────────────────────────────────────


def create(
    list_id: int,
    title: str = "",
    body: str = "",
    *,
    color: str = "",
    pinned: bool = False,
    source: str = "ui",
    source_client: str | None = None,
) -> dict:
    title = common.validate_short(title, "title")
    body = common.validate_notes(body, "body")
    if not title and not body.strip():
        raise ValidationError("A note needs a title or a body")
    color = _color(color)
    client = common.clean_source_client(source_client)
    with db.transaction() as conn:
        _check_cap(conn, list_id)
        now = common.now_iso()
        note_id = conn.execute(
            "INSERT INTO notes (list_id, title, body, tags, color, pinned, source, source_client, "
            "edited_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                list_id,
                title,
                body,
                json.dumps(tags_of(body)),
                color,
                int(bool(pinned)),
                source,
                client,
                (client or "AI tool") if source == "agent" else None,
                now,
                now,
            ),
        ).lastrowid
        assert note_id is not None  # A successful INSERT into a rowid table.
        return _get(conn, list_id, note_id)


def update(list_id: int, note_id: int, fields: dict, version: int | None = None, by: str | None = None) -> dict:
    """Change a note's title, body, colour, pin or status (archive or restore).
    Changing the title or body needs `version`, the version it was read at; with
    `version`, a note changed since is refused (ConflictError). `by`: the AI tool
    making the change, None for the app."""
    unknown = sorted(set(fields) - FIELDS)
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(unknown)}. Valid: {', '.join(sorted(FIELDS))}")
    if version is None and ("title" in fields or "body" in fields):
        raise ValidationError("Changing the title or body needs the note's version: read the note and send its version")
    sets: dict = {}
    if "title" in fields:
        sets["title"] = common.validate_short(fields["title"], "title")
    if "body" in fields:
        sets["body"] = common.validate_notes(fields["body"], "body")
    if "color" in fields:
        sets["color"] = _color(fields["color"])
    if "pinned" in fields:
        sets["pinned"] = int(bool(fields["pinned"]))
    if "status" in fields:
        sets["status"] = _status(fields["status"])
    with db.transaction() as conn:
        note = _get(conn, list_id, note_id)
        if version is not None and version != note["version"]:
            raise ConflictError(
                f"This note changed since version {version}; it is now version "
                f"{note['version']}. Nothing was saved: read it again."
            )
        if not sets.get("title", note["title"]) and not sets.get("body", note["body"]).strip():
            raise ValidationError("A note needs a title or a body")
        _write(conn, note_id, sets, by)
        return _get(conn, list_id, note_id)


def edit(list_id: int, note_id: int, old: str, new: str, by: str | None = None) -> dict:
    """Replace `old` in the body with `new`. `old` must occur exactly once."""
    old, new = str(old or ""), str(new or "")
    if not old:
        raise ValidationError("old_str is required: the exact text to replace")
    with db.transaction() as conn:
        note = _get(conn, list_id, note_id)
        found = note["body"].count(old)
        if found == 0:
            raise ValidationError(
                "old_str was not found in the note's body. Read the note and "
                "copy the text exactly, spaces and line breaks included."
            )
        if found > 1:
            raise ValidationError(
                f"old_str was found {found} times: include more of the surrounding text so it occurs once."
            )
        _write(conn, note_id, {"body": common.validate_notes(note["body"].replace(old, new, 1), "body")}, by)
        return _get(conn, list_id, note_id)


def append(list_id: int, note_id: int, text: str, by: str | None = None) -> dict:
    """Add `text` to the end of the body: on the next line when both the body's
    last line and the text's first are list items (one more checklist item),
    else after a blank line, so the text cannot merge into what is there."""
    text = str(text or "").strip("\n")
    if not text.strip():
        raise ValidationError("Nothing to append")
    with db.transaction() as conn:
        note = _get(conn, list_id, note_id)
        body = note["body"].rstrip()
        last = body.rsplit("\n", 1)[-1]
        joint = "\n" if _LIST_ITEM.match(last) and _LIST_ITEM.match(text) else "\n\n"
        _write(conn, note_id, {"body": common.validate_notes(f"{body}{joint}{text}" if body else text, "body")}, by)
        return _get(conn, list_id, note_id)
