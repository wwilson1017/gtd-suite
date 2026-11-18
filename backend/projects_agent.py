"""Projects GTD as Basecamp on the agent link: the MCP tools and Agent Commands
for everything in a project but its card table (recordings.py), each a thin
call. The card table's own tools and commands (board_*, card_*, BOARD, …) are
in mcp_server.py and agent_cmd.py; this module adds to them and to the
Projects part of the guide. main.py imports it.

No delete tool or command: archive and trash are statuses, and both come back.
The list comes from the token, never an argument; the writer is the AI tool
(people.actor_in), so its work shows under its own name. A stale version is a
plain refusal on this side (a tool error, a 400), as in notes_agent.
"""

# _arg(...) in tool signatures is a call inside an annotation, which pyright cannot read.
# pyright: reportInvalidTypeForm=false

from backend import agent_cmd, boards, db, mcp_server, people, recordings, reports, schedules
from backend.agent_cmd import Arg, Command
from backend.common import ConflictError, ValidationError
from backend.mcp_server import _arg, _client_name, _given, _list_id, _tool

mcp_server.INSTRUCTIONS["projects"] = (
    "Projects GTD is the user's projects: each one a kanban board of cards, with tools beside it: "
    "Messages (announcements and discussions, each with comments), Docs (folders, "
    "Markdown documents, links), a Calendar (events; calendar_list reads it with what is due), "
    "Chat (quick talk: chat_read, chat_post), Links (type 'door': a url), "
    "todos_import (a plan of to-dos written as Markdown, in one call), "
    "Check-ins (questions asked on a schedule: activity_list says which you are asked "
    "today; answer with item_create type 'answer'), To-dos (to-do lists, "
    "groups inside a list, to-dos with assignees and dates, subtasks; loose to-dos sit outside "
    "any list), and the board itself (the board_ and card_ tools): new cards land in Triage, "
    "undecided work waits in Not now, work moves left to right through the work columns, and "
    "a card in Done is complete; a blocked card goes On Hold in its column. Cards carry "
    "assignees, labels, start and due dates and subtasks (item_create with type 'step' and "
    "card_id). project_open "
    "shows a project's tools with what is in each; item_list, item_get, item_create and "
    "item_update work the messages, to-do lists, to-dos and subtasks; todo_complete checks "
    "one off; comment_add comments on any item or card. You work as a member of the team: "
    "what you write is shown under your name, and people (the user is 'me') can assign to-dos "
    "to you. Discuss on the item's comments, log progress there, and complete what you finish. "
    "Write @ and a person's name (project_open's everyone lists them) to mention them; "
    "activity_list's assigned_to_you.mentions lists where someone mentioned you lately, to answer there. "
    "report_get reads Reports across projects (overdue, upcoming, unassigned, added and completed, "
    "Mission Control's Needles, the Hill Charts, everything of a kind) and project_search finds text "
    "anywhere; the Needle and the Hill Chart are the user's judgment, so you read them and never set "
    "them. Start a project or post a message only when the user asks. Nothing can be deleted: "
    "item_archive archives an item and restores it; the trash is the user's alone."
)
# The sample projects (samples.py), said on both the MCP server and the guide.
_SAMPLES = (
    "A project with sample: true is an example the app made to show how it works; leave it alone unless the user asks."
)
mcp_server.INSTRUCTIONS["projects"] += " " + _SAMPLES

_TYPES = (
    "'message', 'todolist', 'todolist_group' (a group inside a to-do list), 'todo', "
    "'step' (a subtask of a to-do or a card), 'vault' (a folder in Docs), 'document', "
    "'link' (a file elsewhere: needs fields.url), 'schedule_entry' (a calendar event: needs "
    "starts_on), 'question' (an automatic check-in) or 'answer' (to a check-in question)"
)
_MORE = (
    "The type's own fields, as an object: todo {repeat: as schedule_entry's; finishing it adds "
    "the next}; message {post_at: an ISO date-time a draft posts itself at}; link {url}; "
    "schedule_entry {ends_on, starts_at and "
    "ends_at as HH:MM, all_day, url (a join link), highlighted, repeat (every_day, "
    "every_weekday, every_week, every_other_week, every_month, every_year), repeat_until}; "
    "question {frequency (every_day, every_week, every_other_week, every_month), days "
    "(weekdays, 0 = Sunday), time (HH:MM), paused}; answer {group_on: the day it answers, "
    "default today}"
)
_PROJECT = "The project: its id, or its name (case-insensitive)"
_ID = "The item's id"
_PEOPLE = (
    "People by name or id: 'me' is the user; an AI tool is its name (yours too). Replaces the whole list; [] clears it"
)
_DATE = "YYYY-MM-DD; empty string clears it"


def _update(list_id: int, item_id: int, fields: dict, version, client) -> dict:
    try:
        return recordings.update(list_id, item_id, fields, version, source="agent", client=client)
    except ConflictError as e:
        raise ValidationError(str(e)) from None


def _overview(list_id: int, project) -> dict:
    """project_open's answer: the project, its tools with their contents in brief,
    its people and its latest activity."""
    page = recordings.project(list_id, project)
    page["activity"] = recordings.activity(list_id, board_id=page["id"], limit=10)["events"]
    page["everyone"] = [{"id": p["id"], "name": p["name"], "kind": p["kind"]} for p in people.list_people(list_id)]
    return page


