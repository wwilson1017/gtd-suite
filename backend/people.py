"""Projects GTD — the account's people: who wrote a thing, and who it is for.

Basecamp is about people, and an account here is one person and their AI tools.
So there are three kinds:

    me      the account's person, made the first time they write
    ai      each AI tool that has written, named by its client ("Claude")
    person  anyone the person adds by name, to assign and mention; they do not
            sign in

A browser is always "me"; the agent link is the AI tool it names (or "AI tool").
Every write that needs an author finds or makes its person inside the caller's
transaction (`*_in`). Nothing is deleted: a person is archived.

# simplification: added people cannot sign in; per-project invites are their own phase
"""

import hashlib

from backend import common, db
from backend.common import NotFoundError, ValidationError

KINDS = ("me", "person", "ai")
# Avatar colours, picked from the name so a person keeps theirs.
COLORS = (
    "#e5484d",
    "#f76b15",
    "#ffc53d",
    "#46a758",
    "#12a594",
    "#0090ff",
    "#3e63dd",
    "#8e4ec6",
    "#d6409f",
    "#978365",
    "#5b5bd6",
    "#29a383",
)
FIELDS = frozenset({"name", "title", "color", "status"})
MAX_PEOPLE = 200
# Places kept for the two people the app makes itself, "me" and the "AI tool"
# that unknown tools write as once the account is full, so neither breaks the cap.
_KEPT = 2
AI_DEFAULT = "AI tool"


def _color(name: str) -> str:
    return COLORS[int(hashlib.sha256(name.lower().encode()).hexdigest(), 16) % len(COLORS)]


def _row(conn, list_id: int, person_id: int) -> dict:
    row = conn.execute("SELECT * FROM people WHERE id = ? AND list_id = ?", (person_id, list_id)).fetchone()
    if row is None:
        raise NotFoundError(f"Person not found: {person_id}")
    return dict(row)


def _find_or_make(conn, list_id: int, kind: str, name: str) -> int:
    row = conn.execute(
        "SELECT id FROM people WHERE list_id = ? AND kind = ? AND lower(name) = lower(?)", (list_id, kind, name)
    ).fetchone()
    if row:
        return row["id"]
    now = common.now_iso()
    return conn.execute(
        "INSERT INTO people (list_id, kind, name, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (list_id, kind, name, _color(name), now, now),
    ).lastrowid


def me_in(conn, list_id: int) -> int:
    """The account's own person, made on first use: named after the list, or "Me"."""
    row = conn.execute("SELECT id FROM people WHERE list_id = ? AND kind = 'me'", (list_id,)).fetchone()
    if row:
        return row["id"]
    name = conn.execute("SELECT name FROM lists WHERE id = ?", (list_id,)).fetchone()["name"]
    return _find_or_make(conn, list_id, "me", (name or "").strip() or "Me")


def actor_in(conn, list_id: int, client: str | None, source: str) -> int:
    """Who is writing: "me" from the web app, else the AI tool by its client name.
    Once the account holds MAX_PEOPLE, a tool not met before writes as "AI tool":
    the name is the client's own say-so, so it never grows the list past the cap."""
    if source == "ui":
        return me_in(conn, list_id)
    name = common.clean_source_client(client) or AI_DEFAULT
    known = conn.execute(
        "SELECT id FROM people WHERE list_id = ? AND kind = 'ai' AND lower(name) = lower(?)", (list_id, name)
    ).fetchone()
    if (
        known is None
        and conn.execute("SELECT COUNT(*) FROM people WHERE list_id = ?", (list_id,)).fetchone()[0]
        >= MAX_PEOPLE - _KEPT
    ):
        name = AI_DEFAULT
    return _find_or_make(conn, list_id, "ai", name)


