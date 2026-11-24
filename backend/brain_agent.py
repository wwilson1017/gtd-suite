"""Common Brain on the agent link: its MCP tools and its paragraph of the
instructions, each a thin call into brain.py. main.py imports it; the link offers
them only while Brain is on for the account (mcp_server._AppsOn).

MCP only: Brain has no Agent Commands. No tool forgets anything: brain_forget_link
hands the person a link to the app, where they confirm. The list comes from the
token, never an argument, and who wrote what is the calling tool's own name, or
the program key's.

A folder-limited key (keys.py) reaches only mcp_server.FOLDER_KEY_TOOLS. Its page
writes stay inside its folders (_may_write), and every read and write it makes
passes `restricted`, so brain.py never shows it a confidential page.
"""

# _arg(...) in tool signatures is a call inside an annotation, which pyright cannot read.
# pyright: reportInvalidTypeForm=false

import contextlib
import re
from typing import cast

from backend import brain as store
from backend import db, files, keys, mcp_server, readlog, settings
from backend.common import ConflictError, NotFoundError, ValidationError
from backend.mcp_server import _apps_on, _arg, _client_name, _key, _tool


def _scope() -> list[dict]:
    """The only source of brain authority: the request's validated, ordered grant."""
    carried = mcp_server._brains.get()
    if not carried:
        raise ValidationError("This link reaches no active brain")
    current = store.grant_in(db.get_db(), carried[0]["list_id"], [b["id"] for b in carried], stored=True)
    if not current:
        raise ValidationError("This link reaches no active brain")
    return current


def _select(folder: str | None = None) -> dict:
    carried = _scope()
    if folder is None:
        return carried[0]
    for b in carried:
        if b["folder"] == folder.strip("/"):
            return b
    raise ValidationError("Choose a brain: " + ", ".join(b["folder"] for b in carried))


def _item(kind: str, ident: int) -> dict:
    store._kind(kind)
    carried = _scope()
    table = "brain_memories" if kind == "memory" else "brain_pages"
    row = db.get_db().execute(f"SELECT brain_id FROM {table} WHERE id = ?", (ident,)).fetchone()
    if row:
        for b in carried:
            if row["brain_id"] == b["id"]:
                return b
    raise NotFoundError("Item not found")


def _split(path: str) -> tuple[dict, str]:
    carried = _scope()
    if len(carried) == 1:
        return carried[0], path
    head, _, rest = path.strip("/").partition("/")
    for b in carried:
        if head == b["folder"]:
            return b, rest
    raise ValidationError("Start the path with a brain folder: " + ", ".join(b["folder"] + "/" for b in carried))


def _working(folder: str, brain: str | None) -> tuple[dict, str]:
    chosen = _select(brain)
    if len(_scope()) > 1 and folder.strip("/").split("/")[0] in {b["folder"] for b in _scope()}:
        b, rest = _split(folder)
        if brain is not None and b["id"] != chosen["id"]:
            raise ValidationError("folder and brain name different brains")
        return b, rest
    return chosen, folder


def _prose(b: dict, text: str, working: str = "curator") -> str:
    """Rewrite only server-authored path guidance, never user content or search text."""
    if len(_scope()) == 1:
        return text
    names = sorted({working, "people", "projects", "topics", "inbox", "daily", "curator"}, key=len, reverse=True)
    text = re.sub(
        r"(?<![\w/])(" + "|".join(re.escape(n) for n in names) + r")/", lambda m: b["folder"] + "/" + m[0], text
    )
    text = text.replace(f"folder={working}", f"folder={b['folder']}/{working}")
    return text.replace("keep now (the page 'now')", f"keep {b['folder']}/now (the page '{b['folder']}/now')").replace(
        "Keep now (the page 'now')", f"Keep {b['folder']}/now (the page '{b['folder']}/now')"
    )


def _place[T](b: dict, result: T) -> T:
    """Response audit: path fields, folder metadata, queue strings and change captions.
    Page bodies, titles, memory text, rules written by the person and queries are data.
    """
    if len(_scope()) == 1:
        return result
    prefix = b["folder"] + "/"

    def walk(value, key=""):
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, dict):
            out = {k: walk(v, k) for k, v in value.items()}
            if value.get("path") and "what" in out:
                out["what"] = out["what"].replace("(" + value["path"] + ")", "(" + out["path"] + ")")
            return out
        if isinstance(value, str) and value and key in ("path", "folder", "inbox", "this_weeks_journal"):
            return prefix + value
        return value

    return cast(T, walk(result))


