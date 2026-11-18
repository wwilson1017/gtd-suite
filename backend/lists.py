"""todo-gtd — lists and their two tokens.

A browser reaches its list through a session cookie (sessions.py). The other two
ways in are tokens in an address, where the token IS the authorization and an
unknown token is a 404, never a 401:

  agent token    the MCP server: read and write todos, no link management
  capture token  write-only inbox drop

Each resolver checks only its own column, so a token of one kind is never
accepted on the other surface. They rotate independently, from a signed-in
browser; only the self-host reset replaces both at once (and signs every
browser out).

The agent token is stored as a SHA-256 hash (what a lookup matches) and also
plain, like the capture token, because the web app displays both. Keeping them
readable is not a security downgrade: a signed-in browser reads and changes
everything, and it is the only thing that can fetch them.
"""

import datetime
import hashlib
import json
import secrets
import string

from backend.paid import caps as paid_caps
from backend import apps, common, db, lifecycle, sessions, settings

# 43 letters and digits: 62**43 > 2**256, not enumerable. No - or _, which a chat's
# markdown pass escapes or italicises, so a pasted link survives a round trip as text.
_TOKEN_ALPHABET, _TOKEN_LENGTH = string.ascii_letters + string.digits, 43
_TOUCH_INTERVAL_SECONDS = 3600


def mint_token() -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def account_no_in(conn) -> str:
    """A random NNNN-NNNN that no list holds, inside the caller's transaction."""
    while True:
        number = f"{secrets.randbelow(9000) + 1000}-{secrets.randbelow(10000):04d}"
        if not conn.execute("SELECT 1 FROM lists WHERE account_no = ?", (number,)).fetchone():
            return number


def create_list(
    tz: str | None = None,
    name: str | None = None,
    *,
    only_if_none: bool = False,
    app: str = apps.ANCHOR,
    connect: str | None = None,
) -> dict | None:
    """Create a list and sign its creator in: the result carries the new
    session's token, for the cookie. ``app`` is the app it was made in, the one
    app it starts with on; made in Todo, Notes or Projects it starts with those
    three, and made at Common Brain, the suite's front door, with every app on.
    A new self-host account also starts with every app on.

    ``only_if_none`` is the self-host claim: the check, the insert and the
    session are one transaction, so of two first visitors exactly one gets a
    list and the other None."""
    agent, capture = mint_token(), mint_token()
    zone = common.validate_tz(tz)
    name = common.validate_list_name(name)
    with db.transaction() as conn:
        if only_if_none and conn.execute("SELECT 1 FROM lists LIMIT 1").fetchone():
            return None
        list_id = conn.execute(
            "INSERT INTO lists (agent_token_hash, agent_token, capture_token, tz, name, created_at, "
            "apps, account_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                hash_token(agent),
                agent,
                capture,
                zone,
                name,
                common.now_iso(),
                json.dumps(
                    list(apps.APPS)
                    if app == "brain" or not settings.open_signup()
                    else list(apps.FAMILY)
                    if app in apps.FAMILY
                    else [app]
                ),
                account_no_in(conn),
            ),
        ).lastrowid
        assert list_id is not None  # A successful INSERT into a rowid table.
        brain_id = conn.execute(
            "INSERT INTO brains (list_id, folder, created_at, updated_at) VALUES (?, 'brain', ?, ?)",
            (list_id, common.now_iso(), common.now_iso()),
        )
        conn.execute("UPDATE lists SET link_brains = ? WHERE id = ?", (json.dumps([brain_id.lastrowid]), list_id))
        if connect is not None:
            from backend.connect import created_in

            created_in(conn, connect, list_id)
        session = sessions.create_in(conn, list_id)
    return {
        "list_id": list_id,
        "agent_token": agent,
        "capture_token": capture,
        "tz": zone,
        "name": name,
        "session_token": session,
    }


def _resolve(column: str, value: str) -> int | None:
    # A single indexed lookup: the WHERE match IS the comparison. A list the
    # operator disabled (scripts/admin.py) matches nothing, so capture and MCP
    # answer it as an unknown link (sessions.resolve does the same for browsers).
    # So does a removed list (lifecycle.py): `>` is the exact complement of
    # lifecycle.state's `<=`, so at the boundary every surface agrees. An archived
    # list resolves, and its caller's touch brings it back.
    if not value:
        return None
    live, params = live_where()
    row = db.get_db().execute(f"SELECT id FROM lists WHERE {column} = ? AND {live}", [value, *params]).fetchone()
    return row["id"] if row else None