# ── MCP tools ─────────────────────────────────────────────────────────────────


@_tool("Open a project", read_only=True, app="projects")
def project_open(project: _arg(str, _PROJECT)) -> dict:
    """A project's page: its tools in order (Message Board, To-dos, Card Table)
    with a preview of each (the latest messages, the to-do lists with how many
    are done, the card table's columns), its latest activity, and everyone
    who can be assigned. A project that is the home of a Todo GTD project names
    it in todo_project: its next actions are that project's to-dos, in Todo GTD.
    Start here."""
    return {"project": _overview(_list_id.get(), project)}


@_tool("List items", read_only=True, app="projects")
def item_list(
    project: _arg(str, _PROJECT),
    type: _arg(str, f"What to list: {_TYPES}. 'todo' lists the loose to-dos"),
    parent_id: _arg(
        int | None, "Only the items under this one: a list's to-dos and groups, a group's to-dos, a to-do's subtasks"
    ) = None,
    status: _arg(str, "'active' (the default), 'archived', 'trashed' or 'drafted' (unposted messages)") = "active",
    sort: _arg(
        str,
        "Messages: 'newest' (the default), 'activity' (latest comment) or "
        "'alpha'. Pinned messages come first either way",
    ) = "newest",
) -> dict:
    """A project's messages, to-do lists (each with how many to-dos are done),
    loose to-dos, or the items under one parent. item_get reads one whole."""
    return {
        "items": recordings.list_items(
            _list_id.get(), project, type, status, parent_id, sort, source="agent", client=_client_name()
        )
    }


@_tool("Read an item", read_only=True, app="projects")
def item_get(id: _arg(int, _ID)) -> dict:
    """One message, to-do list, group, to-do or subtask: all its fields, the
    breadcrumb above it, its comments, and what is under it (a list's open
    to-dos and groups plus its completed ones, a to-do's subtasks)."""
    return recordings.thread(_list_id.get(), id, source="agent", client=_client_name())


@_tool("Add an item", read_only=False, app="projects")
def item_create(
    project: _arg(str, _PROJECT),
    type: _arg(str, _TYPES),
    title: _arg(str, "The message's subject, the list's or the to-do's name") = "",
    body: _arg(str, "Markdown: the message itself, or a list's or to-do's notes") = "",
    parent_id: _arg(
        int | None,
        "Where it goes: a to-do's list or group, a group's list, a "
        "subtask's to-do. Leave out for a message, a to-do list or a "
        "loose to-do",
    ) = None,
    card_id: _arg(int | None, "A card to put a subtask on, instead of a to-do") = None,
    assignees: _arg(list[str] | None, _PEOPLE) = None,
    due_on: _arg(str | None, "To-dos and subtasks: due " + _DATE) = None,
    starts_on: _arg(str | None, "To-dos: starts " + _DATE) = None,
    category: _arg(
        str | None,
        "Messages: an emoji and a name, e.g. '📢 Announcement', '✨ FYI', '❤️ Heartbeat', '💡 Pitch', '❓ Question'",
    ) = None,
    color: _arg(str | None, f"To-do lists, groups, folders: one of {', '.join(recordings.COLORS)}") = None,
    draft: _arg(bool, "Messages: save it unposted, for the user to post") = False,
    fields: _arg(dict | None, _MORE) = None,
) -> dict:
    """Post a message; start a to-do list or a group; add a to-do or a subtask;
    make a folder, a document or a link in Docs & Files; put an event on the
    calendar; ask a check-in question, or answer one."""
    more = dict(fields or {})
    fields = {
        **more,
        **_given(
            title=title or None, body=body or None, due_on=due_on, starts_on=starts_on, category=category, color=color
        ),
    }
    if assignees is not None:
        fields["assignee_ids"] = assignees
    if draft:
        fields["status"] = "drafted"
    return {
        "item": recordings.create(
            _list_id.get(),
            project,
            type,
            fields,
            parent_id=parent_id,
            card_id=card_id,
            source="agent",
            client=_client_name(),
        )
    }


@_tool("Update an item", read_only=False, app="projects")
def item_update(
    id: _arg(int, _ID),
    expected_version: _arg(
        int | None,
        "The version item_get returned; when the item changed since, nothing is saved. Send it when rewriting a body",
    ) = None,
    title: _arg(str | None, "A new title") = None,
    body: _arg(str | None, "A whole new body, in markdown") = None,
    assignees: _arg(list[str] | None, _PEOPLE) = None,
    due_on: _arg(str | None, _DATE) = None,
    starts_on: _arg(str | None, _DATE) = None,
    category: _arg(str | None, "A message's category") = None,
    color: _arg(str | None, "A list's or group's colour") = None,
    pinned: _arg(bool | None, "Pin a message to the top of its board, or unpin it") = None,
    post: _arg(bool, "Post a drafted message") = False,
    fields: _arg(dict | None, _MORE) = None,
) -> dict:
    """Change an item's fields; those left out stay. To discuss or log progress,
    comment_add instead of rewriting the body."""
    fields = {
        **(fields or {}),
        **_given(
            title=title, body=body, due_on=due_on, starts_on=starts_on, category=category, color=color, pinned=pinned
        ),
    }
    if assignees is not None:
        fields["assignee_ids"] = assignees
    if post:
        fields["status"] = "active"
    return {"item": _update(_list_id.get(), id, fields, expected_version, _client_name())}