def _instructions() -> str:
    carried = _scope()
    return store.instructions([b["id"] for b in carried])


mcp_server.INSTRUCTIONS["brain"] = _instructions


def _by(name: str | None = None) -> str:
    """A client that calls itself "you" is not the person: brain.YOU is theirs alone.
    `name`: one already worked out (the handshake's, in mcp_server._AppsOn)."""
    name = name or _client_name() or store.UNKNOWN_AI
    return store.UNKNOWN_AI if name.strip().lower() == store.YOU else name


def _read(
    b: dict | list[dict],
    kind: str,
    item_kind: str | None = None,
    item_id: int | None = None,
    target: str = "",
    *,
    by: str | None = None,
) -> None:
    """The read log (readlog.py): this request handed back content of brain `b`, or of each
    of several. The rule for a tool: if its answer carries an existing item's content, it
    calls this last, with the answer already built (_place can still refuse), after the read
    and outside any transaction. Never raises."""
    brains = b if isinstance(b, list) else [b]
    readlog.log(
        brains[0]["list_id"], [x["id"] for x in brains], by or _by(), _key.get(), kind, item_kind, item_id, target
    )


def _made(page: dict, text: str | None) -> bool:
    """The answer holds only the words this call sent: a first version whose body is `text`.
    Then a write that returns the page is not a read. Nothing here trusts the caller's name."""
    return page["version"] == 1 and text is not None and page["body"].strip() == text.strip()


def _read_key() -> bool:
    key = _key.get()
    return bool(key and key["access"] == "read")


def _folders() -> list[str]:
    """The folders a program key is limited to; empty for every other caller."""
    key = _key.get()
    return key["folders"] if key else []


def _may_write(*paths) -> None:
    """A folder-limited key writes pages only inside its folders: `path`, and `move_to`."""
    folders = _folders()
    for path in paths:
        if folders and path is not None and not keys.inside(path, folders):
            raise ValidationError(
                f"This key writes only inside {', '.join(f + '/' for f in folders)}. Nothing was saved."
            )


@contextlib.contextmanager
def _write():
    try:
        with db.transaction() as conn:
            yield conn
    except ConflictError as exc:
        raise ValidationError(str(exc)) from None


def _plain(fn, *args, **kwargs):
    """A stale version is a plain refusal on this side: MCP has no 409."""
    try:
        return fn(*args, **kwargs)
    except ConflictError as e:
        raise ValidationError(str(e)) from None


@_tool("Start with the brain", read_only=True, app="brain")
def brain_start() -> dict:
    """Call this first in every conversation, before answering. Returns the rules
    every AI follows here, every memory (locked ones are the person's own words),
    the pages, what changed since you were last here, where things go across the
    person's apps, and whether to set up or tidy the brain."""
    carried = _scope()
    results, mems = [], []
    for b in carried:
        part = _place(b, store.start(b["id"], _by(), _apps_on.get(), restricted=bool(_folders())))
        if _read_key():
            part.pop("tidy", None)  # a read-only key cannot tidy
        part["rules"] = [_prose(b, r) for r in store.RULES] + b["rules"]
        mems.extend({**m, "brain": b["folder"]} for m in store.memories(b["id"]))
        part["brain"] = {k: b[k] for k in ("id", "name", "folder", "description", "rules", "ai_access")}
        if len(carried) > 1:
            part["aim"] = (
                f"Use brain={b['folder']} for path-less tools on this brain, and prefix paths with {b['folder']}/."
            )
        if not b["settled_at"] and not _key.get():
            part["set_up"] = (
                "This brain is unnamed. Offer the naming interview in brain_onboard, then brain_setup with the person's agreement."
            )
        results.append(part)
    shown, left = store._core(mems)
    out = (
        results[0]
        if len(results) == 1
        else {
            "you_are": _by(),
            "rules": ["Each brain's rules apply to that brain. Prefix every page and folder with its brain folder."],
            "pages": {
                "count": sum(r["pages"]["count"] for r in results),
                "folders": [f for r in results for f in r["pages"]["folders"]],
                "recent": [p for r in results for p in r["pages"]["recent"]],
            },
            "since_you_were_last_here": [c for r in results for c in r.get("since_you_were_last_here", [])],
            "guidance": [
                {k: v for k, v in r.items() if k not in ("memories", "pages", "since_you_were_last_here")}
                for r in results
            ],
        }
    )
    out["brains"] = [r["brain"] for r in results]
    out["memories"] = shown
    if left:
        out["more_memories"] = f"{left} more memories: brain_search finds them."
    _read(carried, "start")
    return out


