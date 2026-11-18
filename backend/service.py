"""todo-gtd — service layer.

Todo/project/area CRUD and queries for one list. Every public function takes the
`list_id` first and every query is scoped ``WHERE list_id = ?`` — the router
and the MCP server resolve the id from the token in the address, so a caller
can never reach another list's rows.

Every write runs inside ``db.transaction()`` (write lock + BEGIN IMMEDIATE), which
is what makes completion and its recurrence spawn race-safe: two concurrent
completes serialize, the second sees status='done' and does not spawn again.

There are no deletes. Archiving is status 'dropped'.

Validation errors raise common.ValidationError with a user-facing message.
"""

import datetime
import json
from typing import cast

from backend.paid import caps as paid_caps
from backend.paid import plans
from backend.paid import billing
from backend import apps, common, db, settings
from backend.common import (
    AREA_FIELDS,
    MAX_TEXT_CHARS,
    PROJECT_FIELDS,
    TICKLE_STALE_COUNT,
    TODO_FIELDS,
    TODO_SOURCES,
    TODO_STATUSES,
    ConflictError,
    NotFoundError,
    ValidationError,
)

# A todo in a project shows its project's area unless it has its own:
# `area_id` is the todo's own (the column updates write), `effective_area_id`
# and `area_name` are what it shows under.
_EFFECTIVE_AREA = "COALESCE(t.area_id, p.area_id)"
_SELECT_TODO = (
    f"SELECT t.*, p.name AS project_name, {_EFFECTIVE_AREA} AS effective_area_id, "
    "a.name AS area_name FROM todos t "
    "LEFT JOIN projects p ON t.project_id = p.id "
    f"LEFT JOIN areas a ON a.id = {_EFFECTIVE_AREA}"
)
# "Not waiting on a revisit date", binding the list's today. A todo deferred to a
# future `revisit_on` is hidden from the WORKING lists (list_todos, Today, the
# status counts, the brain tickle, the weekly review's copies of those lists)
# until that day, then shows as usual. Record views and follow-up checks
# (get_todo, a project's page, open count and "no next action", the review's
# `upcoming`, EXPORT) do not apply it: a scheduled return is still there.
_NOT_DEFERRED = "(t.revisit_on IS NULL OR t.revisit_on <= ?)"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _todo_dict(row) -> dict:
    d = dict(row)
    for key in ("tags", "people"):
        try:
            d[key] = json.loads(d.get(key) or "[]")
        except (ValueError, TypeError):
            d[key] = []
    d["star"] = bool(d.get("star"))
    d["auto_star_on_due"] = bool(d.get("auto_star_on_due"))
    return d


def _tags_json(tags: list[str]) -> str:
    # ensure_ascii=False so search's LIKE over the stored text matches non-ASCII tags.
    return json.dumps(tags, ensure_ascii=False)


def _flag(value, field: str) -> int:
    """A boolean field as 0/1. bulk_update's `fields` is an untyped dict, so a
    string like "false" reaches here — truthiness would silently turn it ON."""
    if value is None or value in (0, 1):  # True == 1, False == 0
        return 1 if value else 0
    raise ValidationError(f"{field} must be true or false")


def _list_tz(conn, list_id: int) -> str:
    row = conn.execute("SELECT tz FROM lists WHERE id = ?", (list_id,)).fetchone()
    return row["tz"] if row else "UTC"


def _list_name(conn, list_id: int) -> str:
    row = conn.execute("SELECT name FROM lists WHERE id = ?", (list_id,)).fetchone()
    return row["name"] if row else ""


# What a full list says, by table, when confirming an email would not raise the cap.
_FULL = {
    "todos": "This list is full ({} todos, counting done and archived ones).",
    "projects": "This list has reached its limit of {} projects (counting completed and archived ones).",
    "areas": "This list has reached its limit of {} areas (counting archived ones).",
}


def _check_cap(conn, list_id: int, table: str) -> None:
    """Refuse one more row in ``table`` (todos, projects or areas) once the list
    holds its cap, which common.caps_for picks from the hosting mode and whether
    the list's email is confirmed. Every creation path calls this. The caller
    holds the write transaction, so the count cannot go stale."""
    row = conn.execute(
        f"SELECT email_verified_at, {paid_caps.PLAN_COLUMNS} FROM lists WHERE id = ?", (list_id,)
    ).fetchone()
    verified, hosted = bool(row and row["email_verified_at"]), settings.open_signup()
    plan = plans.of(row) if row else None
    cap = common.caps_for(verified, hosted, plan)[tuple(_FULL).index(table)]
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE list_id = ?", (list_id,)).fetchone()[0]
    if n < cap:
        return
    if hosted and not verified:
        raise ValidationError(
            f"This list holds {cap} {table} until an email is confirmed in {apps.settings_page()}. Nothing was changed."
        )
    raise ValidationError(f"{_FULL[table].format(cap)}{billing.upsell(hosted and not plan)} Nothing was changed.")


def _resolve_project_id(conn, list_id: int, name: str) -> int:
    """Id of the list's project named `name`, creating it (active) if missing.
    Caller holds the write transaction."""
    row = conn.execute(
        "SELECT id FROM projects WHERE list_id = ? AND lower(name) = lower(?)",
        (list_id, name),
    ).fetchone()
    if row:
        return row["id"]
    _check_cap(conn, list_id, "projects")
    now = common.now_iso()
    return conn.execute(
        "INSERT INTO projects (list_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (list_id, name, now, now),
    ).lastrowid


