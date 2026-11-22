"""todo-gtd — leaf module: constants, errors, validation, recurrence math.

Imports only paid limit data from this app (no cycles) and never imports FastAPI — the
service layer raises the typed errors here and the router maps them to HTTP.
"""

import calendar
import datetime
import re
from zoneinfo import ZoneInfo

from backend.plans import caps

TODO_STATUSES = (
    "inbox",
    "next_action",
    "waiting_for",
    "delegated",
    "someday_maybe",
    "done",
    "dropped",
)
PROJECT_STATUSES = ("active", "someday", "completed", "dropped")
AREA_STATUSES = ("active", "dropped")
# Which surface CREATED the row. Never client-supplied: the web API sets 'ui',
# the capture endpoint 'capture', the MCP tools 'agent'.
TODO_SOURCES = ("ui", "capture", "agent")

MAX_TEXT_CHARS = 20_000
# Short-field caps, enforced at the SERVICE layer: bulk_update's fields dict
# and the agent tools never pass through the typed Pydantic models, so the
# models' max_length alone doesn't bound what reaches the UPDATE.
MAX_SHORT_CHARS = 500
MAX_TAGS = 50
MAX_SOURCE_CLIENT_CHARS = 100
MAX_EMAIL_CHARS = 254
MAX_LIST_NAME_CHARS = 80
# A list's name is OPTIONAL. Making it REQUIRED is a one-line change: set the flag
# to True, and creating a list without one (or clearing it later) is refused with
# a 400. POST /api/lists already accepts it. (The email is added after creation,
# under Connect, so it has no such flag.)
LIST_NAME_REQUIRED = False

# Per-list totals as (todos, projects, areas). Archived (done/dropped) rows
# count, since nothing is ever deleted. A hosted list holds little until its email
# is confirmed; a one-list self-host is never anonymous. Text-field limits are
# the same everywhere. A list over a cap (its email was removed) keeps what it has.
ANON_CAPS = (200, 20, 10)
VERIFIED_CAPS = (5_000, 1_000, 100)
SELF_HOST_CAPS = (20_000, 1_000, 100)
# Projects GTD's (boards, cards) under the same rules; columns per board are fixed.
BOARD_ANON_CAPS = (10, 200)
BOARD_VERIFIED_CAPS = (100, 5_000)
BOARD_SELF_HOST_CAPS = (1_000, 20_000)
MAX_COLUMNS = 12
# Simple Sites' (pages, short links): one page before an email is confirmed and no
# links (an anonymous redirector is what spam looks for); the free tier after that.
SITE_ANON_CAPS = (1, 0)
SITE_VERIFIED_CAPS = (500, 500)
SITE_SELF_HOST_CAPS = (10_000, 10_000)
SITE_MAX_FILES = 1000
SITE_MAX_PENDING = 2000
SITE_MAX_BYTES = 2_000_000  # a page's content, as UTF-8, on the default page limit
SITE_BIG_PAGE_BYTES = 10_000_000  # the larger page limit and self-hosted ceiling
# Common Brain's (connected AIs, active memories, active pages); None means no limit.
BRAIN_ANON_CAPS = (1, 50, 10)
BRAIN_VERIFIED_CAPS = (None, 2_000, 2_000)
BRAIN_SELF_HOST_CAPS = (None, 1_000_000, 1_000_000)
# Common Brain's files, bytes per list: none before an email is confirmed.
FILE_VERIFIED_QUOTA = 500_000_000
FILE_SELF_HOST_QUOTA = 100_000_000_000

# Notes GTD's notes per list, under the same rules.
NOTE_ANON_CAP, NOTE_VERIFIED_CAP, NOTE_SELF_HOST_CAP = 200, 5_000, 20_000
# Projects recordings per list (comments and boosts count), picked as the notes caps are.
RECORDING_ANON_CAP, RECORDING_VERIFIED_CAP, RECORDING_SELF_HOST_CAP = 2_000, 50_000, 200_000

