"""Notes GTD — the web app's notes API, under /api/app beside the todo app's.

Same rules as router.build_router: a signed-in browser on the list it names in
X-List (router.active_owner), same-origin non-GETs, no-store, no DELETE routes.

    GET  /notes[?q=&tag=&status=&limit=&offset=]   whole notes, pinned first
    POST /notes                                     a new note
    GET  /notes/tags                                the active notes' tags, with counts
    GET  /notes/{id}                                one note
    PUT  /notes/{id}                                edit, pin, colour, archive / restore;
                                                    title or body needs `version` (409 if stale)
"""

from fastapi import APIRouter, Depends, Query

from backend import notes
from backend.models import NoteCreate, NoteUpdate
from backend.router import _call, active_owner

router = APIRouter(prefix="/api/app", dependencies=[Depends(active_owner)])


@router.get("/notes")
def search_notes(
    q: str = "",
    tag: str = "",
    status: str = "active",
    limit: int = Query(default=100, ge=1, le=notes.PAGE),
    offset: int = Query(default=0, ge=0),
    owner: int = Depends(active_owner),
):
    return _call(notes.search, owner, q, tag, status, limit, offset)


@router.post("/notes")
def create_note(body: NoteCreate, owner: int = Depends(active_owner)):
    return _call(notes.create, owner, body.title, body.body, color=body.color, pinned=body.pinned)


@router.get("/notes/tags")
def note_tags(owner: int = Depends(active_owner)):
    return {"tags": _call(notes.tag_counts, owner)}


@router.get("/notes/{note_id}")
def get_note(note_id: int, owner: int = Depends(active_owner)):
    return _call(notes.get, owner, note_id)


@router.put("/notes/{note_id}")
def update_note(note_id: int, body: NoteUpdate, owner: int = Depends(active_owner)):
    fields = body.model_dump(exclude_unset=True)
    version = fields.pop("version", None)
    return _call(notes.update, owner, note_id, fields, version)
