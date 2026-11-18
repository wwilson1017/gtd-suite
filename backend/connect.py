"""Device-style Sites connection: the browser approves, the device collects once."""

import re
import secrets
from datetime import timedelta

from backend import common, db, lists
from backend.common import NotFoundError, ValidationError

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE = re.compile(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}")
SECONDS = 900


def start() -> dict:
    token = lists.mint_token()
    now = common.utcnow()
    with db.transaction() as conn:
        while True:
            chars = "".join(secrets.choice(_ALPHABET) for _ in range(8))
            code = chars[:4] + "-" + chars[4:]
            if not conn.execute("SELECT 1 FROM connect_codes WHERE user_code = ?", (code,)).fetchone():
                break
        conn.execute(
            "INSERT INTO connect_codes (device_hash, user_code, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (lists.hash_token(token), code, common.to_iso(now), common.to_iso(now + timedelta(seconds=SECONDS))),
        )
    return {"user_code": code, "device_token": token, "interval": 3, "expires_in": SECONDS}


def _pending_in(conn, code: str):
    if not _CODE.fullmatch(code):
        raise NotFoundError("Connection code not found")
    row = conn.execute(
        "SELECT * FROM connect_codes WHERE user_code = ? AND expires_at > ? AND approved_at IS NULL",
        (code, common.now_iso()),
    ).fetchone()
    if row is None:
        raise NotFoundError("Connection code expired or already used")
    return row


def created_in(conn, code: str, list_id: int) -> None:
    row = _pending_in(conn, code)
    if row["created_list_id"] is not None:
        raise ValidationError("This code already created an account. Start connect again.")
    conn.execute("UPDATE connect_codes SET created_list_id = ? WHERE user_code = ?", (list_id, code))


def approve(list_id: int, code: str, typed_code: str | None) -> None:
    with db.transaction() as conn:
        row = _pending_in(conn, code)
        live, params = lists.live_where()
        if not conn.execute(f"SELECT 1 FROM lists WHERE id = ? AND {live}", (list_id, *params)).fetchone():
            raise NotFoundError("Account unavailable")
        typed = re.sub(r"[^A-Z0-9]", "", (typed_code or "").upper())
        if row["created_list_id"] != list_id and typed[:4] + "-" + typed[4:] != code:
            raise ValidationError("Type the code shown in your terminal to approve this connection.")
        lists.set_app_in(conn, list_id, "sites", True)
        conn.execute(
            "UPDATE connect_codes SET list_id = ?, approved_at = ? WHERE user_code = ?",
            (list_id, common.now_iso(), code),
        )


def poll(token: str) -> dict | None:
    if len(token) != lists._TOKEN_LENGTH or not token.isascii() or not token.isalnum():
        return None
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM connect_codes WHERE device_hash = ? AND expires_at > ?",
            (lists.hash_token(token), common.now_iso()),
        ).fetchone()
        if row is None:
            return None
        live, params = lists.live_where()
        # A newly created account can be disabled even before its approval.
        owner = row["list_id"] or row["created_list_id"]
        account = (
            conn.execute(f"SELECT agent_token FROM lists WHERE id = ? AND {live}", (owner, *params)).fetchone()
            if owner is not None
            else None
        )
        if owner is not None and account is None:
            return None
        if row["approved_at"] is None:
            return {"status": "pending"}
        assert account is not None  # Approved codes always bind a live account.
        conn.execute("DELETE FROM connect_codes WHERE device_hash = ?", (row["device_hash"],))
        return {"status": "approved", "agent_token": account["agent_token"]}


def expire(now) -> int:
    with db.transaction() as conn:
        return conn.execute("DELETE FROM connect_codes WHERE expires_at <= ?", (common.to_iso(now),)).rowcount
