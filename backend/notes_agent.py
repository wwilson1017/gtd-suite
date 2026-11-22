"""Notes GTD on the agent link: its MCP tools, its Agent Commands and its part of
the guide, each a thin call into notes.py. main.py imports it; the link offers
them only while Notes is on for the account (mcp_server._AppsOn, agent_cmd.dispatch).

No delete tool or command: ARCHIVE_NOTE is status 'archived'. The list comes from
the token, never an argument, and provenance is set here. A stale version is a
plain refusal on this side (a tool error, a 400), since neither MCP nor the
guide's error table has a 409.
"""


# _arg(...) in tool signatures is a call inside an annotation, which pyright cannot read.
# pyright: reportInvalidTypeForm=false

from backend.plans import plans
from backend import agent_cmd, common, mcp_server, notes, settings
from backend.agent_cmd import Arg, Command
from backend.common import ConflictError, ValidationError
from backend.mcp_server import _arg, _client_name, _given, _list_id, _tool
from backend.models import NoteCreate, NoteUpdate

mcp_server.INSTRUCTIONS["notes"] = (
    "Notes GTD (the note_ tools) is the user's notes: cards like Google Keep's, each an "
    "optional title and a markdown body. Tags are inline #hashtags in the body, and "
    "checklists are '- [ ]' lines. Search before adding, so you add to a note on the subject "
    "rather than start a second one. Make small changes with note_edit (an exact string "
    "that occurs once) or note_append; rewrite a whole body with note_update only after "
    "note_get, passing the version it returned. Nothing can be deleted: archive a note "
    "instead, and it can come back. Say what you changed."
)

_COLOR = f"One of {', '.join(c for c in notes.COLORS if c)}, or empty for none"


def _summary(note: dict, query: str = "") -> dict:
    """A note as search lists it: a snippet in place of the body."""
    return {**{k: v for k, v in note.items() if k != "body"}, "snippet": notes.snippet(note, query)}


def _searched(list_id: int, query, tag, status, limit, offset) -> dict:
    found = notes.search(list_id, query, tag, status, limit, offset)
    return {**found, "notes": [_summary(n, query) for n in found["notes"]]}


def _update(list_id: int, note_id: int, fields: dict, version, by: str) -> dict:
    try:
        return notes.update(list_id, note_id, fields, version, by=by)
    except ConflictError as e:
        raise ValidationError(str(e)) from None


# ── MCP tools ─────────────────────────────────────────────────────────────────


def _by() -> str:
    return _client_name() or "AI tool"


@_tool("Search notes", read_only=True, app="notes")
def note_search(
    query: _arg(str, "Words the title or body must all hold, in any case. Empty lists every note") = "",
    tag: _arg(str, "Only notes carrying this #tag") = "",
    status: _arg(str, "'active' (the default), 'archived' or 'all'") = "active",
    limit: _arg(int, f"At most this many, 1 to {notes.PAGE}") = 20,
    offset: _arg(int, "Skip this many: the last page's next_offset") = 0,
) -> dict:
    """Find the user's notes: pinned first, then those with every word in the title,
    then the most recently changed. Each comes without its body, with a snippet
    around the match; note_get reads a whole note."""
    return _searched(_list_id.get(), query, tag, status, limit, offset)


@_tool("Read a note", read_only=True, app="notes")
def note_get(id: _arg(int, "The note's id")) -> dict:
    """One whole note: title, markdown body, tags, colour, pin, status, who last
    edited it, and its version (note_update needs it to rewrite the note)."""
    return {"note": notes.get(_list_id.get(), id)}


@_tool("Add a note", read_only=False, app="notes")
def note_create(
    body: _arg(str, "The note, in markdown. #hashtags tag it; '- [ ] item' lines make a checklist"),
    title: _arg(str, "A short title; optional") = "",
    pinned: _arg(bool, "Pin it to the top") = False,
    color: _arg(str, _COLOR) = "",
) -> dict:
    """Add a new note. Search first: when a note on the subject exists, add to it
    with note_append or note_edit instead."""
    return {
        "note": notes.create(
            _list_id.get(), title, body, color=color, pinned=pinned, source="agent", source_client=_client_name()
        )
    }


@_tool("Append to a note", read_only=False, app="notes")
def note_append(
    id: _arg(int, "The note's id"),
    text: _arg(str, "What to add at the end, in markdown"),
) -> dict:
    """Add text to the end of a note without rewriting it. A list item ('- [ ] eggs')
    lands on the line after a list; anything else after a blank line."""
    return {"note": notes.append(_list_id.get(), id, text, by=_by())}


