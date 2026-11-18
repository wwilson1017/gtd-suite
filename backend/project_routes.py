"""Projects GTD as Basecamp — the web app's API for everything in a project but
its card table (recordings.py), and the account's people (people.py). Mounted
on /api/app beside board_routes, under the same rules: a signed-in browser on
the list it names in X-List (router.active_owner), same-origin non-GETs,
no-store, no DELETE routes (archive, trash and "remove" are statuses).

    GET  /home                          Home: projects, latest activity, my assignments
    GET  /projects/sample  POST …       the sample projects: their state; seed them, turn them off or on
    GET  /people   POST /people         the account's people; add someone by name
    PUT  /people/{id}                   rename, retitle, recolour, archive
    GET  /projects/{id}                 a project's page: dock and tool previews
    PUT  /projects/{id}/dock            its tools: order, names, on or off
    GET  /projects/{id}/items?type=     its messages, to-do lists, … (status, parent_id, sort)
    GET  /projects/{id}/todos           its To-dos whole: loose to-dos, lists, groups, to-dos
    POST /projects/{id}/items           a new item of a type
    GET  /items/{id}                    one item's page: it, its breadcrumb, children, comments
    PUT  /items/{id}                    edit, archive, trash, restore, post a draft
    POST /items/{id}/complete           check off a to-do or subtask, or re-open it
    POST /items/{id}/move               reorder, or move under another parent or project
    POST /items/{id}/comments           comment on it
    POST /items/{id}/boosts             boost it
    GET  /cards/{id}/thread             a card's comments, boosts and subtasks
    POST /cards/{id}/comments           comment on a card
    POST /cards/{id}/boosts             boost a card
    POST /boosts/{id}/remove            take a boost back
    GET  /bookmarks   POST /bookmarks   My Bookmarks; bookmark or un-bookmark
    GET  /activity                      the trail (project_id, person_id, before)
    GET  /assignments                   open to-dos and cards assigned to someone (me by default), and
                                        where they were @mentioned in the last two weeks
    GET  /inbox   GET /inbox/count      New for you: bubbled up, unread, previous, due
    POST /inbox/read  /inbox/read-all   mark one item read or unread; mark everything read
    POST /inbox/bubble-up               bring an item back later (or take that off)
    GET  /inbox/mute   POST /inbox/mute "Don't notify me" on an item, a card or a project: read it, set it
    GET  /up-next   PUT /up-next        My Tasks' private Up Next order
    GET  /drafts    GET /my-boosts      My Drafts; boosts on what I wrote
    GET  /projects/{id}/docs            Docs & Files: one folder's folders, documents and links
    GET  /projects/{id}/calendar        a project's events and due work, start to end
    GET  /calendar                      every project's, the same way
    GET  /items/{id}/answers            a check-in's answers grouped by day (person_id)
    GET  /checkins/due                  the check-ins I am asked today and have not answered
    GET  /lineup                        projects with dates over a window of weeks
    GET  /projects/{id}/hill  POST …    a project's Hill Chart; move lists on it (the person only)
    GET  /projects/{id}/needle          the Needle's history (set it: POST items, type needle)
    GET  /projects/{id}/put-away        what is archived and in the trash, with archived cards
    GET  /everything?kind=              Everything: messages, docs, tasks, comments, check-ins
    GET  /reports/…                     overdue, upcoming, unassigned, progress, person/{id},
                                        mission-control, hilltop
    GET  /search?q=                     find text in every project (kind, project_id, person_id, since, sort)
    POST /items/{id}/copy               copy it (and what is under it) to a project or under a parent
    GET  /templates                     the project templates; POST /templates/{id}/use makes a project
    GET  /projects/{id}/chat            its chat lines (since: the last poll's latest; before: earlier)
    POST /items/{id}/shift              move every open date in a to-do list or group by some days
    POST /projects/{id}/todos/import    Markdown in, to-do lists, to-dos and subtasks out
"""

from fastapi import APIRouter, Depends, Query

from backend import boards, inbox, people, recordings, reports, samples, schedules, templates
from backend.models import (
    BookmarkSet,
    BoostCreate,
    BubbleUp,
    CommentCreate,
    Completion,
    DateShift,
    DockSet,
    HillSet,
    InboxItem,
    InboxMute,
    ItemCopy,
    ItemCreate,
    ItemMove,
    ItemUpdate,
    PersonCreate,
    PersonUpdate,
    SampleAction,
    TemplateUse,
    TodoImport,
    UpNext,
)
from backend.router import _call, active_owner

