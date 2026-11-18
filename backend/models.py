"""todo-gtd — Pydantic request models.

Field caps mirror the service-layer limits (MAX_TEXT_CHARS) so an oversized
valid body is rejected at the model boundary. All-optional *Update models so
the router's model_dump(exclude_unset=True) means an omitted field is
untouched and an explicit null/empty clears it.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from backend.common import MAX_EMAIL_CHARS, MAX_SHORT_CHARS, MAX_TAGS, MAX_TEXT_CHARS, SITE_BIG_PAGE_BYTES


class TodoCreate(BaseModel):
    title: str = Field(max_length=MAX_TEXT_CHARS)
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)
    project: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    project_id: int | None = None
    area_id: int | None = None
    context: str = Field(default="", max_length=MAX_SHORT_CHARS)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    people: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    status: str = Field(default="inbox", max_length=MAX_SHORT_CHARS)
    star: bool = False
    due_date: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    revisit_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    repeat: str = Field(default="", max_length=MAX_SHORT_CHARS)
    auto_star_on_due: bool = False


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    notes: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    project: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    project_id: int | None = None
    area_id: int | None = None
    context: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    people: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    star: bool | None = None
    due_date: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    revisit_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    repeat: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    auto_star_on_due: bool | None = None


class TodoBulkUpdate(BaseModel):
    ids: list[int] = Field(max_length=500)
    fields: dict


class ContextRename(BaseModel):
    old: str = Field(max_length=MAX_SHORT_CHARS)
    new: str = Field(max_length=MAX_SHORT_CHARS)
    merge: bool = False


class ProjectCreate(BaseModel):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)
    status: str = Field(default="active", max_length=MAX_SHORT_CHARS)
    purpose: str = Field(default="", max_length=MAX_TEXT_CHARS)
    outcome: str = Field(default="", max_length=MAX_TEXT_CHARS)
    area_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    notes: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    purpose: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    outcome: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    area_id: int | None = None


class AreaCreate(BaseModel):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)


class AreaUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    notes: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


class ConnectPoll(BaseModel):
    device_token: str = Field(max_length=128)

    @field_validator("device_token", mode="before")
    @classmethod
    def opaque_token(cls, value):
        # Minted tokens are ASCII. Even malformed Unicode is an unknown token;
        # do not echo it into Pydantic's validation error response.
        return "" if isinstance(value, str) and (not value.isascii() or len(value) > 128) else value


class ConnectApproval(BaseModel):
    typed_code: str | None = Field(default=None, max_length=32)


class ListCreate(BaseModel):
    connect: str | None = Field(default=None, max_length=9)
    tz: str | None = Field(default=None, max_length=64)  # the browser's IANA zone
    # Optional; the real cap and its message are common.validate_list_name's.
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


class NameUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)  # null/'' clears


class TzUpdate(BaseModel):
    tz: str = Field(max_length=64)  # an IANA zone name


class EmailUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=MAX_EMAIL_CHARS)  # null/'' clears


class AppSwitch(BaseModel):
    on: bool


class SignInRequest(BaseModel):
    email: str = Field(max_length=MAX_EMAIL_CHARS)


class ResetRequest(BaseModel):
    code: str = Field(max_length=MAX_SHORT_CHARS)


# ── Projects GTD (boards.py) ──────────────────────────────────────────────────


class BoardCreate(BaseModel):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)
    columns: list[str] | None = Field(default=None, max_length=50)
    tools: list[str] | None = Field(default=None, max_length=20)  # None: the card table alone


class BoardUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    notes: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    pinned: bool | None = None
    starts_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    ends_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    template: bool | None = None
    folder: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


class TemplateUse(BaseModel):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    starts_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


class ColumnCreate(BaseModel):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    position: int | str | None = None


class ColumnUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    position: int | str | None = None
    color: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    has_on_hold: bool | None = None
    card_limit: int | None = None
    description: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)


class ColumnCards(BaseModel):
    to_column_id: int


class ColumnSort(BaseModel):
    by: str = Field(max_length=MAX_SHORT_CHARS)


class LabelCreate(BaseModel):
    name: str = Field(default="", max_length=MAX_SHORT_CHARS)
    color: str = Field(default="", max_length=MAX_SHORT_CHARS)


class LabelUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    color: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


class CardCreate(BaseModel):
    title: str = Field(max_length=MAX_SHORT_CHARS)
    column_id: int | None = None
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)
    due_date: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    position: int | str | None = None
    starts_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    assignee_ids: list[int | str] | None = Field(default=None, max_length=MAX_TAGS)
    labels: list[int | str] | None = Field(default=None, max_length=MAX_TAGS)
    cover: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    repeat: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    template: bool | None = None


class CardUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    notes: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    due_date: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    starts_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    assignee_ids: list[int | str] | None = Field(default=None, max_length=MAX_TAGS)
    labels: list[int | str] | None = Field(default=None, max_length=MAX_TAGS)
    cover: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    on_hold: bool | None = None
    completed: bool | None = None
    repeat: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    template: bool | None = None
    version: int | None = None  # the card's version as last read; an older one is a 409


class CardMove(BaseModel):
    column_id: int | None = None  # None with project_id: that project's Triage
    project_id: int | None = None  # another project
    position: int | str | None = None
    on_hold: bool | None = None


class RuleCreate(BaseModel):
    kind: str = Field(max_length=MAX_SHORT_CHARS)  # rule, card_button or board_button
    name: str = Field(default="", max_length=MAX_SHORT_CHARS)
    trigger: dict = Field(default_factory=dict)
    actions: list[dict] = Field(max_length=20)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    trigger: dict | None = None
    actions: list[dict] | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


class RulePress(BaseModel):
    card_id: int | None = None  # a card button's card


class CardCopy(BaseModel):
    column_id: int | None = None
    project_id: int | None = None
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


class ItemCopy(BaseModel):
    project_id: int | None = None  # the top of its tool in that project
    parent_id: int | None = None  # or under this list, group or folder


# ── Projects GTD as Basecamp (recordings.py, people.py) ───────────────────────
# Lengths are outer bounds; recordings.py checks each type's own fields.


class ItemFields(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    body: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    category: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    color: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    due_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    starts_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    assignee_ids: list[int | str] | None = Field(default=None, max_length=MAX_TAGS)
    pinned: bool | None = None
    # Docs & Files, Calendar, Check-ins (recordings._clean_extras checks each).
    url: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    ends_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    starts_at: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    ends_at: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    all_day: bool | None = None
    highlighted: bool | None = None
    repeat: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    repeat_until: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    frequency: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    days: list[int] | None = Field(default=None, max_length=7)
    time: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    paused: bool | None = None
    group_on: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    needle: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    spotlight: bool | None = None
    post_at: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    column_id: int | None = None  # a wormhole's column, in another project


class ItemCreate(ItemFields):
    type: str = Field(max_length=MAX_SHORT_CHARS)
    parent_id: int | None = None
    card_id: int | None = None
    position: int | str | None = None


class ItemUpdate(ItemFields):
    version: int | None = None  # the item's version as last read; an older one is a 409


class HillSet(BaseModel):
    positions: dict[str, float | None] = Field(max_length=50)  # to-do list id: 0 to 100, or null to untrack
    note: str = Field(default="", max_length=MAX_TEXT_CHARS)


class DateShift(BaseModel):
    days: int  # earlier when negative


class TodoImport(BaseModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)  # Markdown: headings, lines, indented lines, [x]
    parent_id: int | None = None  # a to-do list or group to import into


class ItemMove(BaseModel):
    parent_id: int | None = None
    project_id: int | None = None
    position: int | str | None = None
    before_id: int | None = None  # just above this sibling


class Completion(BaseModel):
    done: bool = True


class CommentCreate(BaseModel):
    body: str = Field(max_length=MAX_TEXT_CHARS)


class BoostCreate(BaseModel):
    content: str = Field(max_length=MAX_SHORT_CHARS)


class BookmarkSet(BaseModel):
    item_id: int | None = None
    card_id: int | None = None
    project_id: int | None = None
    on: bool = True


class InboxItem(BaseModel):
    item_id: int | None = None
    card_id: int | None = None
    project_id: int | None = None
    read: bool = True


class SampleAction(BaseModel):
    action: Literal["seed", "off", "on"]


class InboxMute(BaseModel):
    item_id: int | None = None
    card_id: int | None = None
    project_id: int | None = None
    muted: bool = True


class BubbleUp(BaseModel):
    item_id: int | None = None
    card_id: int | None = None
    project_id: int | None = None
    when: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)  # inbox.BUBBLE_TIMES, a date, or none


class UpNext(BaseModel):
    items: list[list[str | int]] = Field(max_length=100)


class DockSet(BaseModel):
    dock: list[dict] = Field(max_length=50)


class PersonCreate(BaseModel):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    title: str = Field(default="", max_length=MAX_SHORT_CHARS)


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    color: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)


# ── Simple Sites (sites.py) ───────────────────────────────────────────────────
# Lengths here are outer bounds; sites.py checks the real rules (the plan's page size in UTF-8).


class SiteCreate(BaseModel):
    content: str = Field(max_length=SITE_BIG_PAGE_BYTES)
    format: str = "markdown"
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    name: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=500)
    folder: str | None = Field(default=None, max_length=60)


class SiteLinkCreate(BaseModel):
    short_name: str | None = Field(default=None, max_length=30)
    url: str = Field(max_length=2_000)
    name: str | None = Field(default=None, max_length=10)
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    note: str | None = Field(default=None, max_length=500)
    folder: str | None = Field(default=None, max_length=60)


class SiteUpdate(BaseModel):
    data: str | None = None
    content: str | None = Field(default=None, max_length=SITE_BIG_PAGE_BYTES)
    format: str | None = None
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    status: str | None = None
    password: str | None = Field(default=None, max_length=200)  # '' unlocks (sites.update)
    note: str | None = Field(default=None, max_length=500)
    folder: str | None = Field(default=None, max_length=60)


# ── Notes GTD (notes.py) ──────────────────────────────────────────────────────


class NoteCreate(BaseModel):
    title: str = Field(default="", max_length=MAX_SHORT_CHARS)
    body: str = Field(default="", max_length=MAX_TEXT_CHARS)
    color: str = Field(default="", max_length=MAX_SHORT_CHARS)
    pinned: bool = False


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    body: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    color: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    pinned: bool | None = None
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    version: int | None = None  # required with title or body; an older one is a 409


# Common Brain (brain.py). The service checks the real limits (a memory is one short fact).
class BrainMemoryCreate(BaseModel):
    text: str = Field(max_length=MAX_SHORT_CHARS * 2)


class BrainMemoryUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=MAX_SHORT_CHARS * 2)
    locked: bool | None = None
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    version: int | None = None  # with it, a memory changed since is a 409


class BrainPageCreate(BaseModel):
    path: str = Field(max_length=MAX_SHORT_CHARS)
    title: str = Field(default="", max_length=MAX_SHORT_CHARS)
    body: str = Field(default="", max_length=200_000)
    format: str = Field(default="markdown", max_length=20)


class BrainPageUpdate(BaseModel):
    path: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    title: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    body: str | None = Field(default=None, max_length=200_000)
    format: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=MAX_SHORT_CHARS)
    version: int | None = None  # with it, a page changed since is a 409


class BrainResolve(BaseModel):
    """A page's [[link]] targets, resolved in one batch (brain.resolve)."""

    targets: list[Annotated[str, Field(max_length=MAX_SHORT_CHARS)]] = Field(max_length=500)


class BrainFileUpdate(BaseModel):
    status: Literal["active", "archived"]


class BrainRestore(BaseModel):
    kind: Literal["memory", "page"]
    id: int
    version: int


class KeyCreate(BaseModel):
    """A program key (keys.py): its checks are keys.create's."""

    name: str = Field(max_length=MAX_SHORT_CHARS)
    apps: Literal["brain", "all"] = "brain"
    access: Literal["read", "write"] = "read"
    folders: list[str] = Field(default_factory=list, max_length=50)
    brains: list[int] | None = Field(default=None, max_length=100)
    kind: Literal["key", "link"] = "key"


class BrainSettings(BaseModel):
    name: str = Field(default="", max_length=MAX_SHORT_CHARS)
    description: str = ""
    rules: list[str] = Field(default_factory=list, max_length=50)
    ai_access: Literal["read", "write", "inbox"] = "write"


class BrainGrant(BaseModel):
    brains: list[int] = Field(max_length=100)


class BrainMove(BaseModel):
    kind: Literal["memory", "page"]
    id: int
    to_brain: int
    path: str | None = None
    expected_version: int | None = None
