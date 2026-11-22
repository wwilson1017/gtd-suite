"""The operator's command line for a todo-gtd server. There is no admin web page.

    python -m scripts.admin stats
    python -m scripts.admin lists [--email A] [--name TEXT] [--created-after DATE]
                                  [--created-before DATE] [--unused] [--limit N] [--show-email]
    python -m scripts.admin find --link <any link of a list, or a bare token>
    python -m scripts.admin show <list_id> [--content] [--show-email]
    python -m scripts.admin signin-link <list_id>
    python -m scripts.admin sign-out-all <list_id>
    python -m scripts.admin set-email <list_id> <email>
    python -m scripts.admin clear-email <list_id>
    python -m scripts.admin disable <list_id>
    python -m scripts.admin enable <list_id>
    python -m scripts.admin delete <list_id> --yes-delete-list-<list_id> [--no-snapshot]
    python -m scripts.admin snapshots
    python -m scripts.admin restore <list_id> --from <snapshot> [--identity <key file or ->]
    python -m scripts.admin merge-brain <from-ref> <to-ref> --name N --folder F [--yes]

Every <list_id> also takes the list's account number, with or without its dash.
Read commands take --json. Run it from the app directory with the same DATA_DIR
as the app (on Railway: `railway ssh --service <your service>`, which lands in /app).

Safe while the app is running. This is a SECOND process on the live database, so
the app's in-process write lock does not cover it; what does is SQLite itself.
Every write here goes through ``db.transaction()``: BEGIN IMMEDIATE takes the
database file's write lock, waiting up to the busy timeout for the app's current
write to finish, and WAL means readers on either side never block or see a
half-finished change. Each transaction is a few statements long. The app looks
every token up in the database on every request, so a change made here takes
effect on the running app at once, with no restart.

Privacy: nothing here prints an agent or capture token, and the only link ever
printed is the one-hour sign-in link `signin-link` issues. Titles and names
inside a list are read only by `show --content`. Every change (and every --content read)
is recorded in the `admin_log` table: time, command, list id, nothing else.
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from backend.plans import admin as plan_admin, extension
from backend import (
    apps,
    backup,
    brain,
    keys,
    cleanup,
    common,
    db,
    files,
    lifecycle,
    lists,
    objectstore,
    sessions,
    settings,
    signin,
    sites,
)
from scripts import restore_list

_OPEN = "status NOT IN ('done','dropped')"
_LIST_ROW = f"""
    SELECT id, account_no, name, tz, email, email_verified_at, created_at, last_used_at, review_started_at,
        disabled_at,
        (SELECT COUNT(*) FROM todos WHERE todos.list_id = lists.id) AS todos_total,
        (SELECT COUNT(*) FROM todos WHERE todos.list_id = lists.id AND {_OPEN}) AS todos_open,
        (SELECT COUNT(*) FROM projects WHERE projects.list_id = lists.id) AS projects
    FROM lists
"""
# Delete children first (todos point at projects and areas, projects at areas);
# all of these before the list's own row.
_LIST_TABLES = (*apps.content_tables(), "sessions", "signin_tokens", "api_keys", "brains", "ai_tools")


# ── Output ────────────────────────────────────────────────────────────────────


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> None:
    """``columns`` is (heading, key) pairs; a missing or None value prints as '-'."""
    cells = [[h for h, _ in columns]] + [["-" if r.get(k) is None else str(r[k]) for _, k in columns] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    for row in cells:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())


def _emit(args, data, text) -> None:
    """--json prints ``data``; otherwise ``text()`` prints the plain form."""
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        text()


def _day(iso: str | None) -> str | None:
    return iso[:10] if iso else None


# ── Shared lookups ────────────────────────────────────────────────────────────


def _log(conn, command: str, list_id: int) -> None:
    """One admin_log line, inside the caller's transaction. Never a token or content."""
    conn.execute("INSERT INTO admin_log (at, command, list_id) VALUES (?, ?, ?)", (common.now_iso(), command, list_id))


def _list_rows(where: str = "", params: tuple = ()) -> list:
    return db.get_db().execute(_LIST_ROW + where, params).fetchall()