router = APIRouter(prefix="/api/app", dependencies=[Depends(active_owner)])


@router.get("/home")
def home(owner: int = Depends(active_owner)):
    return _call(recordings.home, owner)


# ── The sample projects (before /projects/{board_id}, which would take "sample" for an id) ──


@router.get("/projects/sample")
def sample_state(owner: int = Depends(active_owner)):
    return _call(samples.state, owner)


@router.post("/projects/sample")
def sample_action(body: SampleAction, owner: int = Depends(active_owner)):
    if body.action == "seed":
        return _call(samples.seed, owner)
    return _call(samples.turn, owner, body.action == "on")


# ── People ────────────────────────────────────────────────────────────────────


@router.get("/people")
def list_people(status: str = "active", owner: int = Depends(active_owner)):
    return {"people": _call(people.list_people, owner, status)}


@router.post("/people")
def add_person(body: PersonCreate, owner: int = Depends(active_owner)):
    return _call(people.add, owner, body.name, body.title)


@router.put("/people/{person_id}")
def update_person(person_id: int, body: PersonUpdate, owner: int = Depends(active_owner)):
    return _call(people.update, owner, person_id, body.model_dump(exclude_unset=True))


# ── Projects ──────────────────────────────────────────────────────────────────


@router.get("/projects/{board_id}")
def get_project(board_id: int, owner: int = Depends(active_owner)):
    return _call(recordings.project, owner, board_id)


@router.put("/projects/{board_id}/dock")
def set_dock(board_id: int, body: DockSet, owner: int = Depends(active_owner)):
    return {"dock": _call(recordings.set_dock, owner, board_id, body.dock)}


@router.get("/projects/{board_id}/items")
def list_items(
    board_id: int,
    type: str,
    status: str = "active",
    parent_id: int | None = None,
    sort: str = "newest",
    owner: int = Depends(active_owner),
):
    return {"items": _call(recordings.list_items, owner, board_id, type, status, parent_id, sort)}


@router.get("/projects/{board_id}/todos")
def todoset(board_id: int, status: str = "active", owner: int = Depends(active_owner)):
    return _call(recordings.todoset, owner, board_id, status)


@router.post("/projects/{board_id}/items")
def create_item(board_id: int, body: ItemCreate, owner: int = Depends(active_owner)):
    fields = body.model_dump(exclude_unset=True)
    kind = fields.pop("type")
    place = {k: fields.pop(k, None) for k in ("parent_id", "card_id", "position")}
    return _call(
        recordings.create,
        owner,
        board_id,
        kind,
        fields,
        parent_id=place["parent_id"],
        card_id=place["card_id"],
        position=place["position"],
        source="ui",
    )


# ── Items ─────────────────────────────────────────────────────────────────────


@router.get("/items/{item_id}")
def get_item(item_id: int, owner: int = Depends(active_owner)):
    return _call(recordings.thread, owner, item_id)


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate, owner: int = Depends(active_owner)):
    """409 when ``version`` is given and the item has changed since."""
    fields = body.model_dump(exclude_unset=True)
    version = fields.pop("version", None)
    return _call(recordings.update, owner, item_id, fields, version)


@router.post("/items/{item_id}/complete")
def complete_item(item_id: int, body: Completion, owner: int = Depends(active_owner)):
    return _call(recordings.complete, owner, item_id, body.done)


@router.post("/items/{item_id}/move")
def move_item(item_id: int, body: ItemMove, owner: int = Depends(active_owner)):
    return _call(
        recordings.move,
        owner,
        item_id,
        parent_id=body.parent_id,
        board=body.project_id,
        position=body.position,
        before=body.before_id,
    )


@router.post("/items/{item_id}/comments")
def comment_item(item_id: int, body: CommentCreate, owner: int = Depends(active_owner)):
    return _call(recordings.comment, owner, body.body, rec_id=item_id)


@router.post("/items/{item_id}/boosts")
def boost_item(item_id: int, body: BoostCreate, owner: int = Depends(active_owner)):
    return _call(recordings.boost, owner, body.content, rec_id=item_id)


# ── Cards: their comments, boosts and subtasks ───────────────────────────────


@router.get("/cards/{card_id}/thread")
def card_thread(card_id: int, owner: int = Depends(active_owner)):
    return _call(recordings.card_thread, owner, card_id)


@router.post("/cards/{card_id}/comments")
def comment_card(card_id: int, body: CommentCreate, owner: int = Depends(active_owner)):
    return _call(recordings.comment, owner, body.body, card_id=card_id)


