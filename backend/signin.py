"""todo-gtd — sign-in links: the one way onto a new device.

A sign-in link is /signin/<token>: one hour, single use, stored only as a
SHA-256 hash. Opening it shows a page whose button POSTs the redemption, which
signs that browser in to the list (a new session, sessions.py). The same token
is issued three ways:

  to confirm   saving an email under Connect (PUT /api/app/email) mails one link
               to the new address; ``mailed_to`` holds it. An address another list
               has confirmed is mailed links back to THAT list instead: one
               account per address
  by email    POST /api/signin mails one message with a link per list whose
               email is that address and CONFIRMED; ``mailed_to`` likewise
  in the app   Connect → "Sign in on another device" shows a link and a QR code;
               ``mailed_to`` is NULL

Redeeming a mailed link proves the address, so it also confirms the list's email
(``lists.email_verified_at``) if it was not already. A mailed link whose address
is no longer the list's email is an unknown link: changing the email cancels the
list's links (lists.set_email_in), and redeem checks it again. At most
MAX_OUTSTANDING_PER_LIST unspent links per list: issuing one more cancels the
oldest.

Mail goes through Resend's HTTP API as plain text: there is no HTML for click
tracking to rewrite, and tracking must stay off on the sending domain (Resend's
default) or the links would pass through a third party. Without RESEND_API_KEY,
MAIL_FROM and a configured base address (never a request's Host header, which an
attacker could forge into the mailed link) there is no mail and the UI hides it.

# simplification: anyone signed in to a list can put a stranger's address on it — inherent to passwordless email; the confirmation mail holds only our words and says to ignore it, and only a confirmed address gets sign-in mail
"""

import datetime
import logging
import os

import httpx2 as httpx

from backend import apps, common, db, lists, sessions, settings
from backend.ratelimit import IPRateLimiter

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
TOKEN_TTL = datetime.timedelta(hours=1)
MAX_LISTS = 10  # per message: the most recently used
MAX_OUTSTANDING_PER_LIST = 10

# One message per address per 15 minutes, however many people ask.
# simplification: in memory, so a restart forgets it; the per-IP limit still holds
address_limiter = IPRateLimiter(window=900, max_hits=1)
# Confirmation mail has its own per-address budget. If it shared address_limiter,
# PUT /api/app/email's `sent` would reveal whether /api/signin had just found a
# confirmed list for the address (that path spends the budget only when one exists).
confirm_limiter = IPRateLimiter(window=900, max_hits=1)


def available() -> bool:
    return bool(os.environ.get("RESEND_API_KEY") and os.environ.get("MAIL_FROM") and settings.configured_base_url())


def _send(to: str, subject: str, text: str) -> None:
    res = httpx.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={"from": os.environ["MAIL_FROM"], "to": [to], "subject": subject, "text": text},
        timeout=15,
    )
    res.raise_for_status()


def _message(links: list[tuple[str, dict]], more: bool, title: str) -> str:
    lines = [
        f"Someone asked to sign in to the {title} list(s) that use this address.",
        "",
        "Each link below works once, for one hour. It opens a page with an "
        '"Open my list on this device" button; nothing happens until you press it. '
        "Pressing it signs that browser in to the list. Nothing else changes.",
        "",
    ]
    for n, (url, row) in enumerate(links, 1):
        used = (row["last_used_at"] or row["created_at"])[:10]
        # No list name: it is text anyone signed in to the list can write, and a
        # mail carries only our own words.
        lines += [f"List {n} (created {row['created_at'][:10]}, last used {used}):", url, ""]
    if more:
        lines += [
            f"This address is on more than {MAX_LISTS} lists; only the {MAX_LISTS} most recently used are included.",
            "",
        ]
    lines.append("If you did not ask for this, ignore this message. Nothing has changed.")
    return "\n".join(lines)


def _verification_message(url: str, title: str) -> str:
    return "\n".join(
        [
            f"Someone added this address to a {title} list. To confirm it, open this link and "
            'press "Open my list on this device":',
            "",
            url,
            "",
            "It works once, for one hour, and signs in the device that opens it. A confirmed "
            "email keeps the list for good and lets you sign in to it from any device.",
            "",
            "If you did not add this address to a list, ignore this message.",
        ]
    )


