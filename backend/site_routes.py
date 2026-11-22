"""Simple Sites — the web app's API for pages and short links, under /api/app.

Same rules as router.build_router: a signed-in browser on the list it names in
X-List (router.active_owner), same-origin non-GETs, no-store. DELETE here is the
Sites delete exception in the app (stored pages cost money, and the
person decides); agents can only unpublish.

    GET    /sites[?kind=page|link]   the pages and links, newest change first, and the caps
    POST   /sites                    a new page
    POST   /sites/links              a new short link
    GET    /sites/{id}               one page (with its content) or link
    PUT    /sites/{id}               content, format, title and/or status, all or nothing
    DELETE /sites/{id}               gone for good
    GET    /sites/{id}/data           records newest first, before cursor
    DELETE /sites/{id}/data           clear records (the browser only)
"""

import contextlib
import secrets
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from starlette.background import BackgroundTask
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.routing import APIRoute

from backend import agent_cmd, sites, db, settings, objectstore, ratelimit
from backend.models import AppSwitch, SiteCreate, SiteLinkCreate, SiteUpdate
from backend.router import _NO_STORE, _call, active_owner

# A whole page as JSON, with room for escaping (as Agent Commands allows).
_MAX_BODY_BYTES = agent_cmd.MAX_BODY_BYTES