@_tool("Move or copy an item", read_only=False, app="projects")
def item_move(
    id: _arg(int, _ID),
    project: _arg(str | None, "To the top of its tool in this project; " + _PROJECT) = None,
    parent_id: _arg(
        int | None, "Or under this item: a to-do list or group for a to-do, a folder for a document, link or folder"
    ) = None,
    copy: _arg(bool, "Copy it there instead (with what is under it; never its comments)") = False,
) -> dict:
    """Move an item, or (copy) copy it: a to-do to another list or group, a
    document, link or folder into a folder, or a top-level item (message, to-do
    list, document, event, check-in question) to another project. A move keeps
    its comments and history; a copy starts fresh."""
    list_id, client = _list_id.get(), _client_name()
    if copy:
        return {
            "item": recordings.copy(
                list_id, id, board=project or None, parent_id=parent_id, source="agent", client=client
            )
        }
    if project in (None, "") and parent_id is None:
        raise ValidationError("Say where: project or parent_id")
    return {
        "item": recordings.move(list_id, id, parent_id=parent_id, board=project or None, source="agent", client=client)
    }


@_tool("Archive or restore an item", read_only=False, app="projects")
def item_archive(
    id: _arg(int, _ID),
    restore: _arg(bool, "true brings an archived or trashed item back") = False,
) -> dict:
    """Archive an item, or bring it back. Nothing is ever deleted, and the trash
    is the person's to use, not yours."""
    return {"item": _update(_list_id.get(), id, {"status": "active" if restore else "archived"}, None, _client_name())}


@_tool("Complete a to-do", read_only=False, app="projects")
def todo_complete(
    id: _arg(int, "The to-do's or subtask's id"),
    done: _arg(bool, "false re-opens it") = True,
) -> dict:
    """Check off a to-do or a subtask, or re-open it."""
    return {"item": recordings.complete(_list_id.get(), id, done, source="agent", client=_client_name())}


@_tool("Comment", read_only=False, app="projects")
def comment_add(
    text: _arg(str, "The comment, in markdown"),
    id: _arg(int | None, "The item to comment on") = None,
    card_id: _arg(int | None, "Or a card to comment on") = None,
) -> dict:
    """Comment on a message, to-do list, to-do or card: an answer, a question,
    progress, a decision. It shows under your name."""
    return {
        "comment": recordings.comment(
            _list_id.get(), text, rec_id=id, card_id=card_id, source="agent", client=_client_name()
        )
    }


@_tool("Read the activity", read_only=True, app="projects")
def activity_list(
    project: _arg(str | None, "Only this project; " + _PROJECT) = None,
    before: _arg(int | None, "The last page's next_before") = None,
    since: _arg(int | None, "Only what happened after this: the latest your last call returned") = None,
) -> dict:
    """What happened lately, newest first: who did what to which item, in which
    project, 50 a page; `latest` is the cursor for next time (since). Also what is
    assigned to you: open to-dos and cards whose assignees include you."""
    list_id = _list_id.get()
    board_id = boards.get_board(list_id, project)["id"] if project not in (None, "") else None
    out = recordings.activity(list_id, board_id=board_id, before=before, since=since)
    out["assigned_to_you"] = _assigned(list_id, _client_name())
    return out


@_tool("Read the calendar", read_only=True, app="projects")
def calendar_list(
    start: _arg(str, "The first day, YYYY-MM-DD"),
    end: _arg(str, "The last day, YYYY-MM-DD (at most 400 days on)"),
    project: _arg(str | None, "Only this project; " + _PROJECT) = None,
    include_due: _arg(bool, "Also the open to-dos, subtasks and cards due in the range") = True,
) -> dict:
    """What is on the calendar from start to end: every event occurrence (a
    repeating event once per day it happens, with `on`), and what is due."""
    return schedules.calendar(_list_id.get(), start, end, board_ref=project or None, include_due=include_due)


_REPORTS = (
    "'overdue' (open work past due, grouped by how late), 'upcoming' (due in the next "
    "days, default 14), 'unassigned' (open to-dos and cards nobody has), 'progress' (to-dos and "
    "cards added and completed from start to end), 'mission_control' (every project's Needle: "
    "on_track, some_risk or concerned, and which have gone quiet), 'hilltop' (every project's "
    "Hill Chart: where each tracked to-do list sits, 0 to 100, and whether it is stale), "
    "'everything' (one kind, newest first: messages, docs, tasks, comments or checkins)"
)