@_tool("Search the brain", read_only=True, app="brain")
def brain_search(
    query: _arg(
        str,
        "Words to look for, in any case. A page holding them all ranks "
        "first. A memory must hold them all, unless you put OR between "
        "synonyms: invoice OR bill",
    ),
    probe: _arg(bool, "A check search: do not log a miss") = False,
) -> dict:
    """Find memories and pages about something, best match first. Words match their
    other forms (invoice finds invoices), and a page holding only some of them still
    shows, lower down. Among close matches a locked memory, then an entry naming two or
    more sources, comes before a lone claim; `backing` says how each result is backed. A search that nothing holds every word of is noted for the next
    tidy, so if the results don't answer it, ask the person and save the answer."""
    carried = _scope()
    found = store.search([b["id"] for b in carried], query, by=_by(), restricted=bool(_folders()), probe=probe)
    by_id = {b["id"]: b for b in carried}
    for key in ("memories", "pages"):
        found[key] = [
            {
                **_place(by_id[item["brain_id"]], {k: v for k, v in item.items() if k != "brain_id"}),
                "brain": by_id[item["brain_id"]]["folder"],
            }
            for item in found[key]
        ]
    _read(carried, "search", target=query)
    return found


@_tool("Remember", read_only=False, app="brain")
def brain_remember(
    memories: _arg(
        list[str], "One or more facts, one short fact each, in the third person ('Maya works nights Tue–Thu')"
    ),
    pass_label: _arg(str, "Label for this curation pass, saved in history") = "",
    reason: _arg(str, "Why this change was made, saved in history") = "",
    brain: _arg(str | None, "Brain folder; defaults to the first brain") = None,
    review_on: _arg(str, "Recheck these by this date (YYYY-MM-DD); empty means 90 days from now") = "",
) -> dict:
    """Save lasting facts, preferences or decisions about the person. One the brain
    already holds is skipped, not saved twice. Passwords, keys and card numbers are
    blanked out ([removed: password]) and the rest is saved; `removed` says what went,
    so tell the person."""
    b = _select(brain)
    return _place(
        b, store.remember(b["id"], memories, by=_by(), pass_label=pass_label, reason=reason, review_on=review_on)
    )


@_tool("Change a memory", read_only=False, app="brain")
def brain_memory_update(
    id: _arg(int, "The memory's id"),
    text: _arg(str | None, "Its new text: still one short fact") = None,
    archived: _arg(bool | None, "true archives it (no longer true), false brings it back") = None,
    expected_version: _arg(int | None, "The version you read; a memory changed since is refused") = None,
    pass_label: _arg(str, "Label for this curation pass, saved in history") = "",
    reason: _arg(str, "Why this change was made, saved in history") = "",
    brain: _arg(str | None, "Brain folder; defaults to the first brain") = None,
    review_on: _arg(
        str | None, "Recheck it by this date (YYYY-MM-DD): set one after checking it is still true; '' clears it"
    ) = None,
) -> dict:
    """Correct a memory, or archive one that is no longer true (nothing is deleted:
    say what replaced it). A locked memory cannot be changed: ask the person."""
    b = _item("memory", id)
    dest = _select(brain) if brain is not None else b
    status = None if archived is None else "archived" if archived else "active"
    with _write() as conn:
        item = store.update_memory_in(
            conn,
            b["id"],
            id,
            text=text,
            status=status,
            version=expected_version,
            by=_by(),
            pass_label=pass_label,
            reason=reason,
            review_on=review_on,
        )
        if dest["id"] != b["id"]:
            item = store.move_to_brain_in(
                conn, "memory", id, dest["id"], None, _by(), item["version"], pass_label=pass_label, reason=reason
            )
    answer = {"memory": _place(dest, item)}
    _read(dest, "get", "memory", id)  # an update with nothing to change still returns its text
    return answer