def _public(row, show_email: bool = False) -> dict:
    """A list row as this tool shows it: no token, and the address only on request."""
    out = {
        "id": row["id"],
        "account_no": row["account_no"],
        "name": row["name"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "todos_open": row["todos_open"],
        "todos_total": row["todos_total"],
        "projects": row["projects"],
        "has_email": row["email"] is not None,
        "email_verified": row["email_verified_at"] is not None,
        "disabled_at": row["disabled_at"],
        # disabled, else active / archived / removed (lifecycle.py)
        "state": "disabled" if row["disabled_at"] else lifecycle.state(row),
    }
    if show_email:
        out["email"] = row["email"]
    return out


def _list_ref(ref: str) -> int:
    """The list id behind what the operator typed: an id, or an account number with or
    without its dash. Eight digits try the number first; ids are nowhere near that long."""
    ref = ref.strip()
    if re.fullmatch(r"[1-9]\d{3}-?\d{4}", ref):
        digits = ref.replace("-", "")
        row = (
            db.get_db().execute("SELECT id FROM lists WHERE account_no = ?", (f"{digits[:4]}-{digits[4:]}",)).fetchone()
        )
        if row:
            return row["id"]
    if ref.isdigit():
        return int(ref)
    raise SystemExit(f"No list has id or account number {ref}")


def _require(list_id: int):
    rows = _list_rows("WHERE id = ?", (list_id,))
    if not rows:
        raise SystemExit(f"No list has id {list_id}")
    return rows[0]


# ── Read commands ─────────────────────────────────────────────────────────────


def cmd_stats(args) -> None:
    conn = db.get_db()

    def one(sql):
        return conn.execute(sql).fetchone()[0]

    by_status = {s: 0 for s in common.TODO_STATUSES}
    by_status.update(conn.execute("SELECT status, COUNT(*) FROM todos GROUP BY status").fetchall())
    today = common.utcnow().date()
    days = [(today - datetime.timedelta(days=n)).isoformat() for n in range(13, -1, -1)]
    made = dict(
        conn.execute(
            "SELECT substr(created_at, 1, 10), COUNT(*) FROM lists WHERE created_at >= ? GROUP BY 1", (days[0],)
        ).fetchall()
    )
    snaps = backup.files()
    data = {
        "lists": one("SELECT COUNT(*) FROM lists"),
        "lists_disabled": one("SELECT COUNT(*) FROM lists WHERE disabled_at IS NOT NULL"),
        "lists_with_email": one("SELECT COUNT(*) FROM lists WHERE email IS NOT NULL"),
        "lists_verified": one("SELECT COUNT(*) FROM lists WHERE email_verified_at IS NOT NULL"),
        "todos": sum(by_status.values()),
        "todos_by_status": by_status,
        "projects": one("SELECT COUNT(*) FROM projects"),
        "areas": one("SELECT COUNT(*) FROM areas"),
        "lists_created_by_day": {d: made.get(d, 0) for d in days},  # UTC days
        **plan_admin.stats(conn),
        "database_bytes": db.db_path().stat().st_size,
        "snapshots": {
            "count": len(snaps),
            "bytes": sum(p.stat().st_size for p in snaps),
            "newest": snaps[-1].name if snaps else None,
        },
    }

    def text():
        print(
            f"Lists: {data['lists']} ({data['lists_with_email']} with an email, "
            f"{data['lists_verified']} confirmed, {data['lists_disabled']} disabled)"
        )
        print(f"Todos: {data['todos']}  " + "  ".join(f"{s} {n}" for s, n in by_status.items()))
        print(f"Projects: {data['projects']}   Areas: {data['areas']}")
        plan_admin.print_stats(data)
        print(f"Database file: {_size(data['database_bytes'])}")
        s = data["snapshots"]
        print(f"Snapshots: {s['count']}, {_size(s['bytes'])}, newest {s['newest'] or '-'}")
        print("Lists created per day (UTC), last 14 days:")
        for d, n in data["lists_created_by_day"].items():
            print(f"  {d}  {n}")

    _emit(args, data, text)


def _print_lists(rows: list[dict], show_email: bool) -> None:
    for r in rows:
        r.update(
            created=_day(r["created_at"]),
            last_used=_day(r["last_used_at"]),
            todos=f"{r['todos_open']}/{r['todos_total']}",
            email_shown=r.get("email") if show_email else ("yes" if r["has_email"] else "no"),
            confirmed=("yes" if r["email_verified"] else "no") if r["has_email"] else None,
        )
    _table(
        rows,
        [
            ("ID", "id"),
            ("ACCOUNT", "account_no"),
            ("NAME", "name"),
            ("CREATED", "created"),
            ("LAST USED", "last_used"),
            ("OPEN/TOTAL", "todos"),
            ("PROJECTS", "projects"),
            ("EMAIL", "email_shown"),
            ("CONFIRMED", "confirmed"),
            ("STATE", "state"),
        ],
    )


def cmd_lists(args) -> None:
    where, params = [], []
    if args.email:
        where.append("email = ?")
        params.append(common.validate_email(args.email))
    if args.name:
        where.append("instr(lower(name), lower(?)) > 0")
        params.append(args.name)
    if args.created_after:
        where.append("created_at >= ?")
        params.append(args.created_after.isoformat())
    if args.created_before:
        where.append("created_at < ?")
        params.append(args.created_before.isoformat())
    if args.unused:
        # The cleanup's own definition of "never used", without its age limit.
        where.append(cleanup._unused())
        params.append("9999")
    sql = "WHERE " + " AND ".join(f"({w})" for w in where) if where else ""
    rows = [_public(r, args.show_email) for r in _list_rows(sql + " ORDER BY id DESC LIMIT ?", (*params, args.limit))]
    _emit(args, rows, lambda: _print_lists([dict(r) for r in rows], args.show_email))


def _identify(link: str) -> dict | None:
    """Which list an agent or capture link belongs to, and which of the two it
    is. Every path segment is tried as the token, hashed the way the app hashes
    it, so any address shape works: /link/<t>, /mcp/<t>, /<t>/mcp, /c/<t>, /api/c/<t>, bare.
    A sign-in link or a session cannot be identified: both are stored hashed and
    say nothing about their list from outside."""
    conn = db.get_db()
    for segment in filter(None, urlsplit(link.strip()).path.split("/")):
        for kind, column, value in (
            ("agent", "agent_token_hash", lists.hash_token(segment)),
            ("capture", "capture_token", segment),
        ):
            row = conn.execute(f"SELECT id, disabled_at FROM lists WHERE {column} = ?", (value,)).fetchone()
            if row:
                return {"list_id": row["id"], "kind": kind, "disabled": bool(row["disabled_at"])}
    return None


def cmd_find(args) -> int:
    found = _identify(args.link)
    if not found:
        _emit(
            args,
            {"list_id": None, "kind": None},
            lambda: print(
                "No list has that link. (Only agent and capture links can be identified; a sign-in link cannot.)"
            ),
        )
        return 1
    _emit(
        args,
        found,
        lambda: print(
            f"List {found['list_id']}: that is its {found['kind']} link"
            + (" (the list is disabled)" if found["disabled"] else "")
        ),
    )
    return 0


def cmd_show(args) -> None:
    row = _require(args.list_id)
    conn = db.get_db()
    by_status = {s: 0 for s in common.TODO_STATUSES}
    by_status.update(
        conn.execute("SELECT status, COUNT(*) FROM todos WHERE list_id = ? GROUP BY status", (args.list_id,)).fetchall()
    )
    data = {
        **_public(row, args.show_email),
        "tz": row["tz"],
        "review_started_at": row["review_started_at"],
        "todos_by_status": by_status,
        **plan_admin.details(conn, args.list_id),
    }
    if args.content:
        # stderr, so --json output stays parseable.
        print(
            f"Reading the private content of list {args.list_id} (--content); this is recorded in admin_log.",
            file=sys.stderr,
        )
        with db.transaction() as tx:
            _log(tx, "show --content", args.list_id)
        data["project_items"] = [
            dict(r)
            for r in conn.execute(
                "SELECT id, name, status FROM projects WHERE list_id = ? ORDER BY id", (args.list_id,)
            )
        ]
        data["todo_items"] = [
            dict(r)
            for r in conn.execute("SELECT id, status, title FROM todos WHERE list_id = ? ORDER BY id", (args.list_id,))
        ]

    def text():
        _print_lists([dict(data)], args.show_email)
        print(f"Time zone: {data['tz']}")
        print(f"Review started: {data['review_started_at'] or '-'}")
        plan_admin.print_details(data)
        print("Todos by status: " + "  ".join(f"{s} {n}" for s, n in by_status.items()))
        if args.content:
            print("Projects:")
            _table(data["project_items"], [("ID", "id"), ("STATUS", "status"), ("NAME", "name")])
            print("Todos:")
            _table(data["todo_items"], [("ID", "id"), ("STATUS", "status"), ("TITLE", "title")])

    _emit(args, data, text)


def cmd_snapshots(args) -> None:
    rows = []
    for path in backup.files():
        taken = backup._taken(path)
        rows.append(
            {"name": path.name, "taken_at": common.to_iso(taken) if taken else None, "bytes": path.stat().st_size}
        )

    def text():
        if not rows:
            print(f"No snapshots in {backup.backups_dir()}")
            return
        _table(
            [{**r, "size": _size(r["bytes"])} for r in rows],
            [("SNAPSHOT", "name"), ("TAKEN (UTC)", "taken_at"), ("SIZE", "size")],
        )

    _emit(args, rows, text)


# ── Write commands ────────────────────────────────────────────────────────────
# Each prints exactly what changed and logs it in the same transaction as the
# change — except set-email and restore, which reuse the app's own functions
# (their own transactions) and log straight after.


def cmd_signin_link(args) -> None:
    """The operator's way back in for someone with no email and no signed-in
    device (a stranded self-hoster): one sign-in link, printed once."""
    _require(args.list_id)
    with db.transaction() as conn:
        token, _ = signin.issue_link_in(conn, args.list_id)
        _log(conn, "signin-link", args.list_id)
    print(
        f"List {args.list_id}: a sign-in link, shown once. It works once, within the hour, "
        "and signs in the browser that opens it. Nothing else changed:"
    )
    base = settings.configured_base_url()
    print(f"{base}/signin/{token}")
    if not base:
        print("(PUBLIC_BASE_URL is not set here, so that is the path only; put the server's address in front of it.)")


def cmd_sign_out_all(args) -> None:
    _require(args.list_id)
    with db.transaction() as conn:
        sessions.revoke_all_in(conn, args.list_id)
        _log(conn, "sign-out-all", args.list_id)
    print(
        f"List {args.list_id}: every browser is signed out and unspent sign-in links "
        "are cancelled. The agent and capture links are unchanged."
    )


def _set_email(args, email: str | None, command: str) -> None:
    before = _require(args.list_id)["email"]
    try:
        stored = lists.set_email(args.list_id, email)
    except common.ValidationError as e:
        raise SystemExit(str(e))
    if stored == before:
        print(f"List {args.list_id}: nothing changed (the email was already that).")
        return
    with db.transaction() as conn:
        _log(conn, command, args.list_id)
    print(
        f"List {args.list_id}: email "
        + (f"set to {stored}, unconfirmed" if stored else "removed")
        + ". Sign-in links already mailed for this list no longer work."
        + (
            " No sign-in mail goes to the address until someone signed in to the list confirms it under Connect."
            if stored
            else ""
        )
    )


def cmd_set_email(args) -> None:
    if not args.email.strip():
        raise SystemExit("Give an address, or use clear-email to remove it")
    _set_email(args, args.email, "set-email")


def cmd_clear_email(args) -> None:
    _set_email(args, None, "clear-email")


def _set_disabled(args, disabled: bool) -> None:
    _require(args.list_id)
    command = "disable" if disabled else "enable"
    with db.transaction() as conn:
        changed = conn.execute(
            "UPDATE lists SET disabled_at = ? WHERE id = ? AND (disabled_at IS NULL) = ?",
            (common.now_iso() if disabled else None, args.list_id, disabled),
        ).rowcount
        if changed:
            _log(conn, command, args.list_id)
    if changed and disabled:
        # Disabled first, so anything the extension has in flight sees it; then the
        # extension checks it (plans/extension.py). A refusal, or a service that cannot be
        # asked, undoes it.
        plan_admin._undo_on_failure(args.list_id, extension.check_disable)
    if not changed:
        print(f"List {args.list_id}: nothing changed (it was already {command}d).")
    elif disabled:
        print(
            f"List {args.list_id}: disabled. Its agent and capture links now answer "
            "as unknown links (404) and its browsers as signed out. Nothing was deleted; "
            "`enable` turns them back on."
        )
    else:
        print(f"List {args.list_id}: enabled. Its links work again.")


def cmd_disable(args) -> None:
    _set_disabled(args, True)


def cmd_enable(args) -> None:
    _set_disabled(args, False)


def cmd_delete(args) -> int:
    """The one operator-only hard delete of real content in the project: the app
    itself never deletes what a user wrote (cleanup.py removes only empty lists)."""
    row = _require(args.list_id)
    conn = db.get_db()
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE list_id = ?", (args.list_id,)).fetchone()[0]
        for t in _LIST_TABLES
    }
    print(
        f"List {args.list_id} (name {row['name']!r}, created {_day(row['created_at'])}, "
        f"last used {_day(row['last_used_at']) or 'never'}) holds: "
        + ", ".join(f"{n} {t.replace('_', ' ')}" for t, n in counts.items())
        + ". Deleting removes all of that and the list itself, with its links."
    )
    flag = f"--yes-delete-list-{args.list_id}"
    if args.extra != [flag]:
        print(f"Nothing was deleted. To delete this list for good, add {flag}")
        return 1
    if (counts["brain_files"] or counts["site_blobs"]) and not files.on():
        raise SystemExit(
            f"List {args.list_id} has stored files; run this with the app's "
            "FILES_S3_* variables set so their bytes are deleted too. Nothing was deleted."
        )
    if not args.no_snapshot:  # before the account is marked, so a failure here changes nothing
        before = backup.snapshot()
        if before is None:
            raise SystemExit(
                "Could not snapshot the database first; nothing was deleted (--no-snapshot skips the snapshot)"
            )
        print(f"Snapshot taken first: {before.name}")
    # Marked disabled first (as disable does), so anything the extension has in flight sees
    # it; then the extension checks it (plans/extension.py), and a refusal or a service
    # failure undoes it.
    with db.transaction() as tx:
        marked = tx.execute(
            "UPDATE lists SET disabled_at = ? WHERE id = ? AND disabled_at IS NULL", (common.now_iso(), args.list_id)
        ).rowcount
    if marked:
        plan_admin._undo_on_failure(args.list_id, extension.check_delete)
    else:
        extension.check_delete(args.list_id)
    # The files' bytes before their rows, which are the only record of where they are.
    try:
        files.delete_objects(args.list_id)
        sites.delete_objects(args.list_id)
    except objectstore.StoreError as e:
        raise SystemExit(
            f"List {args.list_id}: {e} It stays disabled, and its rows are all still there; run delete again."
        ) from e
    with db.transaction() as tx:
        tx.execute("DELETE FROM connect_codes WHERE list_id = ? OR created_list_id = ?", (args.list_id, args.list_id))
        for table in _LIST_TABLES:
            tx.execute(f"DELETE FROM {table} WHERE list_id = ?", (args.list_id,))
        tx.execute("DELETE FROM lists WHERE id = ?", (args.list_id,))
        _log(tx, "delete", args.list_id)
    print(f"List {args.list_id}: deleted.")
    return 0


