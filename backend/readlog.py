"""The read log: Common Brain reads by AI tools, for the person's Security page only.

While the account's Enhanced security switch is on (lists.enhanced_security), each request
that returned Brain content leaves one row per brain it touched: when, which AI (its own
untrusted name, or the key's), which credential (key_id and key_kind; both empty is the
main agent link, and never a token), the operation, and for a read of one page, memory or
file, which one. Pages and memories number separately, so `item_kind` goes with `item_id`.
`target` is the path at the time, or a search's words. A file row means a download link was
handed out: the download itself goes straight to the file store.

Best effort: `log` runs after the read, never inside another transaction, and never fails
or delays it. Rows are kept 90 days (`expire`, daily, whatever the switch says). Forget
removes the item's rows in its own transaction (`forget_in`). Account bookkeeping, not
content, like ai_tools: out of apps.content_tables(), and its rows cascade with their list
and brain. No AI tool, command or REST route reads it.

# simplification: a replaced main link is not told apart from the one before it; a link
# generation number on lists, copied into each row, is the way up.
"""

import datetime
import logging

from backend import common, db

logger = logging.getLogger(__name__)

KEEP = datetime.timedelta(days=90)
PAGE = 100
MAX_TARGET = 500
# Where an item must still be for a row naming it to be written. A forgotten file is a
# tombstone (files.TOMBSTONES) until the sweeper deletes it.
_STILL_THERE = {
    "memory": "brain_memories WHERE",
    "page": "brain_pages WHERE",
    "file": "brain_files WHERE status NOT IN ('abandoned', 'forgotten') AND",
}


def log(
    list_id: int,
    brain_ids: list[int],
    by: str,
    key: dict | None,
    kind: str,
    item_kind: str | None = None,
    item_id: int | None = None,
    target: str = "",
) -> None:
    """One row per brain, only while the switch is on, and for a named item only while it
    is still in the account: the INSERT checks both itself, so a read that finishes just
    after a Forget cannot put the forgotten item's path back. Everything is an argument
    (REST's own routes run outside the MCP contextvars). A failure is logged and swallowed."""
    try:
        # A read first, as lists.seen_ai: with the switch off, no write lock is taken.
        if not db.get_db().execute("SELECT 1 FROM lists WHERE id = ? AND enhanced_security", (list_id,)).fetchone():
            return
        still_there = (
            f"AND EXISTS (SELECT 1 FROM {_STILL_THERE[item_kind]} id = ? AND list_id = l.id)" if item_kind else ""
        )
        with db.transaction() as conn:
            for brain_id in brain_ids:
                conn.execute(
                    "INSERT INTO brain_reads "
                    "(list_id, brain_id, at, by, key_id, key_kind, kind, item_kind, item_id, target) "
                    "SELECT l.id, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM lists l WHERE l.id = ? AND l.enhanced_security "
                    + still_there,
                    (
                        brain_id,
                        common.now_iso(),
                        by,
                        key["id"] if key else None,
                        key["kind"] if key else None,
                        kind,
                        item_kind,
                        item_id,
                        (target or "")[:MAX_TARGET],
                        list_id,
                        *((item_id,) if item_kind else ()),
                    ),
                )
    except Exception as e:
        # The read this records has already been answered for.
        logger.warning("a Brain read was not logged: %s", type(e).__name__)


def forget_in(conn, list_id: int, item_kind: str, item_ids: list[int]) -> None:
    """Forget's own transaction: every row naming the item, whatever the operation and
    whichever brain it was read in (a moved item's old rows keep their brain)."""
    conn.executemany(
        "DELETE FROM brain_reads WHERE list_id = ? AND item_kind = ? AND item_id = ?",
        [(list_id, item_kind, i) for i in item_ids],
    )


def recent(list_id: int, before: int | None = None) -> list[dict]:
    """The newest PAGE rows of the last 90 days, older than row `before`: filtered here, so
    a row past 90 days never shows while it waits for the daily sweep."""
    return [
        dict(r)
        for r in db.get_db().execute(
            "SELECT r.id, r.at, r.by, r.kind, r.item_kind, r.target, b.name AS brain, r.key_kind, k.name AS key_name "
            "FROM brain_reads r JOIN brains b ON b.id = r.brain_id LEFT JOIN api_keys k ON k.id = r.key_id "
            "WHERE r.list_id = ? AND r.at > ? AND r.id < ? ORDER BY r.id DESC LIMIT ?",
            (list_id, common.to_iso(common.utcnow() - KEEP), before if before is not None else 2**62, PAGE),
        )
    ]


def expire(now: datetime.datetime) -> int:
    """Drop rows past 90 days; how many."""
    with db.transaction() as conn:
        return conn.execute("DELETE FROM brain_reads WHERE at <= ?", (common.to_iso(now - KEEP),)).rowcount