@_tool("List the brain's pages", read_only=True, app="brain")
def brain_page_list(
    folder: _arg(str, "Only pages in this folder, like people or daily. Empty lists them all") = "",
    archived: _arg(bool, "List archived pages instead") = False,
) -> dict:
    """The pages by path, without their bodies, the folders with how many pages each
    holds, and the files in the folder (PDFs, images and the like; brain_file_link gives
    a link to one)."""
    if not folder and len(carried := _scope()) > 1:
        _read(carried, "list")  # each brain's name and folder
        return {
            "pages": [],
            "files": [],
            "folders": [{"folder": b["folder"], "name": b["name"], "path": b["folder"]} for b in carried],
        }
    b, folder = _split(folder)
    brain_id, restricted = b["id"], bool(_folders())
    status = "archived" if archived else "active"
    found = files.listing(brain_id, folder, (status,), within=_folders())
    out = {
        "pages": store.pages(brain_id, status, folder, restricted=restricted),
        "folders": store.folders(brain_id, restricted=restricted),
        "files": [{k: f[k] for k in ("path", "size", "content_type", "updated_at")} for f in found[: files.LIST_MAX]],
    }
    if len(found) > files.LIST_MAX:
        out["more_files"] = f"{len(found) - files.LIST_MAX} more files are not shown: name a folder to list fewer."
    answer = _place(b, out)
    _read(b, "list", target=folder)
    return answer


@_tool("Read a page", read_only=True, app="brain")
def brain_page_get(path: _arg(str, "The page's path, like people/maya")) -> dict:
    """One whole page: its body (Markdown or HTML), title, who changed it last, and
    its version."""
    b, path = _split(path)
    page = store.get_page(b["id"], path=path, restricted=bool(_folders()))
    answer = _place(b, {"page": page})
    _read(b, "get", "page", page["id"], page["path"])
    return answer


@_tool("Write a page", read_only=False, app="brain")
def brain_page_write(
    path: _arg(str, "The page's path: folders and a name, like people/maya or projects/kitchen-remodel"),
    body: _arg(str | None, "The whole page, in Markdown (or HTML with format 'html'). Required to make a page") = None,
    title: _arg(str | None, "A title; by default the first heading, else the name") = None,
    format: _arg(str | None, "'markdown' (the default) or 'html'") = None,
    move_to: _arg(str | None, "A new path for it") = None,
    archived: _arg(bool | None, "true archives it, false brings it back") = None,
    expected_version: _arg(int | None, "The version you read; a page changed since is refused") = None,
    create_only: _arg(bool, "Only create; refuse a page already at this path") = False,
    expected_id: _arg(int | None, "The page id you read; refuse a different page at this path") = None,
    pass_label: _arg(str, "Label for this curation pass, saved in history") = "",
    reason: _arg(str, "Why this change was made, saved in history") = "",
) -> dict:
    """Make a page, or replace one's whole body, retitle, move or archive it. The
    history keeps every version. For a small change use brain_page_edit; to add a
    line, brain_page_append. A `review_on: YYYY-MM-DD` line in the frontmatter says when
    to recheck the page; without one it comes due 90 days after its last write."""
    b, path = _split(path)
    dest, target = _split(move_to) if move_to is not None else (b, None)
    _may_write(path, target)
    status = None if archived is None else "archived" if archived else "active"
    with _write() as conn:
        if dest["id"] != b["id"]:
            # A cross-brain move starts with an existing page, never a newly-created one.
            store.get_page(b["id"], path=path, restricted=bool(_folders()))
        item = store.write_page_in(
            conn,
            b["id"],
            path,
            body,
            title=title,
            fmt=format,
            version=expected_version,
            move_to=target if dest["id"] == b["id"] else None,
            status=status,
            by=_by(),
            pass_label=pass_label,
            reason=reason,
            restricted=bool(_folders()),
            new=create_only,
            expected_id=expected_id,
        )
        if dest["id"] != b["id"]:
            item = store.move_to_brain_in(
                conn,
                "page",
                item["id"],
                dest["id"],
                target,
                _by(),
                item["version"],
                pass_label=pass_label,
                reason=reason,
            )
    answer = _place(dest, {"page": item})
    if not _made(item, body):  # an unchanged write returns the page as it stands
        _read(dest, "get", "page", item["id"], item["path"])
    return answer


