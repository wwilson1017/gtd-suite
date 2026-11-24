"""Device-style connection: the browser approves, the device collects the agent link once.

A code is for a client: "sites" (an AI tool connecting to Simple Sites) or "springform" (a
Springform install linking the account: every app on and, on the hosted service, the free grant
for an account with a confirmed email; plans/admin.springform_comp_in)."""

import re
import secrets
from datetime import timedelta

from backend import apps, common, db, lists, settings
from backend.plans import admin as plan_admin
from backend.common import NotFoundError, ValidationError

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE = re.compile(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}")
SECONDS = 900


def start(client: str = "sites") -> dict:
    token = lists.mint_token()
    now = common.utcnow()
    with db.transaction() as conn:
        while True:
            chars = "".join(secrets.choice(_ALPHABET) for _ in range(8))
            code = chars[:4] + "-" + chars[4:]
            if not conn.execute("SELECT 1 FROM connect_codes WHERE user_code = ?", (code,)).fetchone():
                break
        conn.execute(
            "INSERT INTO connect_codes (device_hash, user_code, client, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                lists.hash_token(token),
                code,
                client,
                common.to_iso(now),
                common.to_iso(now + timedelta(seconds=SECONDS)),
            ),
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


def approve(
    list_id: int, code: str, typed_code: str | None, client: str = "sites", own_host: bool | None = None
) -> None:
    """``client`` is what the approve page told the person it was connecting; a code for
    another client is refused, so the page's wording always matches what approval does."""
    with db.transaction() as conn:
        row = _pending_in(conn, code)
        live, params = lists.live_where()
        account = conn.execute(
            f"SELECT email_verified_at FROM lists WHERE id = ? AND {live}", (list_id, *params)
        ).fetchone()
        if account is None:
            raise NotFoundError("Account unavailable")
        if row["client"] != client:
            raise ValidationError("This page is out of date for this code. Open the connect link again.")
        typed = re.sub(r"[^A-Z0-9]", "", (typed_code or "").upper())
        if row["created_list_id"] != list_id and typed[:4] + "-" + typed[4:] != code:
            raise ValidationError("Type the code shown in your terminal to approve this connection.")
        if client == "springform":
            hosted = settings.open_signup()
            if hosted and account["email_verified_at"] is None:
                raise ValidationError(
                    "Add your email and confirm it first (open the link we mail you), then approve this connection."
                )
            for app in apps.APPS:
                lists.set_app_in(conn, list_id, app, True)
            if hosted:
                plan_admin.springform_comp_in(conn, list_id)
        else:
            lists.set_app_in(conn, list_id, "sites", True)
            if own_host is True:
                conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (list_id,))
        conn.execute(
            "UPDATE connect_codes SET list_id = ?, approved_at = ? WHERE user_code = ?",
            (list_id, common.now_iso(), code),
        )
        # The person handing the agent link to a device is its use: Enhanced security's idle
        # clock starts now, so the link the device collects answers.
        conn.execute("UPDATE lists SET agent_used_at = ? WHERE id = ?", (common.now_iso(), list_id))


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