def live_where() -> tuple[str, list]:
    """The WHERE (on `lists`) that keeps a list neither disabled nor removed, and
    its parameters: _resolve's test, shared with sites.lookup so a published page
    goes dark exactly when its list's links do."""
    sql, params = "disabled_at IS NULL", []
    if lifecycle.enabled():
        sql += " AND (email_verified_at IS NOT NULL OR COALESCE(last_used_at, created_at) > ?)"
        params.append(lifecycle.removed_cutoff(common.utcnow()))
    return sql, params


def resolve_agent(token: str) -> int | None:
    return _resolve("agent_token_hash", hash_token(token or ""))


def resolve_capture(token: str) -> int | None:
    return _resolve("capture_token", token)


def get_list(list_id: int) -> dict | None:
    """The list's settings. Never includes the hashes."""
    row = (
        db.get_db()
        .execute(
            "SELECT id, account_no, name, agent_token, capture_token, tz, email, email_verified_at, "
            "created_at, last_used_at, review_started_at, disabled_at, apps, "
            f"{paid_caps.ACCOUNT_COLUMNS} FROM lists WHERE id = ?",
            (list_id,),
        )
        .fetchone()
    )
    return {**dict(row), "apps": _served(row["apps"])} if row else None


def served(app: str) -> bool:
    """Every registered app is served, on its configured host or the main host."""
    return app in apps.APPS


def _served(stored: str) -> list[str]:
    """The stored apps this server serves, in registry order."""
    on = set(json.loads(stored))
    return [key for key in apps.APPS if key in on and served(key)]


def apps_on(list_id: int) -> list[str]:
    """The apps turned on for the account that this server serves: what its agent
    link offers (mcp_server, agent_cmd)."""
    row = db.get_db().execute("SELECT apps FROM lists WHERE id = ?", (list_id,)).fetchone()
    return _served(row["apps"]) if row else []


def set_app_in(conn, list_id: int, app: str, on: bool) -> None:
    """Turn one app on or off for the account, inside the caller's transaction.
    Off hides it from the agent link and the menus; its data stays."""
    row = conn.execute("SELECT apps FROM lists WHERE id = ?", (list_id,)).fetchone()
    stored = [key for key in json.loads(row["apps"]) if key != app] + ([app] if on else [])
    conn.execute("UPDATE lists SET apps = ? WHERE id = ?", (json.dumps(stored), list_id))


def rotate_agent(list_id: int) -> str | None:
    """Replace the agent token. The old agent link stops working instantly."""
    token = mint_token()
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE lists SET agent_token = ?, agent_token_hash = ? WHERE id = ?",
            (token, hash_token(token), list_id),
        )
        if cur.rowcount == 0:
            return None
    return token


def any_list() -> bool:
    return db.get_db().execute("SELECT 1 FROM lists LIMIT 1").fetchone() is not None


def reset_single() -> str | None:
    """Self-host reset, for whoever holds RESET_CODE: THE list's every way in is
    replaced, and the new session's token is returned for the caller's cookie.
    None unless exactly one list exists.

    This is the operator taking the deployment back — possibly from a stranger
    who claimed it first — so every browser is signed out, unspent sign-in links
    are cancelled, program keys are revoked (keys.py), the agent and capture
    links are replaced, and the email and
    its confirmation are cleared (or the previous holder could simply ask for a
    new sign-in link)."""
    with db.transaction() as conn:
        rows = conn.execute("SELECT id FROM lists LIMIT 2").fetchall()
        if len(rows) != 1:
            return None
        list_id = rows[0]["id"]
        sessions.revoke_all_in(conn, list_id)
        conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE list_id = ? AND revoked_at IS NULL", (common.now_iso(), list_id)
        )
        agent = mint_token()
        conn.execute(
            "UPDATE lists SET agent_token = ?, agent_token_hash = ?, capture_token = ?, "
            "email = NULL, email_verified_at = NULL WHERE id = ?",
            (agent, hash_token(agent), mint_token(), list_id),
        )
        return sessions.create_in(conn, list_id)