# A hosted list with no confirmed email is put away after this many days without
# use on any surface, and put away for good after this many (lifecycle.py).
# Nothing is erased; a confirmed email brings it back and stops the clock.
IDLE_ARCHIVE_DAYS = 60
IDLE_REMOVE_DAYS = 180

# Brain tickle: a tickled todo rests this many of the list's calendar days before
# it can be offered again, and after this many tickles it comes back flagged
# stale — "decide: do, defer or drop".
TICKLE_REST_DAYS = 5
TICKLE_STALE_COUNT = 3

# Weekly review: an open, committed todo nobody has touched for this long is
# "stale", and dated items this far ahead count as "upcoming".
REVIEW_STALE_DAYS = 14
REVIEW_UPCOMING_DAYS = 14

# '' means no repeat. 'every:N' (N days) is validated by _EVERY_RE, not the tuple.
REPEAT_OPTIONS = ("", "daily", "weekdays", "weekly", "monthly", "yearly")
_EVERY_RE = re.compile(r"^every:([1-9][0-9]{0,3})$")

TODO_FIELDS = frozenset(
    {
        "title",
        "notes",
        "project",
        "project_id",
        "area_id",
        "context",
        "tags",
        "people",
        "status",
        "star",
        "due_date",
        "revisit_on",
        "repeat",
        "auto_star_on_due",
    }
)
PROJECT_FIELDS = frozenset({"name", "notes", "status", "purpose", "outcome", "area_id"})
AREA_FIELDS = frozenset({"name", "notes", "status"})

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ValidationError(ValueError):
    """Bad input from a client or agent — maps to HTTP 400."""


class NotFoundError(Exception):
    """Row absent (or not in the caller's list — indistinguishable on purpose)."""


class ConflictError(Exception):
    """The write needs the caller's confirmation first — maps to HTTP 409."""


def utcnow() -> datetime.datetime:
    """The one clock read in the app (tests replace it)."""
    return datetime.datetime.now(datetime.timezone.utc)


def to_iso(instant: datetime.datetime) -> str:
    """ISO-8601 UTC with a Z suffix; fixed width, so it sorts as text."""
    return instant.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso() -> str:
    return to_iso(utcnow())


def validate_tz(tz) -> str:
    """The browser-supplied IANA zone name if it is real, else 'UTC'."""
    if isinstance(tz, str) and 0 < len(tz) <= 64:
        try:
            ZoneInfo(tz)
            return tz
        except (ValueError, KeyError, OSError):
            pass
    return "UTC"


def business_today(tz: str) -> datetime.date:
    """The current calendar date in the list's timezone.

    A due date carries the user's LOCAL calendar intent, and the server runs
    UTC, so the server's own date rolls over hours early or late for most
    users. Every "today" decision (spawn, auto-star, today view) reads this.
    """
    return utcnow().astimezone(ZoneInfo(validate_tz(tz))).date()


def local_date(instant: str, tz: str) -> datetime.date:
    """The calendar date a stored instant (to_iso) fell on in the list's timezone."""
    return datetime.datetime.fromisoformat(instant).astimezone(ZoneInfo(validate_tz(tz))).date()


def tickle_cutoff(tz: str) -> str:
    """A todo may be tickled again once its last tickle is OLDER than this instant.

    The rest is counted in the list's calendar days, like every other "today"
    decision: tickled on local day D, a todo rests through D + TICKLE_REST_DAYS - 1,
    so the cutoff is local midnight at the start of today - (TICKLE_REST_DAYS - 1).
    """
    zone = validate_tz(tz)
    first_rest_day = business_today(zone) - datetime.timedelta(days=TICKLE_REST_DAYS - 1)
    return to_iso(datetime.datetime.combine(first_rest_day, datetime.time.min, ZoneInfo(zone)))


def validate_status(status: str) -> str:
    if status not in TODO_STATUSES:
        raise ValidationError(f"Invalid status '{status}'. Valid: {', '.join(TODO_STATUSES)}")
    return status


