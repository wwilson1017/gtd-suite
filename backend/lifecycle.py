"""todo-gtd — the idle lifecycle of a hosted list with no confirmed email.

A derived state, never a column and never a job: it is read from the list's
last use on any surface, ``COALESCE(last_used_at, created_at)``, and the clock.

  active    the default; always for a confirmed email, and always while the
            lifecycle is off (enabled())
  archived  idle IDLE_ARCHIVE_DAYS: the app shows "put away" and one button
            brings it back. The agent and capture links still work, and using
            them brings it back too: use means any surface.
  removed   idle IDLE_REMOVE_DAYS: the agent and capture links answer 404
            (lists._resolve) and the app's only way back is confirming an email,
            which keeps the list for good.

Nothing is erased. A browser's session still resolves in every state, so the
app can say which (router.active_owner refuses the rest of /api/app with 403).

enabled() is the one switch: open signup AND mail. A one-list server's list is
its whole point, and without mail no email can be confirmed, so a removed list
would have no way back: then lists never age.

# simplification: a removed list whose browsers are all signed out is unreachable and unerased — `scripts.admin signin-link` is the way back; erase if the volume ever matters
"""

import datetime

from backend import common, settings, signin


def enabled() -> bool:
    return settings.open_signup() and signin.available()


def _cutoff(now: datetime.datetime, days: int) -> str:
    return common.to_iso(now - datetime.timedelta(days=days))


def removed_cutoff(now: datetime.datetime) -> str:
    """A list last used at or before this instant is removed. lists._resolve
    keeps only those used strictly after it: the exact complement of state()."""
    return _cutoff(now, common.IDLE_REMOVE_DAYS)


def state(row) -> str:
    """'active', 'archived' or 'removed' for a lists row (it needs
    email_verified_at, last_used_at and created_at)."""
    if not enabled() or row["email_verified_at"] is not None:
        return "active"
    now = common.utcnow()
    idle = row["last_used_at"] or row["created_at"]
    if idle <= removed_cutoff(now):
        return "removed"
    if idle <= _cutoff(now, common.IDLE_ARCHIVE_DAYS):
        return "archived"
    return "active"
