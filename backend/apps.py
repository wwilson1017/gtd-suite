"""todo-gtd — the suite: every app this one service serves.

Each app has its own front door (a domain, set in its base-URL variable) and they
all share one account (the `lists` row), one database and one agent link. The
host a request came in on picks the app (settings.app_for); the same paths
(/, /app, /api/app, /signin/…) serve it there.

Adding an app is one entry here. `tables` are its per-list content tables,
children first: cleanup.py keeps a list that has a row in any of them,
scripts/admin.py deletes them for `delete`, and scripts/restore_list.py restores
them. Leaving a table out means a list that only uses that app is deleted after
30 days as "never used".
"""

from typing import NamedTuple


class App(NamedTuple):
    title: str  # the product's name, e.g. "Todo GTD"
    short: str  # the installed app's name, e.g. "Todos"
    base_env: str  # the variable holding its address, e.g. https://todogtd.com
    tables: tuple[str, ...]  # its content tables, children first


# The first entry is the anchor: a request on any other host is for it.
APPS: dict[str, App] = {
    "todo": App("Todo GTD", "Todos", "PUBLIC_BASE_URL", ("todos", "projects", "areas")),
    "projects": App(
        "Projects GTD",
        "Projects",
        "PROJECTS_BASE_URL",
        (
            "rule_fired",
            "rules",
            "readings",
            "boosts",
            "bookmarks",
            "events",
            "recordings",
            "cards",
            "labels",
            "board_columns",
            "boards",
            "people",
        ),
    ),
    "sites": App(
        "Simple Sites",
        "Sites",
        "SITES_BASE_URL",
        ("site_data_fields", "site_data", "site_files", "site_blobs", "sites"),
    ),
    "notes": App("Notes GTD", "Notes", "NOTES_BASE_URL", ("notes",)),
    "brain": App(
        "Common Brain",
        "Brain",
        "BRAIN_BASE_URL",
        ("brain_files", "brain_misses", "brain_ais", "brain_versions", "brain_pages", "brain_memories"),
    ),
}
ANCHOR = next(iter(APPS))
# The apps that live together at the main address on the hosted service: Notes and
# Projects at its /notes and /projects, whatever host they also have (settings.old_url).
FAMILY = ("todo", "notes", "projects")


def content_tables() -> tuple[str, ...]:
    """Every app's content tables, children first."""
    return tuple(t for app in APPS.values() for t in app.tables)


def off_message(key: str) -> str:
    """What the agent link answers for an app the account has turned off."""
    return (
        f"{APPS[key].title} is off for this account. The person can turn it on under "
        "Settings, in Apps, in any app on their account."
    )