@_tool("Add to a page", read_only=False, app="brain")
def brain_page_append(
    path: _arg(str, "The page's path; today's journal is daily/<YYYY-MM-DD>"),
    text: _arg(str, "What to add at the end, in Markdown"),
    pass_label: _arg(str, "Label for this curation pass, saved in history") = "",
    reason: _arg(str, "Why this change was made, saved in history") = "",
) -> dict:
    """Add text to the end of a page without rewriting it, making the page if it is
    not there yet: the way to keep the daily journal."""
    b, path = _split(path)
    _may_write(path)
    page = _plain(
        store.append_page,
        b["id"],
        path,
        text,
        by=_by(),
        pass_label=pass_label,
        reason=reason,
        restricted=bool(_folders()),
    )
    answer = _place(b, {"page": page})
    if not _made(page, text):  # the answer carries text the caller did not supply
        _read(b, "get", "page", page["id"], page["path"])
    return answer


@_tool("Edit a page", read_only=False, app="brain")
def brain_page_edit(
    path: _arg(str, "The page's path"),
    old_str: _arg(str, "The exact text to replace, copied from brain_page_get; it must occur exactly once"),
    new_str: _arg(str, "What replaces it; empty removes it"),
    pass_label: _arg(str, "Label for this curation pass, saved in history") = "",
    reason: _arg(str, "Why this change was made, saved in history") = "",
) -> dict:
    """Replace one exact piece of a page and leave the rest as it is."""
    b, path = _split(path)
    _may_write(path)
    page = _plain(
        store.edit_page,
        b["id"],
        path,
        old_str,
        new_str,
        by=_by(),
        pass_label=pass_label,
        reason=reason,
        restricted=bool(_folders()),
    )
    answer = _place(b, {"page": page})
    _read(b, "get", "page", page["id"], page["path"])  # the answer carries text the caller did not supply
    return answer


@_tool("A link to a file", read_only=True, app="brain")
def brain_file_link(
    path: _arg(str, "The file's path exactly as brain_page_list shows it, like raw/2026/scan.pdf"),
) -> dict:
    """A download link to one of the brain's files (a PDF, an image, a recording),
    good for 10 minutes: fetch it, or give it to the person."""
    b, path = _split(path)
    folders = _folders()
    if folders and not keys.inside(path, folders, file=True):
        raise ValidationError(f"This key reaches only files inside {', '.join(f + '/' for f in folders)}.")
    got = files.link(b["id"], path=path, seconds=files.LINK_SECONDS)
    answer = _place(
        b,
        {
            "link": got["url"],
            "minutes": files.LINK_SECONDS // 60,
            "file": {k: got["file"][k] for k in ("path", "size", "content_type", "sha256", "updated_at")},
        },
    )
    _read(b, "link", "file", got["file"]["id"], got["file"]["path"])
    return answer


@_tool("A memory's or page's history", read_only=True, app="brain")
def brain_history(
    kind: _arg(str, "'memory' or 'page'"),
    id: _arg(int, "The memory's or page's id"),
) -> dict:
    """Every version of a memory or a page, newest first: what it said, who changed
    it and when."""
    b = _item(kind, id)
    versions = store.history(b["id"], kind, id)
    answer = _place(b, {"versions": versions})
    _read(b, "history", kind, id, versions[0].get("path", "") if versions else "")
    return answer


@_tool("Restore a version", read_only=False, app="brain")
def brain_restore(
    kind: _arg(str, "'memory' or 'page'"),
    id: _arg(int, "The memory's or page's id"),
    version: _arg(int, "The version to bring back, from brain_history"),
    pass_label: _arg(str, "Label for this curation pass, saved in history") = "",
    reason: _arg(str, "Why this change was made, saved in history") = "",
) -> dict:
    """Bring a memory or page back to an earlier version. The restore is a new
    version: nothing in between is lost."""
    b = _item(kind, id)
    item = store.restore(b["id"], kind, id, version, by=_by(), pass_label=pass_label, reason=reason)
    answer = _place(b, {"restored": item})
    _read(b, "get", kind, id, item.get("path", ""))  # restoring the version it already has returns the item
    return answer


