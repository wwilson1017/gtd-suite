"""todo-gtd — the app. Run as exactly ONE worker (see db.py):

uvicorn backend.main:app --workers 1
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from backend.plans import extension
from backend import (
    api_v1,
    apps,
    automation,
    backup,
    cleanup,
    common,
    connect,
    db,
    files,
    lifecycle,
    logscrub,
    mcp_server,
    pages,
    readlog,
    recordings,
    sessions,
    settings,
    signin,
    site_host,
    sites,
    sites_agent,  # noqa: F401 (registers Simple Sites on the agent link)
)
from backend import notes_agent  # noqa: F401 (registers Notes GTD on the agent link)
from backend import brain_agent  # noqa: F401 (registers Common Brain on the agent link)
from backend import projects_agent  # noqa: F401 (registers Projects GTD's Basecamp tools)
from backend.board_routes import router as board_router
from backend.project_routes import router as project_router
from backend.site_routes import router as site_router, zip_router as site_zip_router
from backend.note_routes import router as note_router
from backend.brain_routes import router as brain_router
from backend.router import router

logscrub.install()
logger = logging.getLogger(__name__)

_DAILY_SECONDS = 24 * 3600


def _expire() -> None:
    """Sessions idle for a year, sign-in links past their hour, expired connect codes, and
    read-log rows past 90 days (readlog.py)."""
    try:
        now = common.utcnow()
        dropped = sessions.expire(now) + signin.expire(now) + connect.expire(now) + readlog.expire(now)
    except Exception:
        logger.exception(
            "Expiring old sessions, sign-in links, connect codes and read-log rows failed; skipped until the next run"
        )
        return
    if dropped:
        logger.info("Expired %d session(s), sign-in link(s), connect code(s) and read-log row(s)", dropped)


def _cleanup() -> None:
    try:
        deleted = cleanup.delete_unused_lists()
    except Exception:
        logger.exception("Cleanup of unused lists failed; skipped until the next run")
        return
    if deleted:
        logger.info("Deleted %d list(s) that were never used", deleted)


def _sweep_files() -> None:
    try:
        gone = files.sweep()
    except Exception:
        logger.exception("The sweep of stored files failed; skipped until the next run")
        return
    if gone:
        logger.info("Deleted the bytes of %d unreferenced or abandoned file(s)", gone)


def _reconcile_sites() -> None:
    try:
        sites.reconcile_blobs()
    except Exception:
        logger.exception("Sites object reconciliation failed; the next daily run tries again")


def _maintain_sites() -> None:
    try:
        sites.expire_sites()
        sites.short_name_grace()
    except Exception:
        logger.exception("Sites expiry and short-name maintenance failed; the next daily run tries again")


async def _maintain() -> None:
    """Snapshot every interval, then sweep Common Brain's unfinished and forgotten
    files (files.sweep); once a day, expire old sessions and sign-in links, and delete
    lists nobody ever used.

    The cleanup runs only with open signup: a one-list server's list is its
    whole point, and deleting it while empty would let a stranger claim the
    deployment. Sleeps first, so a crash loop cannot fill the volume with snapshots."""
    last_daily = None
    while True:
        await asyncio.sleep(settings.snapshot_interval())
        await asyncio.to_thread(backup.snapshot)
        await asyncio.to_thread(backup.push)
        await asyncio.to_thread(_sweep_files)
        if last_daily is None or time.monotonic() - last_daily >= _DAILY_SECONDS:
            last_daily = time.monotonic()
            await asyncio.to_thread(_expire)
            await asyncio.to_thread(_reconcile_sites)
            await asyncio.to_thread(_maintain_sites)
            if settings.open_signup():
                await asyncio.to_thread(_cleanup)


async def _tick() -> None:
    """Every minute: post the drafts scheduled for now (recordings.publish_scheduled),
    run the due-date and scheduled automation rules (automation.due_tick,
    automation.scheduled_tick), and write the Sites views counted (sites.flush_views).
    A failure is logged and the next minute tries again."""
    while True:
        await asyncio.sleep(60)
        for job, did in (
            (recordings.publish_scheduled, "Posted %d scheduled message(s)"),
            (automation.due_tick, "Due-date rules acted on %d card(s)"),
            (automation.scheduled_tick, "Scheduled rules acted on %d card(s)"),
            (sites.flush_views, ""),
        ):  # every minute that has views: not logged
            try:
                n = await asyncio.to_thread(job)
                if n and did:
                    logger.info(did, n)
            except Exception:
                logger.exception("The minute's %s failed", job.__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # raises, with what to do, when DATA_DIR is not writable
    if settings.open_signup() and not lifecycle.enabled():
        logger.warning(
            "Open signup without mail: no email can be confirmed, so lists keep the "
            "small limits, never age out, and cannot be signed in to by email"
        )
    task = asyncio.create_task(_maintain())
    tick = asyncio.create_task(_tick())
    sweep = asyncio.create_task(extension.maintain())
    # The MCP app's own lifespan starts its session manager; without it every
    # MCP request is a 500.
    async with mcp_server.mcp_app.lifespan(app):
        yield
    for t in (task, tick, sweep):
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t
    db.close_db()


class _AppPrefix:
    """Select path-based apps only on the main host; carry the origin to workers.
    An app is path-based when it has no host of its own, or when that host is an
    old address (settings.old_url)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        # The request's own origin stands in for a main address only on the main host.
        main = settings.configured_base_url() or (str(request.base_url) if settings.on_main_host(request) else "")
        origin = urlsplit(main)
        token = settings._origin.set(f"{origin.scheme}://{origin.netloc}" if main else "")
        try:
            key, _, rest = scope["path"][1:].partition("/")
            if (
                key in apps.APPS
                and key != apps.ANCHOR
                and (not settings.app_base_url(key) or settings.old_url(key))
                and settings.on_main_host(request)
            ):
                parts = rest.split("/")
                if parts[0] in ("link", "mcp") or (len(parts) > 1 and parts[1] == "mcp"):
                    return await PlainTextResponse("Not found", status_code=404, headers=pages.PAGE_HEADERS)(
                        scope, receive, send
                    )
                scope = dict(scope, path="/" + rest, app_prefix="/" + key)
                if scope.get("raw_path"):  # optional in ASGI; the prefix is plain ASCII, so the same cut fits
                    scope["raw_path"] = scope["raw_path"][len(key) + 1 :] or b"/"
                send = self._keep_prefix(send, "/" + key, "/" + rest)
            await self.app(scope, receive, send)
        finally:
            settings._origin.reset(token)

    @staticmethod
    def _keep_prefix(send, prefix: str, path: str):
        """Starlette's trailing-slash redirect is built from the path the routes saw, which
        has lost the prefix: put it back, or /notes/app/ would land in the anchor app."""

        async def resend(message):
            if message["type"] == "http.response.start" and message["status"] in (307, 308):
                headers = MutableHeaders(raw=message["headers"])
                to = urlsplit(headers.get("location", ""))
                if to.path != path and to.path.rstrip("/") == path.rstrip("/"):
                    headers["location"] = to._replace(path=prefix + to.path).geturl()
            await send(message)

        return resend