class _Capped(APIRoute):
    """Caps the body before FastAPI reads it (it reads the whole body before any
    dependency, the session check included, runs): by the declared size, then by
    the bytes as they arrive, which also covers a chunked body. The capped body is
    left where Starlette's Request.body() caches it, so FastAPI reads that."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def capped(request):
            declared = request.headers.get("content-length", "")
            too_big, body = declared.isdigit() and int(declared) > _MAX_BODY_BYTES, bytearray()
            if not too_big:
                async for chunk in request.stream():
                    body += chunk
                    if len(body) > _MAX_BODY_BYTES:
                        too_big = True
                        break
            if too_big:
                return JSONResponse(
                    {"detail": f"Too large: a request is at most {_MAX_BODY_BYTES // 2**20} MB."},
                    status_code=413,
                    headers=_NO_STORE,
                )
            request._body = bytes(body)
            return await handler(request)

        return capped


router = APIRouter(prefix="/api/app", route_class=_Capped, dependencies=[Depends(active_owner)])


@router.get("/sites")
def list_sites(
    kind: str | None = None, folder: str | None = None, q: str | None = None, owner: int = Depends(active_owner)
):
    return {
        "sites": _call(sites.list_sites, owner, kind, folder, q),
        "caps": sites.caps(owner),
        "folders": sites.folders(owner),
    }


@router.post("/sites")
def create_page(body: SiteCreate, owner: int = Depends(active_owner)):
    return _call(
        sites.publish, owner, body.content, body.format, body.title, body.name, note=body.note, folder=body.folder
    )


@router.post("/sites/links")
def create_link(body: SiteLinkCreate, owner: int = Depends(active_owner)):
    return _call(
        sites.shorten,
        owner,
        body.url,
        body.name,
        body.title,
        short_name=body.short_name,
        note=body.note,
        folder=body.folder,
    )


@router.put("/sites/own-host")
def own_host(body: AppSwitch, owner: int = Depends(active_owner)):
    with db.transaction() as conn:
        if (
            not body.on
            and conn.execute(
                "SELECT 1 FROM sites WHERE list_id = ? AND layout = 'files' AND status = 'published' LIMIT 1", (owner,)
            ).fetchone()
        ):
            return JSONResponse(
                {"error": "Unpublish your folder sites first: they only work at their own address."},
                status_code=409,
                headers=_NO_STORE,
            )
        conn.execute("UPDATE lists SET sites_own_host = ? WHERE id = ?", (body.on, owner))
    return {"sites_own_host": body.on}


@router.get("/sites/{site_id}")
def get_site(site_id: int, owner: int = Depends(active_owner)):
    return _call(sites.get_site, owner, site_id)


@router.put("/sites/{site_id}")
def update_site(site_id: int, body: SiteUpdate, owner: int = Depends(active_owner)):
    try:
        return _call(
            sites.update,
            owner,
            site_id,
            content=body.content,
            fmt=body.format,
            title=body.title,
            status=body.status,
            password=body.password,
            note=body.note,
            folder=body.folder,
            data=body.data,
        )
    except sites.Busy:
        raise HTTPException(
            status_code=429,
            detail="Too many at once. Try again in a moment.",
            headers={**_NO_STORE, "Retry-After": "5"},
        )


@router.delete("/sites/{site_id}")
def delete_site(site_id: int, owner: int = Depends(active_owner)):
    _call(sites.delete_site, owner, site_id)
    return {"ok": True}


@router.get("/sites/{site_id}/data")
def read_data(site_id: int, before: int | None = None, limit: int = 100, owner: int = Depends(active_owner)):
    return _call(sites.read_data, owner, site_id, limit=limit, before=before, browser=True)


@router.delete("/sites/{site_id}/data")
def clear_data(site_id: int, owner: int = Depends(active_owner)):
    _call(sites.clear_data, owner, site_id)
    return {"ok": True}


_zip_slot = threading.Lock()


class _ZipResponse(FileResponse):
    """The slot belongs to the temp file, through download, cancellation and removal."""

    def __init__(self, path: str, filename: str):
        self._removed = False
        super().__init__(
            path,
            media_type="application/zip",
            filename=filename,
            headers=_NO_STORE,
            background=BackgroundTask(self.remove),
        )

    def remove(self):
        if not self._removed:
            Path(self.path).unlink(missing_ok=True)
            self._removed = True
            _zip_slot.release()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.remove()


def _zip(list_id: int, site_id: int) -> _ZipResponse:
    if not _zip_slot.acquire(blocking=False):
        raise HTTPException(429, "Another zip is downloading. Try again shortly.", headers=_NO_STORE)
    path = None
    handed_over = False
    try:
        with db.transaction() as conn:
            row = sites._row(conn, list_id, site_id, "page")
            manifest = sites.file_manifest(conn, list_id, site_id) if row["layout"] == "files" else []
            body = sites.render(row).encode() if row["layout"] == "body" else None
            if any(not f["object_key"] for f in manifest):
                raise sites.ValidationError("Some file bytes are unavailable")
            if body is None and not settings.files_s3():
                raise sites.ValidationError("Files are off on this server")
        size = len(body) if body is not None else sum(f["bytes"] for f in manifest)
        # ZIP headers and names also take room. The slot reserves this space through removal.
        needed = size + 4096 * max(1, len(manifest))
        directory = db.db_path().parent
        if shutil.disk_usage(directory).free - needed < 2_000_000_000:
            raise HTTPException(503, "Not enough free space to build a zip. Try again later.", headers=_NO_STORE)
        with tempfile.NamedTemporaryFile(prefix="site-zip-", suffix=".zip", dir=directory, delete=False) as temp:
            path = temp.name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            if body is not None:
                archive.writestr("index.html", body)
            for file in manifest:
                with archive.open(file["path"], "w", force_zip64=True) as output:
                    with contextlib.closing(objectstore.stream(file["object_key"])) as chunks:
                        read = 0
                        for chunk in chunks:
                            read += len(chunk)
                            if read > file["bytes"]:
                                raise objectstore.StoreError("The file store returned an incorrect size")
                            output.write(chunk)
                        if read != file["bytes"]:
                            raise objectstore.StoreError("The file store returned an incorrect size")
        response = _ZipResponse(path, f"site-{site_id}.zip")
        handed_over = True
        return response
    finally:
        if not handed_over:
            if path is not None:
                Path(path).unlink(missing_ok=True)
            _zip_slot.release()


# A one-use, one-minute ticket, so the browser streams the zip to disk itself instead of
# holding up to 1 GB in a Blob. The ticket is the whole credential and only names one zip.
# simplification: tickets live in memory (one worker); a restart drops unredeemed ones.
_ZIP_TICKET_SECONDS = 60
_zip_tickets: dict[str, tuple[int, int, float]] = {}
_zip_tickets_lock = threading.Lock()


@router.post("/sites/{site_id}/zip-link")
def zip_link(site_id: int, request: Request, owner: int = Depends(active_owner)):
    _call(sites.get_site, owner, site_id)  # 404 for another account's id, before any ticket
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _zip_tickets_lock:
        for key in [k for k, (_, _, until) in _zip_tickets.items() if until < now]:
            del _zip_tickets[key]
        _zip_tickets[token] = (owner, site_id, now + _ZIP_TICKET_SECONDS)
    return JSONResponse({"url": f"{settings.base_url(request)}/api/zip/{token}"}, headers=_NO_STORE)


zip_router = APIRouter(prefix="/api")


@zip_router.get("/zip/{token}")
def download_zip(token: str, request: Request):
    with _zip_tickets_lock:
        ticket = _zip_tickets.pop(token, None)
    if ticket is None or ticket[2] < time.monotonic():
        raise HTTPException(ratelimit.wrong_token_status(request), "This download link has expired.", headers=_NO_STORE)
    owner, site_id, _ = ticket
    return _call(_zip, owner, site_id)