def _report(list_id: int, name: str, *, days=None, start=None, end=None, kind=None, before=None) -> dict:
    if name == "overdue":
        return reports.overdue(list_id)
    if name == "upcoming":
        return reports.upcoming(list_id, days or 14)
    if name == "unassigned":
        return reports.unassigned(list_id)
    if name == "progress":
        if not (start and end):
            raise ValidationError("progress needs start and end (YYYY-MM-DD)")
        return reports.progress(list_id, start, end)
    if name == "mission_control":
        return reports.mission_control(list_id)
    if name == "hilltop":
        return reports.hilltop(list_id)
    if name == "everything":
        return reports.everything(list_id, kind or "messages", before=before)
    raise ValidationError(
        "report must be overdue, upcoming, unassigned, progress, mission_control, hilltop or everything"
    )


@_tool("Read a report", read_only=True, app="projects")
def report_get(
    report: _arg(str, "Which: " + _REPORTS),
    days: _arg(int | None, "upcoming: how many days ahead (1 to 90)") = None,
    start: _arg(str | None, "progress: the first day, YYYY-MM-DD") = None,
    end: _arg(str | None, "progress: the last day, YYYY-MM-DD") = None,
    kind: _arg(str | None, "everything: messages, docs, tasks, comments or checkins") = None,
    before: _arg(str | None, "everything: the last page's next_before") = None,
) -> dict:
    """Reports across every project: what is overdue or coming up,
    what nobody has, what was added and finished, how each project is going
    (the status Needle, the Hill Chart), or everything of one kind. The Needle and the
    Hill Chart are the user's to set; you read them."""
    return _report(_list_id.get(), report, days=days, start=start, end=end, kind=kind, before=before)


@_tool("Search", read_only=True, app="projects")
def project_search(
    q: _arg(str, "The words to find: every word must appear in the title or the text"),
    kind: _arg(str | None, "Only this kind: " + ", ".join(reports.SEARCH_KINDS)) = None,
    project: _arg(str | None, "Only this project; " + _PROJECT) = None,
    since: _arg(str | None, "Only what was made on or after this day, YYYY-MM-DD") = None,
    sort: _arg(str, "'best' (title matches first, the default) or 'recent'") = "best",
) -> dict:
    """Find messages, documents, to-dos, comments, events, check-ins and cards
    in every project, archived ones too (not the trash). Each result names its
    project and type and quotes the text around the match; item_get reads one."""
    list_id = _list_id.get()
    board_id = boards.get_board(list_id, project)["id"] if project not in (None, "") else None
    return reports.search(list_id, q, kind=kind, board_id=board_id, since=since, sort=sort)


@_tool("Read a project's chat", read_only=True, app="projects")
def chat_read(
    project: _arg(str, _PROJECT),
    since: _arg(int | None, "Only what was said after this: the latest your last read returned") = None,
) -> dict:
    """A project's chat, oldest first: the latest lines, or
    those since your last read. `latest` is the cursor for next time."""
    return recordings.chat(_list_id.get(), project, since=since)


@_tool("Say something in a project's chat", read_only=False, app="projects")
def chat_post(
    project: _arg(str, _PROJECT),
    text: _arg(str, "What to say; markdown works. Keep it short: chat is for quick talk"),
) -> dict:
    """Post a line in a project's chat, under your name. Longer things belong on
    the Message Board (item_create type 'message')."""
    return {
        "line": recordings.create(
            _list_id.get(), project, "chat_line", {"body": text}, source="agent", client=_client_name()
        )
    }


@_tool("Import to-dos from Markdown", read_only=False, app="projects")
def todos_import(
    project: _arg(str, _PROJECT),
    markdown: _arg(
        str,
        "A heading starts a to-do list, each other line is a to-do, an indented line "
        "(two spaces) is a subtask of the to-do above it, and '- [x]' adds one done. "
        "Bullets and numbers are dropped. At most 500 lines",
    ),
    parent_id: _arg(
        int | None,
        "Import into this to-do list (headings become groups) or group; "
        "by default headings make new lists, and lines before any are loose to-dos",
    ) = None,
) -> dict:
    """Add a whole plan of to-dos at once, written as Markdown, under your name. Says
    how many lists, groups, to-dos and subtasks it added."""
    return recordings.import_todos(
        _list_id.get(), project, markdown, parent_id=parent_id, source="agent", client=_client_name()
    )


def _assigned(list_id: int, client) -> dict:
    """Open to-dos and cards assigned to the calling AI tool."""
    me = people.viewer(db.get_db(), list_id, client, "agent")
    if me is None:
        return {"todos": [], "cards": [], "check_ins": [], "mentions": []}
    return {
        "todos": [
            {k: t[k] for k in ("id", "title", "board_name", "due_on")} for t in recordings.assignments(list_id, me)
        ],
        "cards": [
            {k: c[k] for k in ("id", "title", "board_name", "column_name", "due_date")}
            for c in boards.assigned_cards(list_id, me)
        ],
        # Check-in questions you are asked today and have not answered: answer with
        # item_create type 'answer', parent_id the question.
        "check_ins": schedules.checkins_due(list_id, me),
        # Where someone @mentioned you lately (two weeks, newest first): answer on that item.
        "mentions": recordings.mentions_of(list_id, me),
    }


# ── Agent Commands ────────────────────────────────────────────────────────────

_ITEM_FIELDS = (
    "title",
    "body",
    "assignees",
    "due_on",
    "starts_on",
    "category",
    "color",
    "pinned",
    "url",
    "ends_on",
    "starts_at",
    "ends_at",
    "all_day",
    "highlighted",
    "repeat",
    "repeat_until",
    "frequency",
    "days",
    "time",
    "paused",
    "group_on",
    "post_at",
)