def confirmed_elsewhere_in(conn, email: str, list_id: int) -> list[dict]:
    """The other lists that already have ``email`` CONFIRMED, most recently used
    first: an address belongs to one account, so PUT /api/app/email mails these a
    way back in instead of confirming it a second time. A disabled list is
    included (it still holds its address, and the operator may enable it again);
    ``disabled`` says not to mail it a link, which could not be redeemed."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, created_at, last_used_at, disabled_at IS NOT NULL AS disabled FROM lists "
            "WHERE email = ? AND id != ? AND email_verified_at IS NOT NULL "
            "ORDER BY COALESCE(last_used_at, created_at) DESC LIMIT ?",
            (email, list_id, MAX_LISTS),
        ).fetchall()
    ]


def _existing_message(links: list[tuple[str, dict]], title: str) -> str:
    lines = [
        f"Someone added this address to a new {title} list, but it already belongs to "
        "your account. To go back to it, open the link below and press "
        '"Open my list on this device":',
        "",
    ]
    for url, row in links:
        used = (row["last_used_at"] or row["created_at"])[:10]
        lines += [f"Account created {row['created_at'][:10]}, last used {used}:", url, ""]
    lines += [
        "Each link works once, for one hour, and signs in the device that opens it. "
        "Your notes, todos and everything else are where you left them.",
        "",
        "If you did not do this, ignore this message. Nothing has changed.",
    ]
    return "\n".join(lines)


def send_existing(links: list[tuple[str, dict]], email: str, app: str = apps.ANCHOR) -> None:
    """Mail the way back to the account that already has this address, the links
    PUT /api/app/email minted in place of a confirmation. Runs after the response
    and raises nothing; a failed send lets the address ask again."""
    title = apps.APPS[app].title
    try:
        _send(email, f"You already have a {title} account", _existing_message(links, title))
    except Exception as e:
        confirm_limiter.forget(email)
        # The type only: the message could carry the address or a link.
        logger.error("Existing-account mail failed: %s", type(e).__name__)


def send_verification(url: str, email: str, app: str = apps.ANCHOR) -> None:
    """Mail the confirmation link PUT /api/app/email minted, in the words of the
    app it was asked from. Runs after the response and raises nothing; a failed
    send lets the address ask again."""
    title = apps.APPS[app].title
    try:
        _send(email, f"Confirm your email for {title}", _verification_message(url, title))
    except Exception as e:
        confirm_limiter.forget(email)
        # The type only: the message could carry the address or the link.
        logger.error("Confirmation mail failed: %s", type(e).__name__)


def send_new_ai(email: str) -> None:
    """Enhanced security's alert (lists.seen_ai): a new AI tool has used the agent link. Our
    own words only: the tool's name is its own claim, so it stays out of the mail. Runs on
    its own thread and raises nothing.

    # simplification: a failed send is not retried, the day's one alert is spent; a queue is the way up
    """
    try:
        _send(
            email,
            "A new AI tool connected to your account",
            "\n".join(
                [
                    "One or more new AI tools used your agent link for the first time.",
                    "",
                    f"To see which, open {apps.settings_page()} and look under Connect your AI:",
                    f"{settings.configured_base_url()}/app/connect/ai",
                    "",
                    "If that was not you, make a new agent link there: the old one stops working at once.",
                    "",
                    "You get this message, once a day at most, because Enhanced security is on for "
                    f"your account. Turn it off under Security, in {apps.settings_page()}.",
                ]
            ),
        )
    except Exception as e:
        # The type only: the message could carry the address.
        logger.error("New-AI mail failed: %s", type(e).__name__)


def issue_link_in(conn, list_id: int, *, mailed_to: str | None = None) -> tuple[str, str]:
    """A new sign-in token for the list, inside the caller's transaction:
    ``(token, expires_at)``. Beyond MAX_OUTSTANDING_PER_LIST the oldest by
    (expires_at, rowid) are cancelled, never the one just issued."""
    token = lists.mint_token()
    expires_at = common.to_iso(common.utcnow() + TOKEN_TTL)
    rowid = conn.execute(
        "INSERT INTO signin_tokens (token_hash, list_id, expires_at, mailed_to) VALUES (?, ?, ?, ?)",
        (lists.hash_token(token), list_id, expires_at, mailed_to),
    ).lastrowid
    conn.execute(
        "DELETE FROM signin_tokens WHERE rowid IN (SELECT rowid FROM signin_tokens "
        "WHERE list_id = ? AND rowid != ? ORDER BY expires_at DESC, rowid DESC "
        "LIMIT -1 OFFSET ?)",
        (list_id, rowid, MAX_OUTSTANDING_PER_LIST - 1),
    )
    return token, expires_at


def issue_link(list_id: int) -> tuple[str, str]:
    """A link for Connect's "Sign in on another device" (not mailed)."""
    with db.transaction() as conn:
        return issue_link_in(conn, list_id)


