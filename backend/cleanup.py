"""todo-gtd — abuse cleanup: remove lists that were never used.

The ONLY hard delete in the app, and it cannot reach anyone's data: a list
qualifies only with no row in any app's content tables (apps.py; archived rows
count), no email and no billing customer (plans/billing.py: the row is billing's only tie to
the account), more than 30 days after it was made. That is a "Create my list" click
that nobody came back to. An emailless trial account whose one site expired and was
deleted (sites.expire_sites, day 37) then holds nothing and qualifies too: that is the
end of a trial nobody kept, and a tool holding its link connects again.
"""

import datetime

from backend.plans import billing
from backend import apps, common, db


def _unused() -> str:
    return (
        "created_at < ? AND email IS NULL AND "
        + billing.NO_CUSTOMER_SQL
        + "".join(f" AND NOT EXISTS (SELECT 1 FROM {t} WHERE {t}.list_id = lists.id)" for t in apps.content_tables())
    )


def delete_unused_lists(days: int = 30) -> int:
    """How many were deleted. The condition is evaluated by the deleting
    statements themselves, inside the write transaction, so a list that gains
    its first todo in the meantime is kept.

    "Never used" is about content, not visits: a list that has only ever been
    opened still qualifies, and its sessions, sign-in links, program keys and record of AI
    tools (lists.seen_ai: an AI that connected and wrote nothing) go with it. The
    browser that made it then answers 401 on its next request and lands on the
    home page."""
    cutoff = common.to_iso(common.utcnow() - datetime.timedelta(days=days))
    unused = _unused()
    with db.transaction() as conn:
        conn.execute(
            f"DELETE FROM connect_codes WHERE list_id IN (SELECT id FROM lists WHERE {unused}) "
            f"OR created_list_id IN (SELECT id FROM lists WHERE {unused})",
            (cutoff, cutoff),
        )
        for table in ("sessions", "signin_tokens", "api_keys", "brains", "ai_tools"):
            conn.execute(
                f"DELETE FROM {table} WHERE list_id IN (SELECT id FROM lists WHERE {unused})",
                (cutoff,),
            )
        return conn.execute(f"DELETE FROM lists WHERE {unused}", (cutoff,)).rowcount