def _fields(body: dict) -> dict:
    fields = {k: body[k] for k in _ITEM_FIELDS if k in body}
    if "assignees" in fields:
        fields["assignee_ids"] = fields.pop("assignees")
    return fields


def _cmd_project(ctx, args, body):
    return {"project": _overview(ctx.list_id, args["project"])}


def _cmd_items(ctx, args, body):
    return {
        "items": recordings.list_items(
            ctx.list_id,
            args["project"],
            args["type"],
            args.get("status", "active"),
            args.get("parent_id"),
            args.get("sort", "newest"),
            source="agent",
            client=ctx.client,
        )
    }


def _cmd_item(ctx, args, body):
    return recordings.thread(ctx.list_id, args["id"], source="agent", client=ctx.client)


def _cmd_add(ctx, args, body):
    agent_cmd._known(body, ("type", "parent_id", "card_id", "draft", *_ITEM_FIELDS))
    fields = _fields(body)
    if body.get("draft"):
        fields["status"] = "drafted"
    return {
        "item": recordings.create(
            ctx.list_id,
            args["project"],
            body.get("type"),
            fields,
            parent_id=body.get("parent_id"),
            card_id=body.get("card_id"),
            source="agent",
            client=ctx.client,
        )
    }


def _cmd_update(ctx, args, body):
    agent_cmd._known(body, ("version", "post", *_ITEM_FIELDS))
    fields = _fields(body)
    if body.get("post"):
        fields["status"] = "active"
    return {"item": _update(ctx.list_id, args["id"], fields, body.get("version"), ctx.client)}


def _cmd_status(status: str):
    def run(ctx, args, body):
        return {"item": _update(ctx.list_id, args["id"], {"status": status}, None, ctx.client)}

    return run


def _cmd_complete(done: bool):
    def run(ctx, args, body):
        return {"item": recordings.complete(ctx.list_id, args["id"], done, source="agent", client=ctx.client)}

    return run


def _cmd_comment(ctx, args, body):
    agent_cmd._known(body, ("text",))
    return {
        "comment": recordings.comment(
            ctx.list_id,
            body.get("text"),
            rec_id=args.get("id"),
            card_id=args.get("card_id"),
            source="agent",
            client=ctx.client,
        )
    }


def _cmd_activity(ctx, args, body):
    project = args.get("project")
    board_id = boards.get_board(ctx.list_id, project)["id"] if project else None
    out = recordings.activity(ctx.list_id, board_id=board_id, before=args.get("before"), since=args.get("since"))
    out["assigned_to_you"] = _assigned(ctx.list_id, ctx.client)
    return out


def _calendar(ctx, args):
    include = args.get("include_due")
    return schedules.calendar(
        ctx.list_id,
        args["start"],
        args["end"],
        board_ref=args.get("project") or None,
        include_due=True if include is None else include,
    )


def _cmd_find(ctx, args, body):
    project = args.get("project")
    board_id = boards.get_board(ctx.list_id, project)["id"] if project else None
    return reports.search(
        ctx.list_id,
        args["q"],
        kind=args.get("kind"),
        board_id=board_id,
        since=args.get("since"),
        sort=args.get("sort") or "best",
    )


def _cmd_report(ctx, args, body):
    return _report(
        ctx.list_id,
        args["report"],
        days=args.get("days"),
        start=args.get("start"),
        end=args.get("end"),
        kind=args.get("kind"),
        before=args.get("before"),
    )


def _cmd_move(copy: bool):
    def run(ctx, args, body):
        agent_cmd._known(body, ("project", "parent_id"))
        if copy:
            return {
                "item": recordings.copy(
                    ctx.list_id,
                    args["id"],
                    board=body.get("project") or None,
                    parent_id=body.get("parent_id"),
                    source="agent",
                    client=ctx.client,
                )
            }
        if body.get("project") in (None, "") and body.get("parent_id") is None:
            raise ValidationError("Say where: project or parent_id")
        return {
            "item": recordings.move(
                ctx.list_id,
                args["id"],
                parent_id=body.get("parent_id"),
                board=body.get("project") or None,
                source="agent",
                client=ctx.client,
            )
        }

    return run


def _cmd_chat(ctx, args, body):
    return recordings.chat(ctx.list_id, args["project"], since=args.get("since"))


def _cmd_chat_post(ctx, args, body):
    agent_cmd._known(body, ("text",))
    return {
        "line": recordings.create(
            ctx.list_id, args["project"], "chat_line", {"body": body.get("text")}, source="agent", client=ctx.client
        )
    }


def _cmd_import_todos(ctx, args, body):
    agent_cmd._known(body, ("markdown", "parent_id"))
    return recordings.import_todos(
        ctx.list_id,
        args["project"],
        body.get("markdown"),
        parent_id=body.get("parent_id"),
        source="agent",
        client=ctx.client,
    )


def _cmd_people(ctx, args, body):
    return {
        "people": [
            {"id": p["id"], "name": p["name"], "kind": p["kind"], "title": p["title"]}
            for p in people.list_people(ctx.list_id)
        ]
    }