def request_signin(email: str, base_url: str, app: str = apps.ANCHOR) -> None:
    """Mail ``email`` a sign-in link for each list that has it as a CONFIRMED
    email, if there is any: an unconfirmed address may be a stranger's.

    Returns nothing and raises nothing: the HTTP answer is the same whether or
    not the address is known, and this runs after that answer has been sent."""
    try:
        links: list[tuple[str, dict]] = []
        with db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, name, created_at, last_used_at FROM lists "
                "WHERE email = ? AND email_verified_at IS NOT NULL AND disabled_at IS NULL "
                "ORDER BY COALESCE(last_used_at, created_at) DESC LIMIT ?",
                (email, MAX_LISTS + 1),
            ).fetchall()
            if not rows or not address_limiter.allow(email):
                return
            for row in rows[:MAX_LISTS]:
                token, _ = issue_link_in(conn, row["id"], mailed_to=email)
                links.append((f"{base_url}/signin/{token}", dict(row)))
        try:
            title = apps.APPS[app].title
            _send(email, f"Your {title} sign-in link", _message(links, len(rows) > MAX_LISTS, title))
        except Exception:
            address_limiter.forget(email)  # nothing arrived, so let them ask again
            raise
    except Exception as e:
        # The type only: the message could carry the address or a link.
        logger.error("Sign-in mail failed: %s", type(e).__name__)


def redeem(token: str, app: str = apps.ANCHOR) -> dict | None:
    """Spend a sign-in token: ``{list_id, session_token, verified}``, or None.

    One transaction finds the token, deletes it (that one only), checks it,
    confirms the list's email when the link was mailed to it, turns on ``app``
    (the app of the host it was redeemed on), and signs the browser in. The write lock serializes two redemptions of one token: the
    second finds no row. A disabled list redeems nothing, and its tokens are kept
    for when the operator enables it again."""
    token_hash = lists.hash_token(token or "")
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT t.list_id, t.expires_at, t.mailed_to, l.email, l.email_verified_at "
            "FROM signin_tokens t JOIN lists l ON l.id = t.list_id "
            "WHERE t.token_hash = ? AND l.disabled_at IS NULL",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM signin_tokens WHERE token_hash = ?", (token_hash,))
        if row["expires_at"] <= common.now_iso():
            return None
        mailed = row["mailed_to"] is not None
        if mailed and row["mailed_to"] != row["email"]:
            return None
        # One account per address: a confirmation link minted before another list
        # confirmed the address still signs in, but confirms nothing.
        if mailed and not confirmed_elsewhere_in(conn, row["mailed_to"], row["list_id"]):
            lists.verify_email_in(conn, row["list_id"])
        else:
            mailed = False
        lists.set_app_in(conn, row["list_id"], app, True)
        return {
            "list_id": row["list_id"],
            "session_token": sessions.create_in(conn, row["list_id"]),
            "verified": mailed or row["email_verified_at"] is not None,
        }


def expire(now: datetime.datetime) -> int:
    """Drop sign-in tokens past their hour; how many."""
    with db.transaction() as conn:
        return conn.execute("DELETE FROM signin_tokens WHERE expires_at <= ?", (common.to_iso(now),)).rowcount