@_tool("What changed", read_only=True, app="brain")
def brain_changes(
    since: _arg(str, "Only changes after this ISO time; empty for the latest") = "",
    limit: _arg(int, "At most this many, 1 to 500") = 50,
    brain: _arg(str | None, "Brain folder; defaults to the first brain") = None,
) -> dict:
    """The brain's changes, newest first: each with which AI (or the person, 'you')
    made it, when, and what it says now."""
    b = _select(brain)
    changes = store.changes(b["id"], since or None, limit)
    answer = _place(b, {"changes": changes})
    _read(b, "changes")
    return answer


@_tool("Set up the brain", read_only=True, app="brain")
def brain_onboard(brain: _arg(str | None, "Brain folder; defaults to the first brain") = None) -> dict:
    """The set-up script, once per AI: bring over what you know about the person,
    check it against the brain, ask about the gaps, and report. Call it when the
    person says "set up my brain", or when brain_start says to offer it."""
    b = _select(brain)
    out = store.onboard_script(b["id"], _by())
    out["script"] = [_prose(b, step) for step in out["script"]]
    if _key.get() and not b["settled_at"]:
        out["script"][0] = "The person names and sets the rules for this brain in Common Brain."
    if len(_scope()) > 1:
        out["script"][0] = (
            f"This interview is for {b['folder']}: use brain={b['folder']} on path-less tools. "
            "After brain_setup names it, call brain_start again for its new folder. " + out["script"][0]
        )
    answer = _place(b, out)
    _read(b, "start")  # the script carries the memories, as brain_start does
    return answer


@_tool("Finish setting up", read_only=False, app="brain")
def brain_onboard_done(brain: _arg(str | None, "Brain folder; defaults to the first brain") = None) -> dict:
    """Mark this AI's set-up done. Returns the one line the person pastes into
    this AI's custom instructions, so every chat starts with the brain."""
    b = _select(brain)
    return store.onboarded(b["id"], _by())


@_tool("Tidy the brain", read_only=True, app="brain")
def brain_curate(
    misses_since: _arg(str, "Saved misses_until cursor, or an ISO time; empty for 30 days") = "",
    unattended: _arg(bool, "Nobody is watching: never ask, record questions instead") = False,
    folder: _arg(str, "Working pages folder; rules always live at curator/rules") = "curator",
    brain: _arg(str | None, "Brain folder; defaults to the first brain") = None,
) -> dict:
    """The curator's rules and today's queue: entries past their review date, questions
    the brain could not answer, near-copies, long memories, the inbox and this week's
    journal. Run it when the person asks to tidy the brain, or when brain_start says it
    is nearly full or a tidy is due.
    Run it too when they hand you a meeting transcript to work into the brain: the
    steps say how to quote who said what, and when, as the source."""
    b, folder = _working(folder, brain)
    out = store.curate(b["id"], misses_since or None, unattended, folder, _by(), stamp=not _read_key())
    out["steps"] = [_prose(b, step, folder) for step in out["steps"]]
    answer = _place(b, out)
    _read(b, "curate")
    return answer


@_tool("A link to forget something", read_only=True, app="brain")
def brain_forget_link(
    kind: _arg(str, "'memory' or 'page'"),
    id: _arg(int, "The memory's or page's id"),
) -> dict:
    """You cannot forget anything: only the person can, for good, in Common Brain.
    When they ask you to forget something, give them this link; it opens the item
    and asks them to confirm."""
    b = _item(kind, id)
    item = store.get_memory(b["id"], id) if kind == "memory" else store.get_page(b["id"], id)
    base = settings.app_url("brain")
    _read(b, "get", kind, id, item.get("path", ""))  # `what` is the memory's text or the page's title
    return {
        "link": store.forget_link(base, kind, id) + f"?brain={b['id']}",
        "what": item.get("text") or item.get("title"),
        "say": "Open this link to forget it for good. Only you can do that.",
    }