@_tool("Edit a note", read_only=False, app="notes")
def note_edit(
    id: _arg(int, "The note's id"),
    old_str: _arg(str, "The exact text to replace, copied from note_get; it must occur exactly once in the body"),
    new_str: _arg(str, "What replaces it; empty removes it"),
) -> dict:
    """Replace one exact piece of a note's body and leave the rest as it is: a fact,
    a line, or ticking a checklist item ('- [ ] eggs' to '- [x] eggs')."""
    return {"note": notes.edit(_list_id.get(), id, old_str, new_str, by=_by())}


@_tool("Update a note", read_only=False, app="notes")
def note_update(
    id: _arg(int, "The note's id"),
    expected_version: _arg(int | None, "The version note_get returned. Required with title or body") = None,
    title: _arg(str | None, "A new title; empty clears it") = None,
    body: _arg(str | None, "A whole new body, in markdown") = None,
    color: _arg(str | None, _COLOR) = None,
    pinned: _arg(bool | None, "Pin or unpin it") = None,
    archived: _arg(bool | None, "true archives it, false brings it back") = None,
) -> dict:
    """Rewrite a note's title or whole body, change its colour or pin, or archive or
    restore it; fields left out stay. When the note changed after expected_version,
    nothing is saved and the error says so: read it again. For a small change use
    note_edit or note_append instead."""
    list_id = _list_id.get()
    fields = _given(title=title, body=body, color=color, pinned=pinned)
    if archived is not None:
        fields["status"] = "archived" if archived else "active"
    if not fields:
        return {"note": notes.get(list_id, id)}
    return {"note": _update(list_id, id, fields, expected_version, _by())}


# ── Agent Commands ────────────────────────────────────────────────────────────


def _cmd_by(ctx) -> str:
    return ctx.client or "AI tool"


def _cmd_notes(ctx, args, body):
    return _searched(
        ctx.list_id,
        args.get("q", ""),
        args.get("tag", ""),
        args.get("status", "active"),
        args.get("limit", 100),
        args.get("offset", 0),
    )


def _cmd_export(ctx, args, body):
    return notes.search(ctx.list_id, status="all", limit=notes.PAGE, offset=args.get("offset", 0))


def _cmd_note(ctx, args, body):
    return {"note": notes.get(ctx.list_id, args["id"])}


def _cmd_add(ctx, args, body):
    req = agent_cmd._model(NoteCreate, body)
    return {
        "note": notes.create(
            ctx.list_id,
            req.title,
            req.body,
            color=req.color,
            pinned=req.pinned,
            source="agent",
            source_client=ctx.client,
        )
    }


def _cmd_append(ctx, args, body):
    agent_cmd._known(body, ("text",))
    return {"note": notes.append(ctx.list_id, args["id"], body.get("text"), by=_cmd_by(ctx))}


def _cmd_edit(ctx, args, body):
    agent_cmd._known(body, ("old_str", "new_str"))
    return {"note": notes.edit(ctx.list_id, args["id"], body.get("old_str"), body.get("new_str"), by=_cmd_by(ctx))}


def _cmd_update(ctx, args, body):
    fields = agent_cmd._model(NoteUpdate, body).model_dump(exclude_unset=True)
    version = fields.pop("version", None)
    return {"note": _update(ctx.list_id, args["id"], fields, version, _cmd_by(ctx))}


def _cmd_archive(ctx, args, body):
    return {"note": _update(ctx.list_id, args["id"], {"status": "archived"}, None, _cmd_by(ctx))}


_ID = {"id": Arg("integer", "the note's id", required=True)}
_NOTE = {
    "id": 12,
    "title": "Groceries",
    "body": "- [ ] milk\n- [ ] eggs\n\n#home",
    "tags": ["home"],
    "color": "",
    "pinned": False,
    "status": "active",
    "version": 3,
    "...": "and source, source_client, edited_by, created_at, updated_at",
}
_SUMMARY = {**{k: v for k, v in _NOTE.items() if k != "body"}, "snippet": "- [ ] milk - [ ] eggs #home"}