def _check_ref(conn, list_id: int, kind: str, ref_id) -> int | None:
    """Validate a `project_id` / `area_id` (`kind` is 'project' or 'area')."""
    if ref_id in (None, "", 0):
        return None
    try:
        # bulk_update's `fields` is an untyped dict (unlike TodoUpdate), so a
        # non-numeric id reaches here — must be a 400, not a 500.
        rid = int(ref_id)
    except (TypeError, ValueError):
        raise ValidationError(f"{kind}_id must be an integer, got {ref_id!r}")
    # Scoped to the list: another list's row is "not found", never attachable.
    if not conn.execute(f"SELECT id FROM {kind}s WHERE id = ? AND list_id = ?", (rid, list_id)).fetchone():
        raise ValidationError(f"{kind.capitalize()} id not found: {rid}")
    return rid


def _named_id(conn, list_id: int, kind: str, term) -> int | None:
    """A list filter's project/area term as an id: digits are the id itself,
    anything else is the name. None when the list has no such name."""
    term = str(term).strip()
    # ASCII digits only (isdigit() accepts "²", int() rejects it) and short enough for SQLite.
    if term.isascii() and term.isdigit() and len(term) <= 18:
        return int(term)
    row = conn.execute(
        f"SELECT id FROM {kind}s WHERE list_id = ? AND lower(name) = lower(?)", (list_id, term)
    ).fetchone()
    return row["id"] if row else None


# ── Todos ─────────────────────────────────────────────────────────────────────

MAX_BULK_CREATE = 100  # todos per bulk_create call