def cmd_restore(args) -> None:
    """One-list repair from a snapshot: scripts.restore_list does all of it,
    including its own snapshot of the live database first."""
    _require(args.list_id)
    snapshot = args.snapshot if args.snapshot.is_file() else backup.backups_dir() / args.snapshot.name
    identity = ["--identity", args.identity] if args.identity else []
    restore_list.main([str(snapshot), "--list-id", str(args.list_id), *identity])
    with db.transaction() as conn:
        _log(conn, "restore", args.list_id)


# ── Command line ──────────────────────────────────────────────────────────────


def _merge_brain_check_in(conn, from_id: int, to_id: int) -> dict:
    """All merge refusals, shared by the dry run and the locked write transaction."""
    if from_id == to_id:
        raise common.ValidationError("Source and destination must differ")
    source = conn.execute("SELECT disabled_at FROM lists WHERE id = ?", (from_id,)).fetchone()
    target = conn.execute("SELECT disabled_at FROM lists WHERE id = ?", (to_id,)).fetchone()
    if source is None or target is None:
        raise common.ValidationError("Account not found")
    if source["disabled_at"] is not None or target["disabled_at"] is not None:
        raise common.ValidationError("A disabled account cannot be merged")
    brains = conn.execute("SELECT * FROM brains WHERE list_id = ?", (from_id,)).fetchall()
    if len(brains) != 1:
        raise common.ValidationError("The source must have exactly one brain")
    original = brain._brain_out(brains[0])
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE list_id = ?", (from_id,)).fetchone()[0] for t in _LIST_TABLES
    }
    for app, definition in apps.APPS.items():
        if app != "brain" and any(counts[t] for t in definition.tables):
            raise common.ValidationError(
                "The source must be a whole Brain-only account with no Todo, Projects, Notes or Sites content"
            )
    moved_keys = [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, apps, access, folders, brains, kind FROM api_keys WHERE list_id = ? ORDER BY id",
            (from_id,),
        )
    ]
    for key in moved_keys:
        if key["apps"] == "all":
            raise common.ValidationError("A source key with apps='all' would gain authority in the target account")
        if json.loads(key["brains"]) != [original["id"]]:
            raise common.ValidationError("Every source key must carry exactly the source brain")
    names = {r["name"].lower() for r in conn.execute("SELECT name FROM api_keys WHERE list_id = ?", (to_id,))}
    return {
        "counts": counts,
        "keys": moved_keys,
        "clashes": [k["name"] for k in moved_keys if k["name"].lower() in names],
        "brain": original,
    }


