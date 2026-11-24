"""Common Brain — the web app's API, under /api/app beside the other apps'.

Same rules as router.build_router: a signed-in browser on the list it names in
X-List (router.active_owner), same-origin non-GETs, no-store. The one way to delete
real content anywhere in the suite is here: Forget, the person's own, in the
browser (brain.forget). The agent link has no route to it.

    GET  /brain                          memories, pages, folders, AIs, caps, the nudge
    GET  /brain/archive                  archived memories and pages
    GET  /brain/changes[?since=&limit=]  the what-changed feed
    GET  /brain/search?q=                memories and pages, best match first
    POST /brain/resolve                  where a page's [[links]] lead
    POST /brain/memories                 a new memory (every write says what it `removed`)
    GET  /brain/memories/{id}            one memory
    PUT  /brain/memories/{id}            text, lock, archive / bring back (409 if stale)
    POST /brain/memories/{id}/forget     forget it for good, with its history
    POST /brain/pages                    a new page
    GET  /brain/pages/{id}               one page
    PUT  /brain/pages/{id}               title, body, format, path, archive (409 if stale)
    POST /brain/pages/{id}/forget        forget it for good, with its history
    POST /brain/pages/{id}/share         publish it on Simple Sites
    GET  /brain/history/{kind}/{id}      every version
    POST /brain/restore                  bring a version back, as a new version
    POST /brain/import?dry_run=1         preview/import a raw zip (label, archive_missing)
    GET  /brain/export                   everything, as a zip of files
    GET  /brain/curator-skill            the curator skill for Claude Code and Codex
    GET  /brain/files                    Files: on or off, space used, the quota, the files
    POST /brain/files                    reserve one file, or {files: [up to 100]} (files.py)
    POST /brain/files/{id}/done          after the browser's PUT to the store: it goes live
    GET  /brain/files/{id}               302 to a 5-minute download
    PUT  /brain/files/{id}               archive / bring back
    POST /brain/files/{id}/forget        forget every version at its path, for good
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from backend import brain, brain_import, common, files
from backend.models import (
    BrainFileUpdate,
    BrainMemoryCreate,
    BrainMemoryUpdate,
    BrainPageCreate,
    BrainPageUpdate,
    BrainResolve,
    BrainRestore,
)
from backend.router import _NO_STORE, _call, active_owner


def current_brain(request: Request, owner: int = Depends(active_owner)) -> int:
    value = request.headers.get("X-Brain")
    selected = str(brain.first_brain(owner)) if value is None else value
    for row in brain.brains(owner):
        if str(row["id"]) == selected and row["status"] == "active":
            return row["id"]
    raise HTTPException(409, {"brain_gone": True}, headers=_NO_STORE)


router = APIRouter(prefix="/api/app/brain", dependencies=[Depends(current_brain)])


@router.get("")
def overview(brain_id: int = Depends(current_brain)):
    return _call(brain.overview, brain_id)


@router.get("/archive")
def archived(brain_id: int = Depends(current_brain)):
    return _call(brain.archive_view, brain_id)


@router.get("/changes")
def changes(since: str = "", limit: int = Query(default=100, ge=1, le=500), brain_id: int = Depends(current_brain)):
    return {"changes": _call(brain.changes, brain_id, since or None, limit)}


@router.get("/search")
def search(q: str = Query(max_length=500), brain_id: int = Depends(current_brain)):
    return _call(brain.search, brain_id, q)


@router.post("/resolve")
def resolve(body: BrainResolve, brain_id: int = Depends(current_brain)):
    return {"links": _call(brain.resolve, brain_id, body.targets)}


@router.post("/memories")
def add_memory(body: BrainMemoryCreate, brain_id: int = Depends(current_brain)):
    added = _call(brain.remember, brain_id, [body.text])
    return {"memory": (added["added"] or [None])[0], "skipped": added["skipped"], "removed": added["removed"]}


@router.get("/memories/{memory_id}")
def get_memory(memory_id: int, brain_id: int = Depends(current_brain)):
    return _call(brain.get_memory, brain_id, memory_id)


@router.put("/memories/{memory_id}")
def update_memory(memory_id: int, body: BrainMemoryUpdate, brain_id: int = Depends(current_brain)):
    f = body.model_dump(exclude_unset=True)
    return _call(
        brain.update_memory,
        brain_id,
        memory_id,
        text=f.get("text"),
        locked=f.get("locked"),
        status=f.get("status"),
        version=f.get("version"),
        review_on=f.get("review_on"),
    )


@router.post("/memories/{memory_id}/forget")
def forget_memory(memory_id: int, brain_id: int = Depends(current_brain)):
    return _call(brain.forget, brain_id, "memory", memory_id)


@router.post("/pages")
def create_page(body: BrainPageCreate, brain_id: int = Depends(current_brain)):
    return _call(brain.write_page, brain_id, body.path, body.body, title=body.title or None, fmt=body.format, new=True)


@router.get("/pages/{page_id}")
def get_page(page_id: int, brain_id: int = Depends(current_brain)):
    return _call(brain.get_page, brain_id, page_id)


@router.put("/pages/{page_id}")
def update_page(page_id: int, body: BrainPageUpdate, brain_id: int = Depends(current_brain)):
    fields = body.model_dump(exclude_unset=True)
    version = fields.pop("version", None)
    return _call(brain.update_page, brain_id, page_id, fields, version)


@router.post("/pages/{page_id}/forget")
def forget_page(page_id: int, brain_id: int = Depends(current_brain)):
    return _call(brain.forget, brain_id, "page", page_id)


@router.post("/pages/{page_id}/share")
def share_page(page_id: int, brain_id: int = Depends(current_brain)):
    return _call(brain.share, brain_id, page_id)


@router.get("/history/{kind}/{item_id}")
def history(kind: str, item_id: int, brain_id: int = Depends(current_brain)):
    return {"versions": _call(brain.history, brain_id, kind, item_id)}


@router.post("/restore")
def restore(body: BrainRestore, brain_id: int = Depends(current_brain)):
    return _call(brain.restore, brain_id, body.kind, body.id, body.version)


@router.get("/export")
def export(since: str = "", brain_id: int = Depends(current_brain)):
    return Response(
        _call(brain.export_zip, brain_id, since or None),
        media_type="application/zip",
        headers={**_NO_STORE, "Content-Disposition": 'attachment; filename="common-brain.zip"'},
    )


@router.get("/curator-skill")
def curator_skill():
    return Response(
        brain.CURATOR_SKILL,
        media_type="text/markdown; charset=utf-8",
        headers={**_NO_STORE, "Content-Disposition": 'attachment; filename="SKILL.md"'},
    )


@router.get("/files")
def list_files(brain_id: int = Depends(current_brain)):
    return _call(files.overview, brain_id)


@router.post("/files")
def reserve_files(body: dict = Body(...), brain_id: int = Depends(current_brain)):
    return _call(files.reserve, brain_id, body["files"] if "files" in body else [body], browser=True)


@router.post("/files/{file_id}/done")
def finish_file(file_id: int, brain_id: int = Depends(current_brain)):
    return _call(files.done, brain_id, file_id)


@router.get("/files/{file_id}")
def download_file(file_id: int, brain_id: int = Depends(current_brain)):
    return RedirectResponse(_call(files.link, brain_id, file_id=file_id)["url"], 302, headers=_NO_STORE)


@router.put("/files/{file_id}")
def update_file(file_id: int, body: BrainFileUpdate, brain_id: int = Depends(current_brain)):
    return _call(files.set_status, brain_id, file_id, body.status)


@router.post("/files/{file_id}/forget")
def forget_file(file_id: int, brain_id: int = Depends(current_brain)):
    return _call(files.forget, brain_id, file_id)


@router.post("/import")
async def import_markdown(
    request: Request,
    dry_run: bool = False,
    label: str = "",
    archive_missing: bool = False,
    brain_id: int = Depends(current_brain),
):
    try:
        report = await brain_import.receive(
            request, brain_id, brain.YOU, dry_run=dry_run, label=label, archive_missing=archive_missing
        )
    except common.ConflictError as exc:
        raise HTTPException(409, str(exc), headers=_NO_STORE) from None
    except common.ValidationError as exc:
        raise HTTPException(400, str(exc), headers=_NO_STORE) from None
    return JSONResponse(report, headers=_NO_STORE)