@router.post("/cards/{card_id}/boosts")
def boost_card(card_id: int, body: BoostCreate, owner: int = Depends(active_owner)):
    return _call(recordings.boost, owner, body.content, card_id=card_id)


@router.post("/boosts/{boost_id}/remove")
def remove_boost(boost_id: int, owner: int = Depends(active_owner)):
    return _call(recordings.unboost, owner, boost_id)


# ── Bookmarks, activity, assignments ─────────────────────────────────────────


@router.get("/bookmarks")
def list_bookmarks(owner: int = Depends(active_owner)):
    return {"bookmarks": _call(recordings.bookmarks, owner)}


@router.post("/bookmarks")
def set_bookmark(body: BookmarkSet, owner: int = Depends(active_owner)):
    return _call(
        recordings.bookmark, owner, body.on, rec_id=body.item_id, card_id=body.card_id, board_id=body.project_id
    )


@router.get("/activity")
def activity(
    project_id: int | None = None,
    person_id: int | None = None,
    item_id: int | None = None,
    before: int | None = Query(default=None, ge=0),
    owner: int = Depends(active_owner),
):
    return _call(recordings.activity, owner, board_id=project_id, person_id=person_id, rec_id=item_id, before=before)


@router.get("/assignments")
def assignments(person_id: int | None = None, owner: int = Depends(active_owner)):
    return {
        "todos": _call(recordings.assignments, owner, person_id),
        "cards": _call(boards.assigned_cards, owner, person_id),
        "mentions": _call(recordings.mentions_of, owner, person_id),
    }


# ── New for you, Up Next, My Drafts, My Boosts (inbox.py) ────────────────────


@router.get("/inbox")
def get_inbox(owner: int = Depends(active_owner)):
    return _call(inbox.sidebar, owner)


@router.get("/inbox/count")
def inbox_count(owner: int = Depends(active_owner)):
    return {"unread": _call(inbox.unread_count, owner)}


@router.post("/inbox/read")
def mark_read(body: InboxItem, owner: int = Depends(active_owner)):
    return _call(inbox.mark, owner, body.read, rec_id=body.item_id, card_id=body.card_id, board_id=body.project_id)


@router.post("/inbox/read-all")
def mark_all_read(owner: int = Depends(active_owner)):
    return _call(inbox.mark_all_read, owner)


@router.get("/inbox/mute")
def get_mute(
    item_id: int | None = None,
    card_id: int | None = None,
    project_id: int | None = None,
    owner: int = Depends(active_owner),
):
    return {"muted": _call(inbox.muted, owner, rec_id=item_id, card_id=card_id, board_id=project_id)}


@router.post("/inbox/mute")
def set_mute(body: InboxMute, owner: int = Depends(active_owner)):
    return _call(inbox.mute, owner, body.muted, rec_id=body.item_id, card_id=body.card_id, board_id=body.project_id)


@router.post("/inbox/bubble-up")
def bubble_up(body: BubbleUp, owner: int = Depends(active_owner)):
    return _call(inbox.bubble_up, owner, body.when, rec_id=body.item_id, card_id=body.card_id, board_id=body.project_id)


@router.get("/up-next")
def get_up_next(owner: int = Depends(active_owner)):
    return {"items": _call(inbox.up_next, owner)}


@router.put("/up-next")
def set_up_next(body: UpNext, owner: int = Depends(active_owner)):
    return {"items": _call(inbox.set_up_next, owner, body.items)}


@router.get("/drafts")
def my_drafts(owner: int = Depends(active_owner)):
    return {"items": _call(inbox.drafts, owner)}


@router.get("/my-boosts")
def my_boosts(owner: int = Depends(active_owner)):
    return {"boosts": _call(inbox.my_boosts, owner)}


# ── Docs & Files, Calendar, Check-ins, the Lineup ────────────────────────────


@router.get("/projects/{board_id}/docs")
def docs(
    board_id: int,
    folder_id: int | None = None,
    sort: str = "name",
    status: str = "active",
    owner: int = Depends(active_owner),
):
    return _call(recordings.folder, owner, board_id, folder_id, sort, status)


@router.get("/projects/{board_id}/calendar")
def project_calendar(board_id: int, start: str, end: str, include_due: bool = True, owner: int = Depends(active_owner)):
    return _call(schedules.calendar, owner, start, end, board_ref=board_id, include_due=include_due)


@router.get("/calendar")
def all_calendars(start: str, end: str, include_due: bool = True, owner: int = Depends(active_owner)):
    return _call(schedules.calendar, owner, start, end, include_due=include_due)