def validate_project_status(status: str) -> str:
    if status not in PROJECT_STATUSES:
        raise ValidationError(f"Invalid project status '{status}'. Valid: {', '.join(PROJECT_STATUSES)}")
    return status


def validate_area_status(status: str) -> str:
    if status not in AREA_STATUSES:
        raise ValidationError(f"Invalid area status '{status}'. Valid: {', '.join(AREA_STATUSES)}")
    return status


def validate_due(due_date, field: str = "due_date") -> str | None:
    """A date-only field (`due_date`, `revisit_on`): YYYY-MM-DD or None."""
    if due_date in (None, ""):
        return None
    due = str(due_date).strip()
    if not _DATE_RE.match(due):
        raise ValidationError(f"{field} must be YYYY-MM-DD, got '{due_date}'")
    try:
        # Shape alone lets '2026-13-40' through; due dates are compared as text,
        # so an impossible date must never be stored.
        datetime.date.fromisoformat(due)
    except ValueError:
        raise ValidationError(f"{field} is not a real calendar date: '{due_date}'")
    return due


def validate_repeat(repeat) -> str:
    r = str(repeat or "").strip().lower()
    if r == "none":
        r = ""
    if r in REPEAT_OPTIONS or _EVERY_RE.match(r):
        return r
    raise ValidationError(
        f"Invalid repeat '{repeat}'. Valid: daily, weekdays, weekly, monthly, yearly, "
        "every:N (N days), or empty for none"
    )


def validate_tags(tags, field: str = "tags", item: str = "tag") -> list[str]:
    """A list-of-short-strings field: `tags`, and `people` under the same caps."""
    if tags is None:
        return []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValidationError(f"{field} must be a list of strings")
    cleaned = [t.strip() for t in tags if t.strip()]
    if len(cleaned) > MAX_TAGS:
        raise ValidationError(f"too many {field} (max {MAX_TAGS})")
    if any(len(t) > MAX_SHORT_CHARS for t in cleaned):
        raise ValidationError(f"{item} too long (max {MAX_SHORT_CHARS} characters)")
    return cleaned


def validate_people(people) -> list[str]:
    return validate_tags(people, "people", "person")


def validate_notes(notes, field: str = "notes") -> str:
    """A long free-text field: notes, and a project's purpose and outcome."""
    text = str(notes or "")
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationError(f"{field} too long (max {MAX_TEXT_CHARS} characters)")
    return text