def _create_in(
    conn,
    list_id: int,
    title: str,
    *,
    notes: str = "",
    project: str | None = None,
    project_id: int | None = None,
    area_id: int | None = None,
    context: str = "",
    tags: list[str] | None = None,
    people: list[str] | None = None,
    status: str = "inbox",
    star=False,
    due_date: str | None = None,
    revisit_on: str | None = None,
    repeat: str = "",
    auto_star_on_due=False,
    source: str = "agent",
    source_client: str | None = None,
) -> int:
    """Validate and insert one todo inside the caller's write transaction;
    returns its id."""
    if title is not None and not isinstance(title, str):
        raise ValidationError("title must be a string")
    title = (title or "").strip()
    if not title:
        raise ValidationError("title is required")
    if len(title) > MAX_TEXT_CHARS:
        raise ValidationError(f"title too long (max {MAX_TEXT_CHARS} characters)")
    common.validate_status(status)
    if source not in TODO_SOURCES:
        raise ValidationError(f"Invalid source '{source}'. Valid: {', '.join(TODO_SOURCES)}")
    due = common.validate_due(due_date)
    revisit = common.validate_due(revisit_on, "revisit_on")
    rep = common.validate_repeat(repeat)
    tag_list = common.validate_tags(tags)
    people_list = common.validate_people(people)
    notes = common.validate_notes(notes)
    context = common.validate_short(context, "context")

    _check_cap(conn, list_id, "todos")
    if project_id is not None:
        pid = _check_ref(conn, list_id, "project", project_id)
    elif project and str(project).strip():
        pid = _resolve_project_id(conn, list_id, common.validate_short(project, "project"))
    else:
        pid = None
    aid = _check_ref(conn, list_id, "area", area_id)
    now = common.now_iso()
    return conn.execute(
        """INSERT INTO todos
           (list_id, title, notes, project_id, area_id, context, tags, people, status,
            star, due_date, revisit_on, repeat, auto_star_on_due, source, source_client,
            created_at, updated_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            list_id,
            title,
            notes,
            pid,
            aid,
            context,
            _tags_json(tag_list),
            _tags_json(people_list),
            status,
            _flag(star, "star"),
            due,
            revisit,
            rep,
            _flag(auto_star_on_due, "auto_star_on_due"),
            source,
            common.clean_source_client(source_client),
            now,
            now,
            now if status == "done" else None,
        ),
    ).lastrowid


def create_todo(list_id: int, title: str, **fields) -> dict:
    """Create one todo; `fields` are _create_in's keyword arguments."""
    with db.transaction() as conn:
        new_id = _create_in(conn, list_id, title, **fields)
    return cast(dict, get_todo(list_id, new_id))  # The row was just inserted.


def bulk_create(list_id: int, todos: list[dict], *, source: str = "agent", source_client: str | None = None) -> dict:
    """Create many todos in one transaction, each exactly as create_todo would
    (so a 'done' item is stamped completed and never spawns a repeat). All or
    nothing: the first bad item rolls the batch back and is named by position.
    The per-list caps hold across the batch because each insert re-counts."""
    if not isinstance(todos, list) or not todos:
        raise ValidationError("todos is required")
    if len(todos) > MAX_BULK_CREATE:
        raise ValidationError(f"too many todos (max {MAX_BULK_CREATE} per call)")
    ids: list[int] = []
    with db.transaction() as conn:
        for i, item in enumerate(todos):
            try:
                if not isinstance(item, dict):
                    raise ValidationError("must be an object with a title")
                # An omitted field and a null one mean the same: the default.
                fields = {k: v for k, v in item.items() if v is not None}
                if fields:  # an empty item falls through to "title is required"
                    _check_fields(fields)
                ids.append(
                    _create_in(
                        conn, list_id, fields.pop("title", ""), **fields, source=source, source_client=source_client
                    )
                )
            except ValidationError as e:
                raise ValidationError(f"todos[{i}]: {e} (nothing in this batch was created)")
    return {"created": len(ids), "ids": ids}


def get_todo(list_id: int, todo_id: int) -> dict | None:
    row = db.get_db().execute(_SELECT_TODO + " WHERE t.id = ? AND t.list_id = ?", (todo_id, list_id)).fetchone()
    return _todo_dict(row) if row else None


def _apply_update(conn, list_id: int, todo_id: int, fields: dict) -> bool:
    """Apply a validated field update to one todo inside the caller's write
    transaction, so a completion transition is detected exactly once; spawns the
    next occurrence of a repeating todo on that transition. Returns False if the
    todo doesn't exist (or isn't in the caller's list — indistinguishable on purpose).

    `source` / `source_client` are not updatable: they record who created the row."""
    row = conn.execute("SELECT status FROM todos WHERE id = ? AND list_id = ?", (todo_id, list_id)).fetchone()
    if not row:
        return False
    prior_status = row["status"]
    now = common.now_iso()

    sets: list[str] = []
    params: list = []
    if "title" in fields:
        if fields["title"] is not None and not isinstance(fields["title"], str):
            raise ValidationError("title must be a string")
        title = (fields["title"] or "").strip()
        if not title:
            raise ValidationError("title cannot be empty")
        if len(title) > MAX_TEXT_CHARS:
            raise ValidationError(f"title too long (max {MAX_TEXT_CHARS} characters)")
        sets.append("title = ?")
        params.append(title)
    if "notes" in fields:
        sets.append("notes = ?")
        params.append(common.validate_notes(fields["notes"]))
    if "project_id" in fields:
        sets.append("project_id = ?")
        params.append(_check_ref(conn, list_id, "project", fields["project_id"]))
    elif "project" in fields:
        name = common.validate_short(fields["project"], "project")
        sets.append("project_id = ?")
        params.append(_resolve_project_id(conn, list_id, name) if name else None)
    if "context" in fields:
        sets.append("context = ?")
        params.append(common.validate_short(fields["context"], "context"))
    if "area_id" in fields:
        sets.append("area_id = ?")
        params.append(_check_ref(conn, list_id, "area", fields["area_id"]))
    if "tags" in fields:
        sets.append("tags = ?")
        params.append(_tags_json(common.validate_tags(fields["tags"])))
    if "people" in fields:
        sets.append("people = ?")
        params.append(_tags_json(common.validate_people(fields["people"])))
    if "star" in fields:
        sets.append("star = ?")
        params.append(_flag(fields["star"], "star"))
    if "due_date" in fields:
        sets.append("due_date = ?")
        params.append(common.validate_due(fields["due_date"]))
    if "revisit_on" in fields:
        sets.append("revisit_on = ?")
        params.append(common.validate_due(fields["revisit_on"], "revisit_on"))
    if "repeat" in fields:
        sets.append("repeat = ?")
        params.append(common.validate_repeat(fields["repeat"]))
    if "auto_star_on_due" in fields:
        sets.append("auto_star_on_due = ?")
        params.append(_flag(fields["auto_star_on_due"], "auto_star_on_due"))
    just_completed = False
    if "status" in fields:
        status = common.validate_status(fields["status"])
        sets.append("status = ?")
        params.append(status)
        if status == "done":
            if prior_status != "done":
                sets.append("completed_at = ?")
                params.append(now)
                just_completed = True
        else:
            sets.append("completed_at = NULL")
    sets.append("updated_at = ?")
    params.append(now)
    updated = conn.execute(
        f"UPDATE todos SET {', '.join(sets)} WHERE id = ? AND list_id = ? RETURNING *",
        (*params, todo_id, list_id),
    ).fetchall()[0]
    if just_completed:
        _spawn_next_occurrence(conn, dict(updated), prior_status)
    return True


def _spawn_next_occurrence(conn, todo: dict, prior_status: str) -> None:
    """Completing a repeating todo creates its next occurrence: same fields,
    due date advanced, star cleared (today's priority doesn't carry over).
    Reads the POST-update row so edits saved together with the completion
    carry — in particular, clearing `repeat` while completing must not spawn.

    The one exception to the cleared star is the opt-in `auto_star_on_due`:
    when the occurrence being spawned is due TODAY — i.e. this one was
    completed exactly ONE interval late — it comes back already starred instead
    of waiting to be re-starred by hand. Two or more intervals late re-anchors
    past today and does not star. The rule carries forward with the todo, so it
    keeps applying to every later occurrence.

    Provenance (`source`, `source_client`) is copied: the next occurrence was
    created by whoever created the repeating todo. The revisit date and the
    tickle bookkeeping belong to the occurrence that was completed and are not."""
    if not todo.get("repeat"):
        return
    # The total cap applies here too, or completing in a loop would grow a list
    # without bound. Raising rolls back the completion along with the spawn.
    try:
        _check_cap(conn, todo["list_id"], "todos")
    except ValidationError as e:
        raise ValidationError(f"{e} Clear the repeat to complete this todo.")
    status = prior_status if prior_status not in ("done", "dropped") else "next_action"
    auto_star = bool(todo.get("auto_star_on_due"))
    # ONE clock read, shared with the comparison below — two reads could
    # straddle midnight and disagree about whether the spawn is due today.
    today = common.business_today(_list_tz(conn, todo["list_id"]))
    next_due = common.next_due(todo["repeat"], todo.get("due_date"), today)
    now = common.now_iso()
    conn.execute(
        """INSERT INTO todos
           (list_id, title, notes, project_id, area_id, context, tags, people, status, star,
            due_date, repeat, auto_star_on_due, source, source_client,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            todo["list_id"],
            todo["title"],
            todo["notes"],
            todo["project_id"],
            todo["area_id"],
            todo["context"],
            todo["tags"],
            todo["people"],
            status,
            1 if auto_star and next_due == today.isoformat() else 0,
            next_due,
            todo["repeat"],
            1 if auto_star else 0,
            todo["source"],
            todo["source_client"],
            now,
            now,
        ),
    )


def _check_fields(fields: dict, valid_fields: frozenset = TODO_FIELDS) -> None:
    if not fields:
        raise ValidationError("No fields to update")
    unknown = set(fields) - valid_fields
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(valid_fields))}")


def update_todo(list_id: int, todo_id: int, fields: dict) -> dict | None:
    """Update one todo. Returns the updated todo, or None if not found."""
    _check_fields(fields)
    with db.transaction() as conn:
        found = _apply_update(conn, list_id, int(todo_id), fields)
    return get_todo(list_id, todo_id) if found else None


def bulk_update(list_id: int, ids: list[int], fields: dict, *, all_or_nothing: bool = False) -> dict:
    """Apply the same field update to many todos in one transaction.

    Per-id loop (never one UPDATE ... WHERE id IN (...)) so each repeating
    todo in a bulk-complete spawns its own next occurrence. `all_or_nothing`:
    an id not in this list rolls the whole batch back (Agent Commands'
    BULK_UPDATE); otherwise it is reported in `not_found`.
    """
    _check_fields(fields)
    if not ids:
        raise ValidationError("ids is required")
    if len(ids) > 500:
        # The HTTP model caps this, but the agent tools bypass Pydantic —
        # the service is the one boundary both paths share.
        raise ValidationError("too many ids (max 500)")
    try:
        id_list = sorted(int(i) for i in ids)
    except (TypeError, ValueError):
        raise ValidationError("ids must be integers")
    updated: list[int] = []
    not_found: list[int] = []
    with db.transaction() as conn:
        for todo_id in id_list:
            if _apply_update(conn, list_id, todo_id, fields):
                updated.append(todo_id)
            else:
                not_found.append(todo_id)
        if all_or_nothing and not_found:
            raise NotFoundError(f"Todo not found: {', '.join(map(str, not_found))} (nothing was changed)")
    return {"updated": updated, "not_found": not_found}


def rename_context(list_id: int, old: str, new: str, *, merge: bool = False) -> dict:
    """Rename one of the list's contexts on every todo carrying it.

    A context is a string on each todo, not a record, so this is one list-scoped
    UPDATE over the rows that hold exactly ``old`` — every status, finished included,
    or the old name would linger in the picker. When ``new`` is already one of the
    list's contexts the two would MERGE, which cannot be told apart afterwards, so
    that case raises ConflictError until the caller repeats it with ``merge=True``.

    ``updated_at`` is deliberately NOT bumped: Review's stale list and Waiting's age
    read it as "when I last touched this", and a rename touches no todo's substance.
    """
    old = common.validate_short(old, "context")
    new = common.validate_short(new, "new name")
    if not old:
        raise ValidationError("context is required")
    if not new:
        raise ValidationError("new name cannot be empty")
    if old == new:
        raise ValidationError(f'The context is already named "{new}"')
    with db.transaction() as conn:

        def carried(name: str) -> int:
            return conn.execute(
                "SELECT COUNT(*) FROM todos WHERE list_id = ? AND context = ?",
                (list_id, name),
            ).fetchone()[0]

        count = carried(old)
        if not count:
            raise NotFoundError()
        merged = carried(new) > 0
        if merged and not merge:
            raise ConflictError(f'You already have a context named "{new}". Merging moves every "{old}" to-do into it.')
        conn.execute(
            "UPDATE todos SET context = ? WHERE list_id = ? AND context = ?",
            (new, list_id, old),
        )
    return {"old": old, "new": new, "updated": count, "merged": merged}


def _todo_filter(
    list_id: int,
    status: str | None = None,
    project: str | int | None = None,
    context: str | None = None,
    tag: str | None = None,
    person: str | None = None,
    area: str | int | None = None,
    starred: bool | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    search: str | None = None,
    include_deferred: bool = False,
) -> tuple[list[str], list] | None:
    """list_todos' WHERE clause and its parameters; None when a named project or
    area does not exist, so nothing can match."""
    conn = db.get_db()
    where: list[str] = ["t.list_id = ?"]
    params: list = [list_id]
    if status:
        common.validate_status(status)
        where.append("t.status = ?")
        params.append(status)
    if project not in (None, ""):
        pid = _named_id(conn, list_id, "project", project)
        if pid is None:
            return None
        where.append("t.project_id = ?")
        params.append(pid)
    if area not in (None, ""):
        aid = _named_id(conn, list_id, "area", area)
        if aid is None:
            return None
        where.append(f"{_EFFECTIVE_AREA} = ?")
        params.append(aid)
    if context:
        where.append("lower(t.context) = lower(?)")
        params.append(context.strip())
    if tag:
        where.append("EXISTS (SELECT 1 FROM json_each(t.tags) WHERE value = ?)")
        params.append(tag)
    if person:
        where.append("EXISTS (SELECT 1 FROM json_each(t.people) WHERE value = ?)")
        params.append(person)
    if starred is not None:
        where.append("t.star = ?")
        params.append(1 if starred else 0)
    if due_before:
        where.append("t.due_date IS NOT NULL AND t.due_date <= ?")
        params.append(common.validate_due(due_before))
    if due_after:
        where.append("t.due_date IS NOT NULL AND t.due_date >= ?")
        params.append(common.validate_due(due_after))
    if search:
        # SQLite refuses a LIKE pattern beyond 50,000 bytes with a raw error.
        if len(search) > common.MAX_SHORT_CHARS:
            raise ValidationError(f"Search too long (max {common.MAX_SHORT_CHARS} characters)")
        # simplification: SQLite LIKE folds case for ASCII only; add an ICU/lowercased column if needed
        esc = f"%{_escape_like(search)}%"
        where.append(
            "(t.title LIKE ? ESCAPE '\\' OR t.notes LIKE ? ESCAPE '\\' "
            "OR t.context LIKE ? ESCAPE '\\' OR t.tags LIKE ? ESCAPE '\\' "
            "OR t.people LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\')"
        )
        params.extend([esc] * 6)
    if not search and not include_deferred:
        # Finished rows are unaffected, and a SEARCH still finds a deferred todo —
        # search is how it is reached (and its date changed) before it comes back.
        where.append(f"(t.status IN ('done','dropped') OR {_NOT_DEFERRED})")
        params.append(common.business_today(_list_tz(conn, list_id)).isoformat())
    return where, params


def list_todos(
    list_id: int,
    status: str | None = None,
    project: str | int | None = None,
    context: str | None = None,
    tag: str | None = None,
    person: str | None = None,
    area: str | int | None = None,
    starred: bool | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    include_deferred: bool = False,
) -> list[dict]:
    """Every ordering below ends in t.id, so paging by `offset` over an
    unchanged list neither skips nor repeats a row.

    ``include_deferred`` keeps todos waiting on a future revisit date in the result.
    The working lists leave it off; a record view or a project-health check turns
    it on, because a scheduled return is still that project's next action."""
    conn = db.get_db()
    found = _todo_filter(
        list_id, status, project, context, tag, person, area, starred, due_before, due_after, search, include_deferred
    )
    if found is None:
        return []
    where, params = found
    sql = _SELECT_TODO + " WHERE " + " AND ".join(where)
    if status in ("done", "dropped"):
        # Finished lists grow forever — newest-finished first, or the LIMIT
        # window would freeze on the oldest rows and hide new completions.
        # (dropped rows have no completed_at; updated_at marks the drop.)
        sql += " ORDER BY COALESCE(t.completed_at, t.updated_at) DESC, t.id DESC"
    elif search and not status:
        # Global search spans every status, and repeating todos accumulate
        # done copies with identical titles — open todos must win the LIMIT
        # window or the live occurrence vanishes behind finished ones.
        sql += " ORDER BY (t.status IN ('done','dropped')) ASC, t.id DESC"
    else:
        sql += " ORDER BY t.created_at ASC, t.id ASC"
    n = 100 if limit is None else int(limit)  # `or` would turn an explicit 0 into 100
    params += [max(1, min(n, 500)), max(0, int(offset or 0))]
    sql += " LIMIT ? OFFSET ?"
    return [_todo_dict(r) for r in conn.execute(sql, params).fetchall()]


def count_todos(list_id: int, status: str | None = None, **filters) -> int:
    """How many todos list_todos would return with no limit, for "N of M" paging."""
    found = _todo_filter(list_id, status, **filters)
    if found is None:
        return 0
    where, params = found
    sql = "SELECT COUNT(*) FROM todos t LEFT JOIN projects p ON t.project_id = p.id WHERE " + " AND ".join(where)
    return db.get_db().execute(sql, params).fetchone()[0]


def today_view(list_id: int) -> list[dict]:
    """The daily home screen: open todos that are starred, due today, overdue,
    or whose revisit date has arrived — "today" being the list's own calendar
    date. One query; the frontend groups into sections. A row whose revisit date
    is still ahead is hidden even when starred or due: "bring it back on X" means
    not before X.

    # simplification: an arrived revisit date keeps the todo on Today until it is
    # completed or the date is cleared; no auto-move to inbox, no sweep job
    """
    conn = db.get_db()
    today = common.business_today(_list_tz(conn, list_id)).isoformat()
    return [
        _todo_dict(r)
        for r in conn.execute(
            _SELECT_TODO + " WHERE t.list_id = ? AND t.status NOT IN ('done','dropped')"
            " AND (t.star = 1 OR (t.due_date IS NOT NULL AND t.due_date <= ?)"
            " OR (t.revisit_on IS NOT NULL AND t.revisit_on <= ?))"
            f" AND {_NOT_DEFERRED}"
            " ORDER BY t.due_date ASC NULLS LAST, t.created_at ASC, t.id ASC",
            (list_id, today, today, today),
        ).fetchall()
    ]


# ── Brain tickle ──────────────────────────────────────────────────────────────


def tickle_candidates(list_id: int, limit: int = 100) -> list[dict]:
    """Open next actions that may be offered as today's one "brain tickle":
    everything not tickled within the rest window (common.tickle_cutoff), each
    flagged `stale` once it has been tickled TICKLE_STALE_COUNT times and is
    still open. One deferred to a future revisit date is not offered before that
    day. Read-only — the caller picks one and calls record_tickle."""
    conn = db.get_db()
    tz = _list_tz(conn, list_id)
    rows = conn.execute(
        _SELECT_TODO + " WHERE t.list_id = ? AND t.status = 'next_action'"
        f" AND (t.last_tickled_at IS NULL OR t.last_tickled_at < ?) AND {_NOT_DEFERRED}"
        " ORDER BY t.star DESC, t.due_date ASC NULLS LAST, t.created_at ASC, t.id ASC LIMIT ?",
        (list_id, common.tickle_cutoff(tz), common.business_today(tz).isoformat(), max(1, min(int(limit), 500))),
    ).fetchall()
    return [{**_todo_dict(r), "stale": r["tickle_count"] >= TICKLE_STALE_COUNT} for r in rows]


def record_tickle(list_id: int, todo_id: int) -> dict | None:
    """Stamp a todo as tickled now and count it. Returns the todo, or None if
    it isn't in this list. Not an edit: `updated_at` is left alone, and nothing
    ever resets the count."""
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE todos SET last_tickled_at = ?, tickle_count = tickle_count + 1 WHERE id = ? AND list_id = ?",
            (common.now_iso(), todo_id, list_id),
        )
        if cur.rowcount == 0:
            return None
    return get_todo(list_id, todo_id)


# ── Weekly review ─────────────────────────────────────────────────────────────


def review_data(list_id: int, limit: int = 100) -> dict:
    """What a weekly review walks through, one section per step of the script
    the MCP server hands the AI. Read-only. Each todo section holds at most
    `limit` rows (oldest first), with the full count beside it."""
    conn = db.get_db()
    today = common.business_today(_list_tz(conn, list_id))
    now = common.utcnow()
    week_ago = common.to_iso(now - datetime.timedelta(days=7))
    stale_before = common.to_iso(now - datetime.timedelta(days=common.REVIEW_STALE_DAYS))
    upcoming_until = (today + datetime.timedelta(days=common.REVIEW_UPCOMING_DAYS)).isoformat()
    day = today.isoformat()
    cap = max(1, min(int(limit), 500))

    def section(where: str, *params) -> dict:
        clause = f" WHERE t.list_id = ? AND {where}"
        count = conn.execute(
            "SELECT COUNT(*) FROM todos t LEFT JOIN projects p ON t.project_id = p.id" + clause,
            (list_id, *params),
        ).fetchone()[0]
        rows = conn.execute(
            _SELECT_TODO + clause + " ORDER BY t.created_at ASC, t.id ASC LIMIT ?",
            (list_id, *params, cap),
        ).fetchall()
        return {"count": count, "todos": [_todo_dict(r) for r in rows]}

    def working(where: str, *params) -> dict:
        """A section that is the review's copy of a working list: like that list,
        it leaves out a todo deferred to a future revisit date (see `upcoming`)."""
        return section(f"{where} AND {_NOT_DEFERRED}", *params, day)

    without_next = conn.execute(
        _SELECT_PROJECT + " WHERE p.list_id = ? AND p.status = 'active' AND NOT EXISTS "
        "(SELECT 1 FROM todos n WHERE n.project_id = p.id AND n.status = 'next_action') "
        "ORDER BY lower(p.name) ASC",
        (list_id,),
    ).fetchall()
    return {
        "today": day,
        "inbox": working("t.status = 'inbox'"),
        "completed_last_week": section("t.status = 'done' AND t.completed_at >= ?", week_ago),
        "dated_today_or_overdue": working(
            "t.status NOT IN ('done','dropped') AND "
            "((t.due_date IS NOT NULL AND t.due_date <= ?) "
            "OR (t.revisit_on IS NOT NULL AND t.revisit_on <= ?))",
            day,
            day,
        ),
        "projects_without_next_action": [dict(r) for r in without_next],
        "waiting_for": working("t.status IN ('waiting_for','delegated')"),
        "routines": section("t.status NOT IN ('done','dropped') AND t.repeat != ''"),
        "upcoming": section(
            "t.status NOT IN ('done','dropped') AND "
            "((t.due_date > ? AND t.due_date <= ?) OR (t.revisit_on > ? AND t.revisit_on <= ?))",
            day,
            upcoming_until,
            day,
            upcoming_until,
        ),
        "stale": working("t.status IN ('next_action','waiting_for','delegated') AND t.updated_at < ?", stale_before),
        "areas": list_areas(list_id, "active"),
    }


# ── Areas of focus ────────────────────────────────────────────────────────────


def _area_name_taken(conn, list_id: int, name: str, except_id: int = 0) -> bool:
    return bool(
        conn.execute(
            "SELECT id FROM areas WHERE list_id = ? AND lower(name) = lower(?) AND id != ?",
            (list_id, name, except_id),
        ).fetchone()
    )


def get_area(list_id: int, area_id: int) -> dict | None:
    row = db.get_db().execute("SELECT * FROM areas WHERE id = ? AND list_id = ?", (area_id, list_id)).fetchone()
    return dict(row) if row else None


def list_areas(list_id: int, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM areas WHERE list_id = ?"
    params: list = [list_id]
    if status:
        sql += " AND status = ?"
        params.append(common.validate_area_status(status))
    sql += " ORDER BY lower(name) ASC"
    return [dict(r) for r in db.get_db().execute(sql, params).fetchall()]


def create_area(list_id: int, name: str, notes: str = "") -> dict:
    name = common.validate_short(name, "name")
    if not name:
        raise ValidationError("name is required")
    notes = common.validate_notes(notes)
    with db.transaction() as conn:
        if _area_name_taken(conn, list_id, name):
            raise ValidationError(f'Area "{name}" already exists')
        _check_cap(conn, list_id, "areas")
        now = common.now_iso()
        new_id = conn.execute(
            "INSERT INTO areas (list_id, name, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (list_id, name, notes, now, now),
        ).lastrowid
        assert new_id is not None  # A successful INSERT into a rowid table.
    return cast(dict, get_area(list_id, new_id))  # The row was just inserted.


def update_area(list_id: int, area_id: int, fields: dict) -> dict | None:
    """Update one area (archive it with status 'dropped'). None if not found.
    Projects and todos keep pointing at an archived area."""
    _check_fields(fields, AREA_FIELDS)
    with db.transaction() as conn:
        if not conn.execute("SELECT id FROM areas WHERE id = ? AND list_id = ?", (area_id, list_id)).fetchone():
            return None
        sets: list[str] = []
        params: list = []
        if "name" in fields:
            name = common.validate_short(fields["name"], "name")
            if not name:
                raise ValidationError("name cannot be empty")
            if _area_name_taken(conn, list_id, name, area_id):
                raise ValidationError(f'Area "{name}" already exists')
            sets.append("name = ?")
            params.append(name)
        if "notes" in fields:
            sets.append("notes = ?")
            params.append(common.validate_notes(fields["notes"]))
        if "status" in fields:
            sets.append("status = ?")
            params.append(common.validate_area_status(fields["status"]))
        sets.append("updated_at = ?")
        params.append(common.now_iso())
        conn.execute(
            f"UPDATE areas SET {', '.join(sets)} WHERE id = ? AND list_id = ?",
            (*params, area_id, list_id),
        )
    return get_area(list_id, area_id)


# ── Projects ──────────────────────────────────────────────────────────────────

_SELECT_PROJECT = (
    "SELECT p.*, a.name AS area_name, (SELECT COUNT(*) FROM todos t WHERE t.project_id = p.id "
    "AND t.status NOT IN ('done','dropped')) AS open_count "
    "FROM projects p LEFT JOIN areas a ON a.id = p.area_id"
)


def get_project(list_id: int, project_id: int) -> dict | None:
    row = db.get_db().execute(_SELECT_PROJECT + " WHERE p.id = ? AND p.list_id = ?", (project_id, list_id)).fetchone()
    return dict(row) if row else None


def list_projects(list_id: int, status: str | None = None, area: str | int | None = None) -> list[dict]:
    conn = db.get_db()
    sql = _SELECT_PROJECT + " WHERE p.list_id = ?"
    params: list = [list_id]
    if status:
        common.validate_project_status(status)
        sql += " AND p.status = ?"
        params.append(status)
    if area not in (None, ""):
        aid = _named_id(conn, list_id, "area", area)
        if aid is None:
            return []
        sql += " AND p.area_id = ?"
        params.append(aid)
    sql += " ORDER BY lower(p.name) ASC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def create_project(
    list_id: int,
    name: str,
    notes: str = "",
    status: str = "active",
    *,
    purpose: str = "",
    outcome: str = "",
    area_id: int | None = None,
) -> dict:
    name = common.validate_short(name, "name")
    if not name:
        raise ValidationError("name is required")
    notes = common.validate_notes(notes)
    purpose = common.validate_notes(purpose, "purpose")
    outcome = common.validate_notes(outcome, "outcome")
    common.validate_project_status(status)
    with db.transaction() as conn:
        if conn.execute(
            "SELECT id FROM projects WHERE list_id = ? AND lower(name) = lower(?)",
            (list_id, name),
        ).fetchone():
            raise ValidationError(f'Project "{name}" already exists')
        _check_cap(conn, list_id, "projects")
        aid = _check_ref(conn, list_id, "area", area_id)
        now = common.now_iso()
        new_id = conn.execute(
            "INSERT INTO projects "
            "(list_id, name, notes, status, purpose, outcome, area_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (list_id, name, notes, status, purpose, outcome, aid, now, now),
        ).lastrowid
        assert new_id is not None  # A successful INSERT into a rowid table.
    return cast(dict, get_project(list_id, new_id))  # The row was just inserted.


def update_project(list_id: int, project_id: int, fields: dict) -> dict | None:
    _check_fields(fields, PROJECT_FIELDS)
    with db.transaction() as conn:
        if not conn.execute("SELECT id FROM projects WHERE id = ? AND list_id = ?", (project_id, list_id)).fetchone():
            return None
        sets: list[str] = []
        params: list = []
        if "name" in fields:
            name = common.validate_short(fields["name"], "name")
            if not name:
                raise ValidationError("name cannot be empty")
            if conn.execute(
                "SELECT id FROM projects WHERE list_id = ? AND lower(name) = lower(?) AND id != ?",
                (list_id, name, project_id),
            ).fetchone():
                raise ValidationError(f'Project "{name}" already exists')
            sets.append("name = ?")
            params.append(name)
        for field in ("notes", "purpose", "outcome"):
            if field in fields:
                sets.append(f"{field} = ?")
                params.append(common.validate_notes(fields[field], field))
        if "area_id" in fields:
            sets.append("area_id = ?")
            params.append(_check_ref(conn, list_id, "area", fields["area_id"]))
        if "status" in fields:
            common.validate_project_status(fields["status"])
            sets.append("status = ?")
            params.append(fields["status"])
        sets.append("updated_at = ?")
        params.append(common.now_iso())
        conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE id = ? AND list_id = ?",
            (*params, project_id, list_id),
        )
    return get_project(list_id, project_id)