def viewer(conn, list_id: int, client: str | None, source: str) -> int | None:
    """Who is reading, as actor_in names a writer, without making anyone: None
    for an AI tool that has never written (it has no drafts to see)."""
    if source == "ui":
        row = conn.execute("SELECT id FROM people WHERE list_id = ? AND kind = 'me'", (list_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM people WHERE list_id = ? AND kind = 'ai' AND lower(name) = lower(?)",
            (list_id, common.clean_source_client(client) or AI_DEFAULT),
        ).fetchone()
    return row["id"] if row else None


def list_people(list_id: int, status: str = "active") -> list[dict]:
    """The account's people: me first, then everyone else by name."""
    return [
        dict(r)
        for r in db.get_db().execute(
            "SELECT * FROM people WHERE list_id = ? AND status = ? ORDER BY kind != 'me', lower(name)",
            (list_id, status),
        )
    ]


def get(list_id: int, person_id: int) -> dict:
    return _row(db.get_db(), list_id, person_id)


def add(list_id: int, name: str, title: str = "") -> dict:
    """Add someone by name, to assign things to and mention."""
    name = common.validate_short(name, "name")
    if not name:
        raise ValidationError("name is required")
    title = common.validate_short(title, "title")
    with db.transaction() as conn:
        if conn.execute(
            "SELECT 1 FROM people WHERE list_id = ? AND kind = 'person' AND lower(name) = lower(?)", (list_id, name)
        ).fetchone():
            raise ValidationError(f'"{name}" is already here')
        if (
            conn.execute("SELECT COUNT(*) FROM people WHERE list_id = ?", (list_id,)).fetchone()[0]
            >= MAX_PEOPLE - _KEPT
        ):
            raise ValidationError(f"An account holds at most {MAX_PEOPLE - _KEPT} people")
        person_id = _find_or_make(conn, list_id, "person", name)
        if title:
            conn.execute("UPDATE people SET title = ? WHERE id = ?", (title, person_id))
    return get(list_id, person_id)


def update(list_id: int, person_id: int, fields: dict) -> dict:
    """Rename, retitle, recolour, archive or restore someone. "me" can be renamed
    but not archived."""
    unknown = sorted(set(fields) - FIELDS)
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(unknown)}. Valid: {', '.join(sorted(FIELDS))}")
    with db.transaction() as conn:
        person = _row(conn, list_id, person_id)
        sets = {}
        if "name" in fields:
            sets["name"] = common.validate_short(fields["name"], "name")
            if not sets["name"]:
                raise ValidationError("name is required")
            if conn.execute(
                "SELECT 1 FROM people WHERE list_id = ? AND kind = ? AND lower(name) = lower(?) AND id != ?",
                (list_id, person["kind"], sets["name"], person_id),
            ).fetchone():
                raise ValidationError(f'"{sets["name"]}" is already here')
        if "title" in fields:
            sets["title"] = common.validate_short(fields["title"], "title")
        if "color" in fields:
            if fields["color"] not in COLORS:
                raise ValidationError(f"color must be one of {', '.join(COLORS)}")
            sets["color"] = fields["color"]
        if "status" in fields:
            if fields["status"] not in ("active", "archived"):
                raise ValidationError("status must be 'active' or 'archived'")
            if person["kind"] == "me" and fields["status"] != "active":
                raise ValidationError("You can't archive yourself")
            sets["status"] = fields["status"]
        if sets:
            sets["updated_at"] = common.now_iso()
            conn.execute(
                f"UPDATE people SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?", (*sets.values(), person_id)
            )
    return get(list_id, person_id)


def resolve_in(conn, list_id: int, refs) -> list[int]:
    """People named by id or by name (any case), as ids, in the order given. An
    AI tool's name finds its person; an unknown name is refused, never invented."""
    if refs in (None, ""):
        return []
    if not isinstance(refs, list):
        refs = [refs]
    out: list[int] = []
    for ref in refs:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
            row = conn.execute(
                "SELECT id FROM people WHERE id = ? AND list_id = ? AND status = 'active'", (int(ref), list_id)
            ).fetchone()
        else:
            text = str(ref or "").strip()
            if text.lower() in ("me", "myself"):
                me = me_in(conn, list_id)
                if me not in out:
                    out.append(me)
                continue
            row = conn.execute(
                "SELECT id FROM people WHERE list_id = ? AND lower(name) = lower(?) AND status = 'active' "
                "ORDER BY kind = 'me' DESC, kind = 'person' DESC LIMIT 1",
                (list_id, text),
            ).fetchone()
        if row is None:
            names = ", ".join(p["name"] for p in list_people(list_id)) or "none yet"
            raise ValidationError(f"Nobody here is called {ref}. People: {names}")
        if row["id"] not in out:
            out.append(row["id"])
    return out