def validate_short(value, field: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_SHORT_CHARS:
        raise ValidationError(f"{field} too long (max {MAX_SHORT_CHARS} characters)")
    return text


def clean_source_client(value) -> str | None:
    """The AI tool's self-reported name: untrusted, so truncated rather than rejected."""
    text = str(value or "").strip()[:MAX_SOURCE_CLIENT_CHARS]
    return text or None


# How some tools name themselves, as a person would say it.
_FRIENDLY_CLIENTS = {"claude-code": "Claude Code", "claude-ai": "Claude", "claude-user": "Claude"}
# HTTP libraries, not AI tools: a name like this says nothing about who is calling.
_GENERIC_AGENTS = (
    "python",
    "node",
    "undici",
    "axios",
    "go-http",
    "okhttp",
    "curl",
    "mozilla",
    "java",
    "httpx",
    "aiohttp",
    "bun",
    "deno",
    "got",
    "fetch",
)
_PRODUCT = re.compile(r"\s*([A-Za-z][A-Za-z0-9 ._-]*?)\s*(?:/|\(|$)")


def client_name(declared, user_agent: str | None) -> str | None:
    """The calling AI tool's name, for provenance: the name it declares (MCP's
    clientInfo), else the product its User-Agent leads with — never an HTTP
    library's. Shared by the MCP tools and Agent Commands."""
    name = declared if isinstance(declared, str) and declared else None
    if not name:
        # Cap the input: the lazy class backtracks quadratically on a long run of
        # spaces, and a product name never needs more than this.
        match = _PRODUCT.match((user_agent or "")[:200])
        name = match.group(1) if match else None
        if name and name.lower().startswith(_GENERIC_AGENTS):
            name = None
    if not name:
        return None
    return clean_source_client(_FRIENDLY_CLIENTS.get(name.strip().lower(), name))


def caps_for(verified: bool, hosted: bool, plan: str | None = None) -> tuple[int, int, int]:
    """The list's (todos, projects, areas) caps: by hosting mode, then plan, then by a
    confirmed email."""
    if not hosted:
        return SELF_HOST_CAPS
    if plan in caps.TODO:
        return caps.TODO[plan]
    return VERIFIED_CAPS if verified else ANON_CAPS


def board_caps_for(verified: bool, hosted: bool, plan: str | None = None) -> tuple[int, int]:
    """The list's (boards, cards) caps, picked as caps_for picks its own."""
    if not hosted:
        return BOARD_SELF_HOST_CAPS
    if plan in caps.BOARD:
        return caps.BOARD[plan]
    return BOARD_VERIFIED_CAPS if verified else BOARD_ANON_CAPS


def site_caps_for(verified: bool, hosted: bool, plan: str | None = None) -> tuple[int, int]:
    """The list's (pages, links) caps, picked as caps_for picks its own, by plan."""
    if not hosted:
        return SITE_SELF_HOST_CAPS
    if plan in caps.SITE:
        return caps.SITE[plan]
    return SITE_VERIFIED_CAPS if verified else SITE_ANON_CAPS


def short_name_cap_for(hosted: bool, plan: str | None = None) -> int:
    return 100 if not hosted else caps.SHORT_NAMES.get(plan or "", 0)


def site_bytes_for(verified: bool, hosted: bool, plan: str | None = None) -> int:
    if not hosted:
        return 1_000_000_000
    if not verified:
        return 25_000_000
    return caps.SITE_BYTES.get(plan or "", 25_000_000)


def storage_quota_for(verified: bool, hosted: bool, plan: str | None = None) -> int:
    if hosted and not verified:
        return 25_000_000
    return file_quota_for(verified, hosted, plan)


def site_page_bytes_for(hosted: bool, plan: str | None = None) -> int:
    """The most content one page may hold, in UTF-8 bytes."""
    return SITE_BIG_PAGE_BYTES if not hosted else caps.PAGE_BYTES.get(plan or "", SITE_MAX_BYTES)


def site_data_caps_for(verified: bool, hosted: bool, plan: str | None = None) -> tuple[int, int]:
    """The account's data bytes (minimum 1 KB per record) and records per page."""
    if not hosted:
        return 2_000_000_000, 100_000
    if plan in caps.DATA:
        return caps.DATA[plan]
    return (10_000_000, 2_000) if verified else (0, 0)


def note_cap_for(verified: bool, hosted: bool, plan: str | None = None) -> int:
    """The list's notes cap, picked as caps_for picks its own."""
    if not hosted:
        return NOTE_SELF_HOST_CAP
    if plan in caps.NOTE:
        return caps.NOTE[plan]
    return NOTE_VERIFIED_CAP if verified else NOTE_ANON_CAP


def brain_caps_for(verified: bool, hosted: bool, plan: str | None = None) -> tuple[int | None, int, int]:
    """The list's Common Brain (AIs, memories, pages) caps, picked as site_caps_for picks its own."""
    if not hosted:
        return BRAIN_SELF_HOST_CAPS
    if plan in caps.BRAIN:
        return caps.BRAIN[plan]
    return BRAIN_VERIFIED_CAPS if verified else BRAIN_ANON_CAPS


def brains_cap_for(verified: bool, hosted: bool, plan: str | None = None) -> int:
    """Active brains per account; the highest plan and self-host are displayed as Unlimited."""
    return 100 if not hosted else caps.BRAINS.get(plan or "", 1)


def links_cap_for(verified: bool, hosted: bool, plan: str | None = None) -> int:
    """Live named staff links; program keys keep their separate cap of 20."""
    return 1000 if not hosted else caps.LINKS.get(plan or "", 3)


def file_quota_for(verified: bool, hosted: bool, plan: str | None = None) -> int:
    """The list's Common Brain file quota in bytes, picked as site_caps_for picks its own."""
    if not hosted:
        return FILE_SELF_HOST_QUOTA
    if plan in caps.FILES:
        return caps.FILES[plan]
    return FILE_VERIFIED_QUOTA if verified else 0


def recording_cap_for(verified: bool, hosted: bool, plan: str | None = None) -> int:
    """The list's Projects recordings cap, picked as caps_for picks its own."""
    if not hosted:
        return RECORDING_SELF_HOST_CAP
    if plan in caps.RECORDING:
        return caps.RECORDING[plan]
    return RECORDING_VERIFIED_CAP if verified else RECORDING_ANON_CAP


def validate_email(email) -> str | None:
    """Lowercased address, or None for empty (which clears it)."""
    text = str(email or "").strip().lower()
    if not text:
        return None
    if len(text) > MAX_EMAIL_CHARS or not _EMAIL_RE.match(text):
        raise ValidationError("That doesn't look like an email address")
    return text


def validate_list_name(name, *, required: bool | None = None) -> str:
    """The list's name: trimmed, inner whitespace collapsed, '' when not given."""
    text = " ".join(str(name or "").split())
    if len(text) > MAX_LIST_NAME_CHARS:
        raise ValidationError(f"List name too long (max {MAX_LIST_NAME_CHARS} characters)")
    if not text.isprintable():
        raise ValidationError("List name has characters that cannot be shown")
    if not text and (LIST_NAME_REQUIRED if required is None else required):
        raise ValidationError("Give your list a name")
    return text


def _advance(repeat: str, base: datetime.date) -> datetime.date:
    """One repeat interval after `base`, clamping month-end/Feb-29 overflow."""
    if repeat == "daily":
        return base + datetime.timedelta(days=1)
    if repeat == "weekdays":
        nxt = base + datetime.timedelta(days=1)
        while nxt.weekday() >= 5:  # 5=Sat, 6=Sun
            nxt += datetime.timedelta(days=1)
        return nxt
    if repeat == "weekly":
        return base + datetime.timedelta(days=7)
    if repeat == "monthly":
        y, m = (base.year, base.month + 1) if base.month < 12 else (base.year + 1, 1)
        return base.replace(year=y, month=m, day=min(base.day, calendar.monthrange(y, m)[1]))
    if repeat == "yearly":
        y = base.year + 1
        return base.replace(year=y, day=min(base.day, calendar.monthrange(y, base.month)[1]))
    m = _EVERY_RE.match(repeat)
    if m:
        return base + datetime.timedelta(days=int(m.group(1)))
    raise ValidationError(f"Invalid repeat '{repeat}'")


def next_due(repeat: str, due_date: str | None, today: datetime.date) -> str:
    """Due date for the next occurrence of a repeating todo.

    `today` is the caller's single `business_today(tz)` read: the spawn also
    compares the RESULT against today (auto-star), and two reads could
    straddle midnight and disagree.

    Advances from the old due date; re-anchors to today only when even the
    advanced date is already past, so completing late never spawns an
    already-overdue copy. (A due-today result is not overdue, hence the strict <.)

    # simplification: next-due derives from the previous occurrence with
    # month-end clamping, so a monthly Jan-31 repeat drifts to the 28th after
    # February; storing an anchor day is the upgrade path if that matters.
    """
    if isinstance(due_date, datetime.date):
        base = due_date
    else:
        try:
            base = datetime.date.fromisoformat(due_date) if due_date else today
        except ValueError:
            base = today
    try:
        nxt = _advance(repeat, base)
        if nxt < today:
            nxt = _advance(repeat, today)
    except ValidationError:
        raise
    except (OverflowError, ValueError):  # past date.max: timedelta overflows, replace() rejects year 10000
        raise ValidationError("The next due date is out of range. Clear the repeat first.")
    return nxt.isoformat()