_ITEM_ID = {"id": Arg("integer", "the item's id", required=True)}
_PROJECT_ARG = {"project": Arg("string", "the project's id, or its name", required=True)}
_ITEM = {
    "id": 31,
    "type": "todo",
    "title": "Call the tiler",
    "body": "",
    "board_id": 2,
    "board_name": "Kitchen remodel",
    "parent_id": 30,
    "status": "active",
    "due_on": "2026-11-01",
    "assignees": [{"id": 4, "name": "Claude", "kind": "ai"}],
    "completed": False,
    "comments_count": 1,
    "version": 2,
    "...": "and creator, completer, starts_on, category, color, position, created_at, updated_at",
}

PROJECT_COMMANDS = {
    "PROJECT": Command(
        "A project's page: its tools in order (Board, Messages, To-dos, Docs, "
        "Calendar, Check-ins) with a preview of each, its latest "
        "activity, and everyone who can be assigned. "
        "Start here.",
        False,
        _cmd_project,
        args=_PROJECT_ARG,
        example={
            "request": "GET LINK?cmd=PROJECT&project=Kitchen remodel",
            "response": {"ok": True, "project": {"id": 2, "name": "Kitchen remodel", "dock": ["..."], "previews": {}}},
        },
    ),
    "ITEMS": Command(
        "A project's messages (pinned first), to-do lists (each with completed_count and "
        "todos_count), loose to-dos, folders, documents, links, events, check-in questions, or "
        "the items under one parent (a folder's contents, a question's answers).",
        False,
        _cmd_items,
        args={
            **_PROJECT_ARG,
            "type": Arg(
                "string",
                "message, todolist, todolist_group, todo, step, vault, document, "
                "link, schedule_entry, question or answer",
                required=True,
            ),
            "parent_id": Arg("integer", "only the items under this one"),
            "status": Arg("string", "active (the default), archived, trashed or drafted"),
            "sort": Arg("string", "messages: newest (the default), activity or alpha"),
        },
        example={
            "request": "GET LINK?cmd=ITEMS&project=2&type=todolist",
            "response": {
                "ok": True,
                "items": [
                    {"id": 30, "type": "todolist", "title": "Demolition", "completed_count": 2, "todos_count": 5}
                ],
            },
        },
    ),
    "ITEM": Command(
        "One item whole: its fields, the breadcrumb above it, its comments, and what is under "
        "it (a list's to-dos and groups, a to-do's subtasks).",
        False,
        _cmd_item,
        args=_ITEM_ID,
        example={
            "request": "GET LINK?cmd=ITEM&id=31",
            "response": {"ok": True, "recording": _ITEM, "ancestors": [], "comments": [], "children": []},
        },
    ),
    "ADD_ITEM": Command(
        "Post a message, start a to-do list or group, add a to-do or a subtask, a folder, a "
        "document, a link to a file, a calendar event, a check-in question, or answer one.",
        True,
        _cmd_add,
        args=_PROJECT_ARG,
        body='{"type": required (message, todolist, todolist_group, todo, step, vault, document, '
        'link, schedule_entry, question, answer), "title", "body": markdown, "parent_id": the '
        'list, group, to-do, folder or question it goes under, "card_id": a card for a subtask, '
        '"assignees": names, "due_on", "starts_on", "category", "color", "draft": true to leave '
        'a message unposted; link: "url"; schedule_entry: "starts_on" (required), "ends_on", '
        '"starts_at" and "ends_at" (HH:MM), "all_day", "url" (a join link), "highlighted", '
        '"repeat" (every_day, every_weekday, every_week, every_other_week, every_month, '
        'every_year), "repeat_until"; question: "frequency" (every_day, every_week, '
        'every_other_week, every_month), "days" (0 = Sunday), "time", "paused"; answer: '
        '"group_on" (the day it answers, default today); todo: "repeat" (as schedule_entry: '
        'finishing it adds the next); a drafted message: "post_at" (an ISO date-time it posts '
        "itself at)}",
        example={
            "request": "POST LINK?cmd=ADD_ITEM&project=2",
            "body": {
                "type": "todo",
                "title": "Call the tiler",
                "parent_id": 30,
                "assignees": ["me"],
                "due_on": "2026-11-01",
            },
            "response": {"ok": True, "item": _ITEM},
        },
    ),
    "UPDATE_ITEM": Command(
        "Change an item's fields (the rest stay). With version, refused when it changed "
        "since. post: true posts a drafted message.",
        True,
        _cmd_update,
        args=_ITEM_ID,
        body='{"version", "title", "body", "assignees", "due_on", "starts_on", "category", '
        '"color", "pinned", "post", and the type\'s own fields as ADD_ITEM lists them}: any of them',
        example={
            "request": "POST LINK?cmd=UPDATE_ITEM&id=31",
            "body": {"due_on": "2026-11-08"},
            "response": {"ok": True, "item": _ITEM},
        },
    ),
    "COMPLETE_TODO": Command(
        "Check off a to-do or subtask.",
        True,
        _cmd_complete(True),
        args=_ITEM_ID,
        body="none: send no body, or {}",
        example={
            "request": "POST LINK?cmd=COMPLETE_TODO&id=31",
            "response": {"ok": True, "item": {**_ITEM, "completed": True}},
        },
    ),
    "REOPEN_TODO": Command(
        "Re-open a completed to-do or subtask.",
        True,
        _cmd_complete(False),
        args=_ITEM_ID,
        body="none: send no body, or {}",
        example={"request": "POST LINK?cmd=REOPEN_TODO&id=31", "response": {"ok": True, "item": _ITEM}},
    ),
    "COMMENT": Command(
        "Comment on an item (id) or a card (card_id): an answer, progress, a decision. It shows under your name.",
        True,
        _cmd_comment,
        args={"id": Arg("integer", "the item's id"), "card_id": Arg("integer", "or a card's id")},
        body='{"text": required, markdown}',
        example={
            "request": "POST LINK?cmd=COMMENT&id=31",
            "body": {"text": "Booked for Tuesday."},
            "response": {"ok": True, "comment": {"id": 40, "type": "comment", "body": "Booked for Tuesday."}},
        },
    ),
    "MOVE_ITEM": Command(
        "Move an item: a to-do to another list or group (parent_id), a document, link or folder "
        "into a folder, or a top-level item to another project. It keeps its comments and history.",
        True,
        _cmd_move(False),
        args=_ITEM_ID,
        body='{"project": a project id or name (the top of its tool there), or "parent_id": the '
        "list, group or folder it goes under}",
        example={
            "request": "POST LINK?cmd=MOVE_ITEM&id=31",
            "body": {"parent_id": 44},
            "response": {"ok": True, "item": {**_ITEM, "parent_id": 44}},
        },
    ),
    "COPY_ITEM": Command(
        "Copy an item (and what is under it: a list's to-dos, a folder's documents) to the same "
        "place, under a parent, or to another project. The copy starts with no comments.",
        True,
        _cmd_move(True),
        args=_ITEM_ID,
        body='{"project": optional, "parent_id": optional}',
        example={
            "request": "POST LINK?cmd=COPY_ITEM&id=30",
            "body": {"project": "Garage"},
            "response": {"ok": True, "item": {**_ITEM, "id": 52, "type": "todolist"}},
        },
    ),
    "ARCHIVE_ITEM": Command(
        "Archive an item. Nothing is deleted: RESTORE_ITEM brings it back.",
        True,
        _cmd_status("archived"),
        args=_ITEM_ID,
        body="none: send no body, or {}",
        example={
            "request": "POST LINK?cmd=ARCHIVE_ITEM&id=31",
            "response": {"ok": True, "item": {**_ITEM, "status": "archived"}},
        },
    ),
    "RESTORE_ITEM": Command(
        "Bring an archived or trashed item back.",
        True,
        _cmd_status("active"),
        args=_ITEM_ID,
        body="none: send no body, or {}",
        example={"request": "POST LINK?cmd=RESTORE_ITEM&id=31", "response": {"ok": True, "item": _ITEM}},
    ),
    "ACTIVITY": Command(
        "What happened lately, newest first: who did what to which item, in which project. "
        "50 a page; for the next, send the answer's next_before as before. latest is the cursor "
        "for next time: send it as since to get only what is new. assigned_to_you lists the "
        "open to-dos and cards assigned to you.",
        False,
        _cmd_activity,
        args={
            "project": Arg("string", "only this project: its id or name"),
            "before": Arg("integer", "the last page's next_before"),
            "since": Arg("integer", "only what came after this: the latest you were given"),
        },
        example={
            "request": "GET LINK?cmd=ACTIVITY",
            "response": {
                "ok": True,
                "events": [
                    {
                        "verb": "completed",
                        "board_name": "Kitchen",
                        "recording_title": "Call the tiler",
                        "creator": {"name": "Me"},
                    }
                ],
                "next_before": None,
            },
        },
    ),
    "CALENDAR": Command(
        "What is on the calendar from start to end (YYYY-MM-DD, at most 400 days): every event "
        "occurrence, with the day it falls on, and the open to-dos, subtasks and cards due.",
        False,
        lambda ctx, args, body: _calendar(ctx, args),
        args={
            "start": Arg("date", "the first day", required=True),
            "end": Arg("date", "the last day", required=True),
            "project": Arg("string", "only this project: its id or name"),
            "include_due": Arg("boolean", "also what is due (default true)"),
        },
        example={
            "request": "GET LINK?cmd=CALENDAR&start=2026-11-01&end=2026-11-30",
            "response": {
                "ok": True,
                "events": [{"id": 50, "title": "Tile delivery", "on": "2026-11-04", "all_day": True}],
                "due": [{"kind": "todo", "title": "Call the tiler", "on": "2026-11-05"}],
            },
        },
    ),
    "CHAT": Command(
        "A project's chat, oldest first: the latest lines, or (since) only what was said after "
        "your last read. latest is the cursor for next time.",
        False,
        _cmd_chat,
        args={**_PROJECT_ARG, "since": Arg("integer", "only lines after this: the latest you were given")},
        example={
            "request": "GET LINK?cmd=CHAT&project=Kitchen remodel",
            "response": {
                "ok": True,
                "lines": [{"id": 70, "body": "Tiler is here.", "creator": {"name": "Me"}}],
                "latest": 70,
            },
        },
    ),
    "CHAT_POST": Command(
        "Say something in a project's chat, under your name. Keep it short; longer things go in Messages.",
        True,
        _cmd_chat_post,
        args=_PROJECT_ARG,
        body='{"text": required, markdown}',
        example={
            "request": "POST LINK?cmd=CHAT_POST&project=Kitchen remodel",
            "body": {"text": "On it."},
            "response": {"ok": True, "line": {"id": 71, "type": "chat_line", "body": "On it."}},
        },
    ),
    "IMPORT_TODOS": Command(
        "Add to-dos from Markdown, under your name: a heading starts a to-do list, each other "
        "line is a to-do, an indented line a subtask of the to-do above, '- [x]' one done. "
        "parent_id imports into a list (headings become groups) or a group. At most 500 lines.",
        True,
        _cmd_import_todos,
        args=_PROJECT_ARG,
        body='{"markdown": required, "parent_id"}',
        example={
            "request": "POST LINK?cmd=IMPORT_TODOS&project=Kitchen remodel",
            "body": {"markdown": "# Week one\n- Measure\n  - Order tile\n- [x] Book the fitter"},
            "response": {"ok": True, "lists": 1, "groups": 0, "todos": 2, "subtasks": 1, "completed": 1},
        },
    ),
    "FIND": Command(
        "Find text in every project, archived ones too (not the trash): messages, documents, "
        "to-dos, comments, events, check-ins and cards. Every word must appear in the title or "
        "the text; each result quotes the text around it.",
        False,
        _cmd_find,
        args={
            "q": Arg("string", "the words to find", required=True),
            "kind": Arg("string", "only this kind: " + ", ".join(reports.SEARCH_KINDS)),
            "project": Arg("string", "only this project: its id or name"),
            "since": Arg("date", "only what was made on or after this day"),
            "sort": Arg("string", "best (title matches first, the default) or recent"),
        },
        example={
            "request": "GET LINK?cmd=FIND&q=tile",
            "response": {
                "ok": True,
                "q": "tile",
                "count": 1,
                "results": [
                    {
                        "id": 31,
                        "type": "todo",
                        "title": "Call the tiler",
                        "board_name": "Kitchen",
                        "snippet": "Ask about the grout colour",
                        "title_match": True,
                    }
                ],
            },
        },
    ),
    "REPORT": Command(
        "Reports across every project. report is one of: " + _REPORTS + ". The "
        "Needle and the Hill Chart are the user's to set; you read them.",
        False,
        _cmd_report,
        args={
            "report": Arg(
                "string",
                "overdue, upcoming, unassigned, progress, mission_control, hilltop or everything",
                required=True,
            ),
            "days": Arg("integer", "upcoming: how many days ahead"),
            "start": Arg("date", "progress: the first day"),
            "end": Arg("date", "progress: the last day"),
            "kind": Arg("string", "everything: messages, docs, tasks, comments or checkins"),
            "before": Arg("string", "everything: the last page's next_before"),
        },
        example={
            "request": "GET LINK?cmd=REPORT&report=overdue",
            "response": {
                "ok": True,
                "today": "2026-11-10",
                "count": 1,
                "groups": [
                    {
                        "label": "Under a week late",
                        "items": [
                            {
                                "kind": "todo",
                                "id": 31,
                                "title": "Call the tiler",
                                "on": "2026-11-08",
                                "days_late": 2,
                                "board_name": "Kitchen",
                            }
                        ],
                    }
                ],
            },
        },
    ),
    "PEOPLE": Command(
        "Everyone who can be assigned or mentioned: the user ('me'), the people they added, "
        "and the AI tools that have worked here.",
        False,
        _cmd_people,
        example={
            "request": "GET LINK?cmd=PEOPLE",
            "response": {"ok": True, "people": [{"id": 1, "name": "Me", "kind": "me"}]},
        },
    ),
}


def _guide(ctx, row, today) -> dict:
    out = agent_cmd._projects_guide(ctx, row, today)
    out["reaches"] = ["projects (kanban boards of cards, with messages, to-dos and docs beside them)"]
    out["about"] = (
        "The projects are Projects GTD: each is a kanban board with tools beside it. PROJECT opens one. "
        "Messages, to-do lists, to-dos, subtasks, folders, documents, links, events and "
        "check-ins are items (ITEMS, ITEM, ADD_ITEM, UPDATE_ITEM, COMPLETE_TODO, COMMENT); "
        "CALENDAR reads the calendar; ACTIVITY says which check-ins you are asked today; "
        "REPORT reads Reports (overdue, upcoming, the Needles, the Hill Charts) and FIND "
        "searches every project; "
        "each project's board is BOARD and the _CARD commands. What you write shows "
        "under your name."
    )
    out["about"] += " " + _SAMPLES
    out["reads"] = {
        **out["reads"],
        "activity": f"{ctx.mcp['url']}?cmd=ACTIVITY",
        "people": f"{ctx.mcp['url']}?cmd=PEOPLE",
    }
    return out


agent_cmd.register_app("projects", {**agent_cmd._BOARD_COMMANDS, **PROJECT_COMMANDS}, _guide)
