"""todo-gtd — browser sessions: how a browser stays signed in to one list.

A session is one signed-in browser. Its cookie (COOKIE) holds a random token and
the ``sessions`` table holds only that token's SHA-256 hash, the list, and when it
was made and last used. Every /api/app request resolves the cookie here
(router.session_owner).

The cookie is set by three things only — creating a list, redeeming a sign-in
link, the self-host reset — and NOTHING ever clears it. Signing out revokes the
row and leaves the cookie in place: a stale cookie is harmless (the app answers
401 and the browser goes to /, where the next sign-in overwrites it), whereas a
sign-out response that cleared it could erase a sign-in another tab had just
finished. The cookie lasts a year from sign-in with no renewal; the row's
last_used_at slides, and expire() drops rows idle for a year.

At most MAX_PER_LIST sessions per list: signing in one more browser revokes the
least recently used, so a throwaway list cannot grow the table.

Named revoke, not delete: these rows are not content, and
test_no_delete_functions_exist pins the modules that hold content.
"""

import datetime

from fastapi import Response

from backend import common, db, lists, settings

COOKIE = "todogtd_session"
MAX_PER_LIST = 20
LIFETIME = datetime.timedelta(days=365)
_TOUCH_INTERVAL = datetime.timedelta(hours=1)


def create_in(conn, list_id: int) -> str:
    """A new session for the list, inside the caller's transaction; returns the
    token for the cookie. Beyond MAX_PER_LIST the oldest by (last_used_at, rowid)
    are revoked, never the one just made: to_iso is millisecond-precise, and a
    frozen clock ties."""
    token = lists.mint_token()
    now = common.now_iso()
    rowid = conn.execute(
        "INSERT INTO sessions (token_hash, list_id, created_at, last_used_at) VALUES (?, ?, ?, ?)",
        (lists.hash_token(token), list_id, now, now),
    ).lastrowid
    conn.execute(
        "DELETE FROM sessions WHERE rowid IN (SELECT rowid FROM sessions "
        "WHERE list_id = ? AND rowid != ? ORDER BY last_used_at DESC, rowid DESC "
        "LIMIT -1 OFFSET ?)",
        (list_id, rowid, MAX_PER_LIST - 1),
    )
    return token


def resolve(token: str | None) -> dict | None:
    """The live session behind a cookie value — ``{token_hash, list_id}`` — or
    None: missing, unknown, revoked, idle for a year, or the list is disabled."""
    if not token:
        return None
    cutoff = common.to_iso(common.utcnow() - LIFETIME)
    row = (
        db.get_db()
        .execute(
            "SELECT s.token_hash, s.list_id FROM sessions s JOIN lists l ON l.id = s.list_id "
            "WHERE s.token_hash = ? AND l.disabled_at IS NULL AND s.last_used_at >= ?",
            (lists.hash_token(token), cutoff),
        )
        .fetchone()
    )
    return dict(row) if row else None


def touch(token_hash: str) -> None:
    """Record that the session was used: the row only, never the cookie.

    # simplification: hour-granular — a read first, so most requests take no write lock (as lists.touch)
    """
    row = db.get_db().execute("SELECT last_used_at FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
    if not row or row["last_used_at"] >= common.to_iso(common.utcnow() - _TOUCH_INTERVAL):
        return
    with db.transaction() as conn:
        conn.execute("UPDATE sessions SET last_used_at = ? WHERE token_hash = ?", (common.now_iso(), token_hash))


def revoke(token: str | None) -> None:
    """Sign one browser out. Its cookie stays, and answers 401 from now on."""
    if token:
        with db.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (lists.hash_token(token),))


def revoke_all_in(conn, list_id: int) -> None:
    """Sign every browser out of the list and cancel its unspent sign-in links,
    inside the caller's transaction (sign out everywhere, the self-host reset)."""
    conn.execute("DELETE FROM sessions WHERE list_id = ?", (list_id,))
    conn.execute("DELETE FROM signin_tokens WHERE list_id = ?", (list_id,))


def revoke_all(list_id: int) -> None:
    with db.transaction() as conn:
        revoke_all_in(conn, list_id)


def set_cookie(response: Response, token: str) -> None:
    """For create, redeem and reset only. ``Secure`` follows the configured base
    address: behind Railway the app itself sees plain http."""
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(LIFETIME.total_seconds()),
        path="/",
        secure=settings.cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def expire(now: datetime.datetime) -> int:
    """Drop sessions idle for a year (their cookies have expired too); how many."""
    with db.transaction() as conn:
        return conn.execute("DELETE FROM sessions WHERE last_used_at < ?", (common.to_iso(now - LIFETIME),)).rowcount