def rotate_capture(list_id: int) -> str | None:
    """Replace the capture token. The old capture link stops working instantly."""
    token = mint_token()
    with db.transaction() as conn:
        cur = conn.execute("UPDATE lists SET capture_token = ? WHERE id = ?", (token, list_id))
        if cur.rowcount == 0:
            return None
    return token


def set_email_in(conn, list_id: int, email: str | None) -> tuple[str | None, bool]:
    """Set, change or clear (None/'') the list's email inside the caller's
    transaction: ``(stored, verified)``. A new address is unconfirmed, and the
    list's unspent sign-in links are cancelled — one already mailed to the old
    address must stop working. The same address again changes nothing. Sessions
    are left alone: the browser making the change stays signed in."""
    new = common.validate_email(email)
    row = conn.execute("SELECT email, email_verified_at FROM lists WHERE id = ?", (list_id,)).fetchone()
    if row is None or row["email"] == new:
        return new, bool(row and row["email_verified_at"])
    conn.execute("UPDATE lists SET email = ?, email_verified_at = NULL WHERE id = ?", (new, list_id))
    conn.execute("DELETE FROM signin_tokens WHERE list_id = ?", (list_id,))
    return new, False


def set_email(list_id: int, email: str | None) -> str | None:
    """set_email_in in its own transaction, mailing nothing (scripts/admin.py)."""
    with db.transaction() as conn:
        return set_email_in(conn, list_id, email)[0]


def verify_email_in(conn, list_id: int) -> None:
    """Stamp the list's email as confirmed, inside the caller's transaction:
    signin.redeem, for a link that was mailed to it."""
    conn.execute(
        "UPDATE lists SET email_verified_at = ? WHERE id = ? AND email_verified_at IS NULL", (common.now_iso(), list_id)
    )
    conn.execute("UPDATE sites SET expires_at = NULL WHERE list_id = ?", (list_id,))


def set_name(list_id: int, name: str | None) -> str:
    """Set, change or clear ('') the list's name; returns the stored value."""
    new = common.validate_list_name(name)
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET name = ? WHERE id = ?", (new, list_id))
    return new


def set_tz(list_id: int, tz: str) -> str:
    """Change the list's time zone; returns the stored value. Creation falls back
    to UTC for a browser that reports nonsense, but an explicit change to an
    unknown zone is refused — silently storing UTC would move the user's "today"."""
    if common.validate_tz(tz) != tz:
        raise common.ValidationError("Unknown time zone")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET tz = ? WHERE id = ?", (tz, list_id))
    return tz


def review_due(list_id: int) -> bool:
    """True when the last weekly review started more than seven days ago — or
    the list is that old and has never had one."""
    row = get_list(list_id)
    if not row:
        return False
    week_ago = common.to_iso(common.utcnow() - datetime.timedelta(days=7))
    return (row["review_started_at"] or row["created_at"]) < week_ago


def review_status(list_id: int) -> dict:
    """What the Review page shows: whether a weekly review is due (`review_due`,
    the agents' own answer, so the page and the hint cannot disagree) and how long
    ago the last one was, None when there has never been one.

    Counted in the list's CALENDAR days, not elapsed 24-hour periods: the page
    words it "today" / "yesterday", and a review marked at 23:50 must read as
    yesterday ten minutes later."""
    row = get_list(list_id)
    days = None
    if row and row["review_started_at"]:
        reviewed_on = common.local_date(row["review_started_at"], row["tz"])
        days = max(0, (common.business_today(row["tz"]) - reviewed_on).days)
    return {"review_due": review_due(list_id), "days_since_review": days}


def start_review(list_id: int) -> None:
    """Stamp a weekly review now: an agent starting one, or the Review page's
    "Mark review done". Either quiets the `review_due` hint for a week; the list
    keeps one stamp, not a start and a finish."""
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET review_started_at = ? WHERE id = ?", (common.now_iso(), list_id))


def touch(list_id: int) -> None:
    """Record that the list was used.

    # simplification: hour-granular — a read first, so most requests take no write lock
    """
    row = db.get_db().execute("SELECT last_used_at FROM lists WHERE id = ?", (list_id,)).fetchone()
    if not row:
        return
    last = row["last_used_at"]
    stale_before = common.utcnow() - datetime.timedelta(seconds=_TOUCH_INTERVAL_SECONDS)
    if last and last >= stale_before.strftime("%Y-%m-%dT%H:%M:%S"):
        return
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET last_used_at = ? WHERE id = ?", (common.now_iso(), list_id))