def merge_brain(from_id: int, to_id: int, name: str, folder: str, *, yes: bool = False) -> dict:
    """Fold a whole Brain-only account. Tokens, content ids and object keys stay valid."""
    report = _merge_brain_check_in(db.get_db(), from_id, to_id)
    if not yes:
        return report
    with db.transaction() as conn:
        report = _merge_brain_check_in(conn, from_id, to_id)
        original = report["brain"]
        target = brain.create_brain_in(
            conn, to_id, name, original["description"], original["rules"], original["ai_access"], folder=folder
        )
        conn.execute(
            "UPDATE brains SET settled_at = ?, status = ? WHERE id = ?",
            (original["settled_at"] or target["settled_at"], original["status"], target["id"]),
        )
        for table in apps.APPS["brain"].tables:
            conn.execute(
                f"UPDATE {table} SET list_id = ?, brain_id = ? WHERE list_id = ?", (to_id, target["id"], from_id)
            )
        names = {r["name"].lower() for r in conn.execute("SELECT name FROM api_keys WHERE list_id = ?", (to_id,))}
        for key in report["keys"]:
            name = key["name"]
            if name.lower() in names:
                suffix = "-" + folder
                name = key["name"][: max(1, keys.MAX_NAME - len(suffix))] + suffix
                n = 2
                while name.lower() in names:
                    suffix = f"-{folder}-{n}"
                    name = key["name"][: max(1, keys.MAX_NAME - len(suffix))] + suffix
                    n += 1
            keys._name(name)
            names.add(name.lower())
            conn.execute(
                "UPDATE api_keys SET list_id = ?, brains = ?, name = ? WHERE id = ?",
                (to_id, json.dumps([target["id"]]), name, key["id"]),
            )
        conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), from_id))
        _log(conn, "merge-brain source", from_id)
        _log(conn, "merge-brain target", to_id)
        report["to_brain"] = target["id"]
    return report