@router.get("/items/{item_id}/answers")
def answers(item_id: int, person_id: int | None = None, owner: int = Depends(active_owner)):
    return {"days": _call(schedules.answers, owner, item_id, person_id=person_id)}


@router.get("/checkins/due")
def checkins_due(owner: int = Depends(active_owner)):
    me = next((p for p in people.list_people(owner) if p["kind"] == "me"), None)
    return {"questions": _call(schedules.checkins_due, owner, me["id"] if me else None)}


@router.get("/lineup")
def lineup(start: str, end: str, owner: int = Depends(active_owner)):
    return {"projects": _call(schedules.lineup, owner, start, end)}


# ── Hill Charts, the Needle, the archive; Everything, Reports, search ─────────


@router.get("/projects/{board_id}/hill")
def hill(board_id: int, owner: int = Depends(active_owner)):
    return _call(recordings.hill_chart, owner, board_id)


@router.post("/projects/{board_id}/hill")
def set_hill(board_id: int, body: HillSet, owner: int = Depends(active_owner)):
    return _call(recordings.set_hill, owner, board_id, body.positions, body.note)


@router.get("/projects/{board_id}/needle")
def needle(board_id: int, owner: int = Depends(active_owner)):
    return {"needles": _call(recordings.needles, owner, board_id)}


@router.get("/projects/{board_id}/put-away")
def put_away(board_id: int, owner: int = Depends(active_owner)):
    return _call(recordings.put_away, owner, board_id)


@router.get("/everything")
def everything(
    kind: str = "messages", before: str | None = None, subtasks: bool = False, owner: int = Depends(active_owner)
):
    return _call(reports.everything, owner, kind, before=before, subtasks=subtasks)


@router.get("/reports/overdue")
def overdue(owner: int = Depends(active_owner)):
    return _call(reports.overdue, owner)


@router.get("/reports/upcoming")
def upcoming(days: int = 14, owner: int = Depends(active_owner)):
    return _call(reports.upcoming, owner, days)


@router.get("/reports/unassigned")
def unassigned(owner: int = Depends(active_owner)):
    return _call(reports.unassigned, owner)


@router.get("/reports/progress")
def progress(start: str, end: str, owner: int = Depends(active_owner)):
    return _call(reports.progress, owner, start, end)


@router.get("/reports/person/{person_id}")
def person_tasks(person_id: int, owner: int = Depends(active_owner)):
    return _call(reports.person_tasks, owner, person_id)


@router.get("/reports/mission-control")
def mission_control(owner: int = Depends(active_owner)):
    return _call(reports.mission_control, owner)


@router.get("/reports/hilltop")
def hilltop(owner: int = Depends(active_owner)):
    return _call(reports.hilltop, owner)


@router.get("/search")
def search(
    q: str = Query("", max_length=reports.MAX_QUERY),
    kind: str | None = None,
    project_id: int | None = None,
    person_id: int | None = None,
    since: str | None = None,
    sort: str = "best",
    owner: int = Depends(active_owner),
):
    return _call(reports.search, owner, q, kind=kind, board_id=project_id, person_id=person_id, since=since, sort=sort)


# ── Copies and templates ──────────────────────────────────────────────────────


@router.post("/items/{item_id}/copy")
def copy_item(item_id: int, body: ItemCopy, owner: int = Depends(active_owner)):
    return _call(recordings.copy, owner, item_id, board=body.project_id, parent_id=body.parent_id)


@router.get("/templates")
def list_templates(owner: int = Depends(active_owner)):
    return {"templates": _call(templates.templates, owner)}


@router.post("/templates/{board_id}/use")
def use_template(board_id: int, body: TemplateUse, owner: int = Depends(active_owner)):
    return _call(templates.make_project, owner, board_id, body.name, starts_on=body.starts_on)


@router.get("/projects/{board_id}/chat")
def project_chat(
    board_id: int, since: int | None = None, before: int | None = None, owner: int = Depends(active_owner)
):
    return _call(recordings.chat, owner, board_id, since=since, before=before)


@router.post("/items/{item_id}/shift")
def shift_dates(item_id: int, body: DateShift, owner: int = Depends(active_owner)):
    return _call(recordings.shift_dates, owner, item_id, body.days)


@router.post("/projects/{board_id}/todos/import")
def import_todos(board_id: int, body: TodoImport, owner: int = Depends(active_owner)):
    return _call(recordings.import_todos, owner, board_id, body.text, parent_id=body.parent_id)