# ── Filters / capture ─────────────────────────────────────────────────────────


def get_filters(list_id: int) -> dict:
    """Distinct contexts, tag and people unions, the active areas (what the
    pickers offer), per-status counts (all statuses, zeros included), and the
    list's timezone — the frontend computes "today" in that zone so the web
    app, the API and AI tools agree on it."""
    conn = db.get_db()

    def distinct(column: str) -> list[str]:
        values = {
            r["v"]
            for r in conn.execute(
                f"SELECT DISTINCT j.value AS v FROM todos t, json_each(t.{column}) j WHERE t.list_id = ?",
                (list_id,),
            )
            if isinstance(r["v"], str) and r["v"]
        }
        return sorted(values, key=str.lower)

    contexts = [
        r["context"]
        for r in conn.execute(
            "SELECT DISTINCT context FROM todos WHERE list_id = ? AND context != '' ORDER BY lower(context)",
            (list_id,),
        )
    ]
    counts = {s: 0 for s in TODO_STATUSES}
    tz = _list_tz(conn, list_id)
    # The open-status counts describe the working lists, so a todo waiting on a
    # revisit date is not counted until its day — otherwise the Inbox badge would
    # count an item the Inbox does not show. Finished counts keep every row.
    for r in conn.execute(
        "SELECT t.status, COUNT(*) AS n FROM todos t WHERE t.list_id = ? "
        f"AND (t.status IN ('done','dropped') OR {_NOT_DEFERRED}) GROUP BY t.status",
        (list_id, common.business_today(tz).isoformat()),
    ):
        if r["status"] in counts:
            counts[r["status"]] = r["n"]
    return {
        "contexts": contexts,
        "tags": distinct("tags"),
        "people": distinct("people"),
        "areas": [{"id": a["id"], "name": a["name"]} for a in list_areas(list_id, "active")],
        "status_counts": counts,
        "tz": tz,
        "name": _list_name(conn, list_id),  # '' when the list has none
    }