def cmd_merge_brain(args) -> None:
    try:
        report = merge_brain(_list_ref(args.from_ref), _list_ref(args.to_ref), args.name, args.folder, yes=args.yes)
    except (common.ValidationError, common.ConflictError) as exc:
        raise SystemExit(str(exc)) from None
    print("Counts: " + json.dumps(report["counts"], sort_keys=True))
    _table(report["keys"], [(k, k) for k in ("name", "apps", "access", "folders", "brains", "kind")])
    print("Name clashes: " + (", ".join(report["clashes"]) or "none"))
    print("Merged; source disabled." if args.yes else "Dry run; nothing changed. Add --yes to merge.")


def cmd_site_status(args) -> None:
    """Operator takedown: independent of publishing and never prints a host code."""
    with db.transaction() as conn:
        row = conn.execute("SELECT id, list_id FROM sites WHERE id = ? OR host = ?", (args.site, args.site)).fetchone()
        if row is None:
            raise SystemExit("Site not found")
        down = args.command == "site-down"
        conn.execute("UPDATE sites SET suspended_at = ? WHERE id = ?", (common.now_iso() if down else None, row["id"]))
        _log(conn, f"{args.command} {row['id']}", row["list_id"])
    print(f"Site {row['id']}: {'taken down by the operator' if down else 'suspension cleared'}.")