@_tool("Evaluate the brain's search", read_only=False, app="brain")
def brain_eval(
    folder: _arg(str, "The folder holding golden and scorecard pages") = "curator",
    brain: _arg(str | None, "Brain folder; defaults to the first brain") = None,
) -> dict:
    """Run golden probe searches and append the score and failures to the scorecard.
    Golden lines: - <id>: <query> => <expected>; <expected>. Every expected string
    must occur in a top-10 result's path or title. No search miss is logged."""
    b, folder = _working(folder, brain)
    golden = store.get_page(b["id"], path=f"{store.path_of(folder)}/golden")
    out = store.evaluate(b["id"], folder, _by())
    answer = _place(b, out)
    _read(b, "get", "page", golden["id"], golden["path"])  # `failures` are ids written on the golden page
    return answer


@_tool("A link to export the brain", read_only=True, app="brain")
def brain_export_link(brain: _arg(str | None, "Brain folder; defaults to the first brain") = None) -> dict:
    """Open Export in the signed-in app, for a full snapshot or changes since a date.
    The link grants no access; file bytes are downloaded separately."""
    b = _select(brain)
    base = settings.app_url("brain")
    return {
        "link": f"{base}/app/connect/export?brain={b['id']}",
        "say": "Open Export in Common Brain, signed in to the account you want to download.",
    }


@_tool("Name and set up a brain", read_only=False, app="brain")
def brain_setup(
    name: _arg(str, "The name confirmed with the person"),
    description: _arg(str, "One paragraph describing what belongs here"),
    rules: _arg(list[str], "Two to four rules confirmed with the person"),
    brain: _arg(str | None, "Brain folder; defaults to the first brain") = None,
) -> dict:
    """The main agent link may name an unsettled brain once, with the person's agreement."""
    if _key.get() is not None:
        raise ValidationError("Only the main agent link can set up a brain.")
    b = _select(brain)
    return store.setup(b["id"], name, description, rules, _by())


def _entry(ref: str) -> tuple[dict, str, int]:
    if re.fullmatch(r"memory:[0-9]+", ref):
        ident = int(ref.split(":")[1])
        return _item("memory", ident), "memory", ident
    b, path = _split(ref)
    return b, "page", store.get_page(b["id"], path=path)["id"]


@_tool("Flag a disagreement", read_only=False, app="brain")
def brain_contradiction_flag(
    a: _arg(str, "An entry: memory:<id>, or a page path like people/maya"),
    b: _arg(str, "An entry: memory:<id>, or a page path like people/maya"),
    note: _arg(str, "One sentence saying what disagrees (up to 500 characters)"),
) -> dict:
    """Two entries say different things: do not pick one and do not merge them;
    flag the pair. Both stay as they are, and every AI's brain_start shows the pair
    until the person says which is right."""
    brain, kind_a, id_a = _entry(a)
    other, kind_b, id_b = _entry(b)
    # simplification: a pair lives in one brain; a disagreement across brains is refused,
    # since each brain has its own rules.
    if brain["id"] != other["id"]:
        raise ValidationError("Both entries must be in the same brain.")
    out = _place(brain, store.flag_contradiction(brain["id"], (kind_a, id_a), (kind_b, id_b), note, by=_by()))
    _read(brain, "curate")  # the pair carries both entries: a piece of the tidy-up queue
    return out


@_tool("Settle a disagreement", read_only=False, app="brain")
def brain_contradiction_settle(
    id: _arg(int, "The open pair's id from brain_start or brain_curate"),
    keep: _arg(str, "'a' or 'b' keeps that side and archives the other; 'both' closes the pair"),
    answer: _arg(str, "The person's answer (up to 500 characters)") = "",
) -> dict:
    """Call only with the person's own answer about an open pair: keep 'a' or 'b'
    archives the other entry (history says what replaced it; a locked memory is
    the person's to change in Common Brain). 'both' closes the pair without
    changing either (not a real disagreement, or already corrected with the normal tools)."""
    carried = _scope()
    row = db.get_db().execute("SELECT brain_id FROM brain_contradictions WHERE id = ?", (id,)).fetchone()
    if row:
        for b in carried:
            if row["brain_id"] == b["id"]:
                out = _place(b, _plain(store.settle_contradiction, b["id"], id, keep, by=_by(), answer=answer))
                _read(b, "curate")  # as brain_contradiction_flag
                return out
    raise NotFoundError("Contradiction not found")