def changes(list_id: int, since: int = 0, limit: int = 500) -> dict:
    """What changed after `since`, for a tool that keeps a copy of the list in
    step: the todos, projects and areas created or edited since then, oldest
    change first, and `next_since` to send next time. Nothing is ever deleted,
    so that is every change there can be. Each caller keeps its own number; the
    server remembers nothing about who has synced. `reset` means the caller's
    copy cannot be patched and it gets everything instead: its `since` is ahead
    of the list (the database was put back from a snapshot), or behind a
    one-list repair, which removes rows (lists.sync_floor).

    # simplification: a restore that the list then outgrows before a tool syncs
    # is not noticed; add a restore id to the cursor if that ever matters.
    """
    if since < 0:
        raise ValidationError("since must be 0 or more")
    if not 1 <= limit <= 500:
        raise ValidationError("limit must be between 1 and 500")
    conn = db.get_db()
    # Read first and used as the ceiling, so a write landing between the three
    # queries below is left whole for the next call rather than half-reported.
    head, floor = conn.execute("SELECT rev, sync_floor FROM lists WHERE id = ?", (list_id,)).fetchone()
    reset = since > head or 0 < since < floor
    if reset:
        since = 0
    rows = []
    if since < head:
        for kind, select in (
            ("todos", _SELECT_TODO),
            ("projects", _SELECT_PROJECT),
            ("areas", "SELECT a.* FROM areas a"),
        ):
            alias = kind[0] if kind != "areas" else "a"
            rows += [
                (r["rev"], kind, r)
                for r in conn.execute(
                    f"{select} WHERE {alias}.list_id = ? AND {alias}.rev > ? AND {alias}.rev <= ? "
                    f"ORDER BY {alias}.rev LIMIT ?",
                    (list_id, since, head, limit + 1),
                )
            ]
        rows.sort(key=lambda row: row[0])  # a rev belongs to one row, so this is a total order
    more = len(rows) > limit
    rows = rows[:limit]
    out: dict = {
        "changed": bool(rows),
        "next_since": rows[-1][0] if more else head,
        "more": more,
        "reset": reset,
        "todos": [],
        "projects": [],
        "areas": [],
    }
    for _, kind, row in rows:
        out[kind].append(_todo_dict(row) if kind == "todos" else dict(row))
    return out


def changes_count(list_id: int) -> dict:
    """{count, last_change_at}: how many changes the list has had and when the
    last one was, for a cheap "anything new?" check before a sync. `count` is the change counter (lists.rev),
    so compare it for equality only; a list that has never changed is
    {0, None}."""
    row = db.get_db().execute("SELECT rev, changed_at FROM lists WHERE id = ?", (list_id,)).fetchone()
    return {"count": row["rev"], "last_change_at": row["changed_at"]}


def capture(list_id: int, text: str, source: str = "capture") -> dict:
    """Deterministic quick capture: full trimmed text becomes an inbox todo's title."""
    text = (text or "").strip()
    if not text:
        raise ValidationError("Nothing to capture")
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationError(f"Capture text too long (max {MAX_TEXT_CHARS} characters)")
    return create_todo(list_id, text, status="inbox", source=source)