def _parser() -> argparse.ArgumentParser:
    assert __doc__ is not None  # This module defines the CLI description in its docstring.
    parser = argparse.ArgumentParser(prog="python -m scripts.admin", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, fn, help, *, read=False, list_id=True):
        p = sub.add_parser(name, help=help, description=help)
        p.set_defaults(fn=fn, json=False)
        if list_id:
            p.add_argument("list_id", help="the list's id or account number")
        if read:
            p.add_argument("--json", action="store_true", help="machine-readable output")
        return p

    p = command(
        "merge-brain", cmd_merge_brain, "fold a whole Brain-only account into another as a brain", list_id=False
    )
    p.add_argument("from_ref")
    p.add_argument("to_ref")
    p.add_argument("--name", required=True)
    p.add_argument("--folder", required=True)
    p.add_argument("--yes", action="store_true")

    for name in ("site-down", "site-up"):
        p = command(name, cmd_site_status, "set or clear an operator site suspension", list_id=False)
        p.add_argument("site", help="the site's id or stored host label")

    day = datetime.date.fromisoformat
    command("stats", cmd_stats, "totals for the whole server", read=True, list_id=False)
    p = command("lists", cmd_lists, "one row per list, newest first", read=True, list_id=False)
    p.add_argument("--email", help="only lists with this email")
    p.add_argument("--name", help="only lists whose name contains this")
    p.add_argument("--created-after", type=day, metavar="YYYY-MM-DD", help="created on or after")
    p.add_argument("--created-before", type=day, metavar="YYYY-MM-DD", help="created before")
    p.add_argument("--unused", action="store_true", help="only lists with no todos, projects, areas or email")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--show-email", action="store_true", help="print the addresses")
    p = command("find", cmd_find, "which list a link belongs to", read=True, list_id=False)
    p.add_argument(
        "--link",
        required=True,
        help="an agent or capture link, or a bare token (write --link=<token> for a token that starts with '-')",
    )
    p = command("show", cmd_show, "one list's details", read=True)
    p.add_argument("--content", action="store_true", help="also print todo and project titles (someone's private list)")
    p.add_argument("--show-email", action="store_true", help="print the address")
    command("signin-link", cmd_signin_link, "print a one-hour sign-in link for the list; nothing else changes")
    command("sign-out-all", cmd_sign_out_all, "sign every browser out of the list and cancel its sign-in links")
    p = command("set-email", cmd_set_email, "set the list's email")
    p.add_argument("email")
    command("clear-email", cmd_clear_email, "remove the list's email")
    command("disable", cmd_disable, "make every link of the list answer 404 and sign its browsers out; deletes nothing")
    command("enable", cmd_enable, "undo disable")
    p = command("delete", cmd_delete, "permanently delete the list; needs --yes-delete-list-<list_id>")
    p.add_argument("--no-snapshot", action="store_true", help="skip the snapshot taken first")
    command("snapshots", cmd_snapshots, "the snapshot files", read=True, list_id=False)
    p = command("restore", cmd_restore, "put one list back the way a snapshot has it")
    p.add_argument(
        "--from",
        dest="snapshot",
        type=Path,
        required=True,
        help="a snapshot's path, or its file name in DATA_DIR/backups",
    )
    p.add_argument("--identity", help="for an encrypted snapshot: the age key file, or - to type the key in")
    plan_admin.register(command, day)
    return parser


def main(argv=None) -> int:
    parser = _parser()
    # delete's confirmation flag carries the list id, so it cannot be declared.
    args, args.extra = parser.parse_known_args(argv)
    if args.extra and args.fn is not cmd_delete:
        parser.error("unrecognized arguments: " + " ".join(args.extra))
    if not db.db_path().is_file():
        raise SystemExit(f"No database at {db.db_path()}; is DATA_DIR set as it is for the app?")
    db.init_db()
    if "list_id" in args:  # after init_db: an older database has no numbers yet
        args.list_id = _list_ref(args.list_id)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