class _ShortHost:
    """SITES_SHORT_URL's host serves page and link addresses, page data and unlock,
    nothing else: any other GET or HEAD goes to the same path on Sites' own address, and
    anything else is a 404. So the app, the API, the agent link and sign-in never answer
    there, and the only cookie it ever sets is a page's pass."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and settings.on_short_host(Request(scope)):
            parts, method = scope["path"].split("/"), scope["method"]
            served = (
                parts[0] == ""
                and sites.ADDRESS_RE.fullmatch(parts[1])
                and (
                    (len(parts) == 2 and method in ("GET", "HEAD"))
                    or (parts[2:] == ["unlock"] and method == "POST")
                    or (parts[2:] == ["data"] and method in ("GET", "POST", "OPTIONS"))
                )
            )
            if not served:
                if method in ("GET", "HEAD"):
                    if len(parts) == 2 and not sites.ADDRESS_RE.fullmatch(parts[1]):
                        row = await asyncio.to_thread(sites.lookup_short, parts[1])
                        if row is not None:
                            if method == "GET":
                                sites.count_view(row["id"])
                            res = RedirectResponse(row["target"], status_code=302, headers=pages.PAGE_HEADERS)
                            return await res(scope, receive, send)
                    raw = scope.get("raw_path") or scope["path"].encode()
                    target = settings.app_base_url("sites") + raw.decode("latin-1")
                    if scope.get("query_string"):
                        target += "?" + scope["query_string"].decode("latin-1")
                    res = RedirectResponse(target, status_code=302, headers=pages.PAGE_HEADERS)
                else:
                    res = PlainTextResponse("Not found", status_code=404, headers=pages.PAGE_HEADERS)
                return await res(scope, receive, send)
        await self.app(scope, receive, send)


app = FastAPI(title="todo-gtd", lifespan=lifespan)
app.add_middleware(_AppPrefix)
app.add_middleware(_ShortHost)
app.add_middleware(site_host.SiteHost)
app.include_router(router)
app.include_router(board_router)
app.include_router(project_router)
app.include_router(site_router)
app.include_router(site_zip_router)
app.include_router(note_router)
app.include_router(brain_router)
# The REST API for program keys; its refusals answer {error}.
app.include_router(api_v1.router)
app.add_exception_handler(api_v1.Refused, api_v1.refused)
# The agent link (/link/<token>, /mcp/<token>, and /mcp with a bearer header) and the 404s for
# every sign-in discovery path.
app.router.routes += mcp_server.routes


@app.get("/healthz", include_in_schema=False)
def healthz():
    """For the platform's health check: the process is up and the database answers."""
    db.get_db().execute("SELECT 1").fetchone()
    return {"ok": True}


# The frontend build's hashed bundles. Skipped in a tree with no build, which
# still starts (the pages answer 503 with how to build it).
_assets = pages.STATIC_DIR / "assets"
if _assets.is_dir():
    app.mount("/assets", StaticFiles(directory=_assets))
# pages.router ends in the SPA catch-all, which would shadow any one-segment
# path registered after it.
app.include_router(pages.router)
# The agent link's other shape, /<token>/mcp. After everything, the pages
# included: it is two segments deep with a free first segment, and placed here it
# can only ever match an address nothing else answers.
app.router.routes.append(mcp_server.token_first_route)