NOTE_COMMANDS = {
    "NOTES": Command(
        "Find notes: every word of q in the title or body (any case), and/or a #tag. Pinned "
        "first, then those with every word in the title, then the most recently changed. Each "
        "note comes without its body, with a snippet; NOTE reads one whole.",
        False,
        _cmd_notes,
        args={
            "q": Arg("string", "words the note must all hold; omit it to list every note"),
            "tag": Arg("string", "only notes carrying this tag, without the #"),
            "status": Arg("string", "active (the default), archived or all"),
            "limit": Arg("integer", f"1 to {notes.PAGE}; default 100"),
            "offset": Arg("integer", "the last page's next_offset"),
        },
        example={
            "request": "GET LINK?cmd=NOTES&q=milk",
            "response": {"ok": True, "notes": [_SUMMARY], "count": 1, "next_offset": None},
        },
    ),
    "NOTE": Command(
        "One whole note, with its version (UPDATE_NOTE needs it to rewrite the note).",
        False,
        _cmd_note,
        args=_ID,
        example={"request": "GET LINK?cmd=NOTE&id=12", "response": {"ok": True, "note": _NOTE}},
    ),
    "EXPORT_NOTES": Command(
        f"Every note, archived ones too, whole, {notes.PAGE} a page: GET each answer's next_url until one has none.",
        False,
        _cmd_export,
        args={"offset": Arg("integer", "the last page's next_offset")},
        example={
            "request": "GET LINK?cmd=EXPORT_NOTES",
            "response": {"ok": True, "notes": [_NOTE], "count": 1, "next_offset": None},
        },
    ),
    "ADD_NOTE": Command(
        "Add a note. Search (NOTES) first: when one on the subject exists, add to it with "
        "APPEND_NOTE or EDIT_NOTE instead.",
        True,
        _cmd_add,
        body='{"body": markdown, "title", "color", "pinned"}: a body or a title is required',
        example={
            "request": "POST LINK?cmd=ADD_NOTE",
            "body": {"title": "Groceries", "body": "- [ ] milk\n- [ ] eggs\n\n#home"},
            "response": {"ok": True, "note": {**_NOTE, "version": 1}},
        },
    ),
    "APPEND_NOTE": Command(
        "Add text to the end of a note without rewriting it: a list item lands on the line "
        "after a list, anything else after a blank line.",
        True,
        _cmd_append,
        args=_ID,
        body='{"text": required}',
        example={
            "request": "POST LINK?cmd=APPEND_NOTE&id=12",
            "body": {"text": "- [ ] bread"},
            "response": {"ok": True, "note": {**_NOTE, "version": 4}},
        },
    ),
    "EDIT_NOTE": Command(
        "Replace one exact piece of a note's body, which must occur exactly once, and leave "
        "the rest as it is. Ticks a checklist item too.",
        True,
        _cmd_edit,
        args=_ID,
        body='{"old_str": required, copied exactly from NOTE, "new_str": "" removes it}',
        example={
            "request": "POST LINK?cmd=EDIT_NOTE&id=12",
            "body": {"old_str": "- [ ] milk", "new_str": "- [x] milk"},
            "response": {"ok": True, "note": {**_NOTE, "version": 4}},
        },
    ),
    "UPDATE_NOTE": Command(
        "Rewrite a note's title or whole body, change its colour or pin, or archive or restore "
        "it (status). A new title or body needs the version NOTE returned; when the note "
        "changed since, nothing is saved and the error says so.",
        True,
        _cmd_update,
        args=_ID,
        body='{"version", "title", "body", "color", "pinned", "status": active or archived}: any of them',
        example={
            "request": "POST LINK?cmd=UPDATE_NOTE&id=12",
            "body": {"version": 3, "body": "- [x] milk\n- [ ] eggs\n\n#home"},
            "response": {"ok": True, "note": {**_NOTE, "version": 4}},
        },
    ),
    "ARCHIVE_NOTE": Command(
        "Archive a note. Nothing is deleted: UPDATE_NOTE with status active brings it back.",
        True,
        _cmd_archive,
        args=_ID,
        body="none: send no body, or {}",
        example={
            "request": "POST LINK?cmd=ARCHIVE_NOTE&id=12",
            "response": {"ok": True, "note": {**_NOTE, "status": "archived"}},
        },
    ),
}


def _guide(ctx, row, today) -> dict:
    """Notes GTD's part of HELP."""
    cap = common.note_cap_for(row["email_verified_at"] is not None, settings.open_signup(), plans.of(row))
    return {
        "reaches": ["notes"],
        "about": "The notes are Notes GTD: NOTES, NOTE, EXPORT_NOTES and the _NOTE commands.",
        "reads": {"notes": f"{ctx.mcp['url']}?cmd=NOTES&limit={notes.PAGE}"},
        "limits": {"notes_per_list": cap, "notes_per_page": notes.PAGE, "note_body_chars": common.MAX_TEXT_CHARS},
        "notes": {
            "tags": "inline #hashtags in the body; a heading's '# ' is not one",
            "checklists": "'- [ ] item' lines; EDIT_NOTE from '- [ ] item' to '- [x] item' ticks one",
            "colors": [c for c in notes.COLORS if c],
            "archive": "ARCHIVE_NOTE; UPDATE_NOTE with status active brings it back",
        },
    }


agent_cmd.register_app("notes", NOTE_COMMANDS, _guide)
