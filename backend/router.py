"""todo-gtd — HTTP API.

A browser is signed in to one list by a session cookie (sessions.py); everything
else is reached by a token in the path, where an unknown or rotated token is a
404, NEVER a 401 (AI clients treat a 401 as "start sign-in").

    GET  /api/app/session         the app's first call: which list this browser is in
    /api/app/…                    the whole app: todo/project/area CRUD and the weekly
                                  review stamp (build_router),
                                  the agent and capture links, the program keys (keys.py:
                                  list, make, revoke), name, time zone, and the
                                  account routes (email, sign-in link, apps on/off,
                                  restore, sign out)
    POST /api/c/{capture token}   write-only inbox drop
    POST /api/lists               create a list and sign this browser in to it
    GET  /api/config              what this server offers, and whether this browser is signed in
    POST /api/signin              mail sign-in links for an address's confirmed lists (always the same answer)
    POST /api/signin/{token}      redeem one: this browser is signed in
    POST /api/reset               self-host: replace every way in, by operator code

/api/app is the one place that answers 401 (no WWW-Authenticate): it is browser-only,
and its 401 sends the app to the home page. Every /api/app request except
/session must carry ``X-List`` with the list id /session named; any other value is
409 ``{list_changed}`` and the app reloads, so a sign-in completed in one tab can
never write into the list another tab is showing. Every non-GET there, and every
route that sets the cookie, must be same-origin (_same_origin). A list that is put
away (lifecycle.py) answers 403 ``{state}`` everywhere there but /session and the
account routes, which the put-away page uses.

The agent and capture links rotate independently and only from a signed-in
browser: their tokens resolve against their own columns and cannot reach link
management. There are no DELETE routes here; archiving is status 'dropped' (Simple
Sites' one delete, of a page or link, is in site_routes.py).

The CRUD lives in ``build_router(owner_dep)``, whose dependency returns the
list id; every handler is list-scoped through it. Handlers are plain ``def`` so
FastAPI runs the blocking SQLite work in its threadpool.
"""

import asyncio
import json
import secrets
from typing import cast
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response

from backend.paid import routes as paid_routes
from backend.paid import plans
from backend.paid import billing
from backend import (
    apps,
    brain,
    common,
    connect,
    db,
    keys,
    lifecycle,
    lists,
    project_links,
    ratelimit,
    service,
    sessions,
    settings,
    signin,
    storage,
)
from backend.common import (
    MAX_TEXT_CHARS,
    ConflictError,
    NotFoundError,
    ValidationError,
    validate_email,
)
from backend.models import (
    AppSwitch,
    AreaCreate,
    AreaUpdate,
    ContextRename,
    ConnectApproval,
    ConnectPoll,
    ConnectStart,
    EmailUpdate,
    KeyCreate,
    BrainSettings,
    BrainGrant,
    BrainMove,
    ListCreate,
    NameUpdate,
    ProjectCreate,
    ProjectLinkCreate,
    ProjectUpdate,
    ResetRequest,
    SignInRequest,
    TodoBulkUpdate,
    TodoCreate,
    TodoUpdate,
    TzUpdate,
)
from backend.ratelimit import IPRateLimiter, client_ip

# On every response under /api/app and every one that carries a link — and on
# the refusals too: an HTTPException's response does not inherit headers set on
# the injected Response (see pages._not_found).
_NO_STORE = {"Cache-Control": "no-store"}


def _caps(verified: bool, hosted: bool, plan: str | None = None) -> dict:
    return dict(zip(("todos", "projects", "areas"), common.caps_for(verified, hosted, plan)))


_MAX_BODY_BYTES = 64 * 1024

create_limiter = IPRateLimiter(window=3600, max_hits=10)  # lists per IP
capture_ip_limiter = IPRateLimiter(window=60, max_hits=30)  # one NAT firing captures
capture_token_limiter = IPRateLimiter(window=60, max_hits=30)  # one link, however many IPs
# Writes per LIST (keyed on its id, so new links or sessions do not reset it), whoever sends them.
write_limiter = IPRateLimiter(window=60, max_hits=300)
recover_limiter = IPRateLimiter(window=900, max_hits=5)  # mail requests per IP: sign-in, confirm
reset_limiter = IPRateLimiter(window=3600, max_hits=5)  # reset-code attempts per IP

_base_url = settings.base_url


def _too_many() -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Too many requests. Please wait a moment and try again.",
        headers={**_NO_STORE, "Retry-After": "60"},
    )


def _wrong_token(request: Request) -> HTTPException:
    """The answer to a token that matched nothing: 404, or 429 once the address
    has sent too many. A VALID token never gets here, however many misses its
    address has made (ratelimit.bad_token_limiter)."""
    if ratelimit.wrong_token_status(request) == 429:
        return HTTPException(
            status_code=429, detail=ratelimit.TOO_MANY_WRONG_LINKS, headers={**_NO_STORE, "Retry-After": "600"}
        )
    return HTTPException(status_code=404, detail="Not found", headers=_NO_STORE)


def _call(fn, *args, **kwargs):
    """Run a service call, mapping domain errors to their HTTP shape."""
    try:
        return fn(*args, **kwargs)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e), headers=_NO_STORE)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Not found", headers=_NO_STORE)
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e), headers=_NO_STORE)
    except OverflowError:
        # sqlite3 refuses to bind an int beyond 64 bits; that is bad input, not a crash.
        raise HTTPException(status_code=400, detail="Number out of range", headers=_NO_STORE)


def _same_origin(request: Request) -> None:
    """403 unless the request came from this site's own pages. ``Sec-Fetch-Site``
    when the browser sends it (every current one does); otherwise ``Origin`` must
    be present and be this server's. Neither is a refusal: SameSite=Lax is no
    defence for redemption, which needs no cookie — a cross-site form POST with an
    attacker's link would sign the victim's browser in to the attacker's list."""
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        allowed = site == "same-origin"
    else:
        own = urlsplit(_base_url(request))
        allowed = request.headers.get("origin") == f"{own.scheme}://{own.netloc}"
    if not allowed:
        raise HTTPException(
            status_code=403, headers=_NO_STORE, detail="Refused: this request did not come from this site."
        )


def _signed_in(request: Request, response: Response, *, pinned: bool = True) -> int:
    """The list this browser's session cookie is signed in to, or 401. With
    ``pinned``, the request must name that list in ``X-List`` (409 otherwise).
    Non-GETs are same-origin only and count against the list's write limit.
    Never clears the cookie and never charges the wrong-token bucket: a stale
    cookie is an ordinary signed-out browser, not a guess."""
    session = sessions.resolve(request.cookies.get(sessions.COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Not signed in", headers=_NO_STORE)
    list_id = session["list_id"]
    if pinned and request.headers.get("x-list") != str(list_id):
        raise HTTPException(status_code=409, detail={"list_changed": True}, headers=_NO_STORE)
    if request.method != "GET":
        _same_origin(request)
        if not write_limiter.allow(str(list_id)):
            raise _too_many()
    response.headers.update(_NO_STORE)
    sessions.touch(session["token_hash"])
    return list_id


def session_owner(request: Request, response: Response) -> int:
    """S: a signed-in browser, on the list it names in X-List."""
    return _signed_in(request, response)


def _put_away(state: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"state": state}, headers=_NO_STORE)


def active_owner(owner: int = Depends(session_owner)) -> int:
    """A: S, on a list that is not put away (lifecycle.py), and the list counts
    as used. A put-away list is 403 {state} and NOT touched, so opening the app
    does not bring it back: the app shows the put-away page instead."""
    state = lifecycle.state(lists.get_list(owner))
    if state != "active":
        raise _put_away(state)
    lists.touch(owner)
    return owner


# ---------------------------------------------------------------------------
# CRUD factory. `owner_dep` returns the list id; every query is list-scoped
# through it. Mounted once, on /api/app with active_owner.
# ---------------------------------------------------------------------------


def build_router(owner_dep, *, prefix: str = "") -> APIRouter:
    r = APIRouter(prefix=prefix, dependencies=[Depends(owner_dep)])

    # ── Todos ──────────────────────────────────────────────────────────────────

    @r.get("/todos")
    def list_todos(
        status: str | None = None,
        project: str | None = None,
        context: str | None = None,
        tag: str | None = None,
        person: str | None = None,
        area: str | None = None,
        starred: bool | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
        search: str | None = None,
        limit: int = Query(default=200, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        include_deferred: bool = False,
        owner: int = Depends(owner_dep),
    ):
        todos = _call(
            service.list_todos,
            owner,
            status=status,
            project=project,
            context=context,
            tag=tag,
            person=person,
            area=area,
            starred=starred,
            due_before=due_before,
            due_after=due_after,
            search=search,
            limit=limit,
            offset=offset,
            include_deferred=include_deferred,
        )
        return {"todos": todos}

    @r.get("/today")
    def today(owner: int = Depends(owner_dep)):
        return {"todos": _call(service.today_view, owner)}

    @r.post("/todos")
    def create_todo(body: TodoCreate, owner: int = Depends(owner_dep)):
        return _call(
            service.create_todo,
            owner,
            body.title,
            notes=body.notes,
            project=body.project,
            project_id=body.project_id,
            area_id=body.area_id,
            context=body.context,
            tags=body.tags,
            people=body.people,
            status=body.status,
            star=body.star,
            due_date=body.due_date,
            revisit_on=body.revisit_on,
            repeat=body.repeat,
            auto_star_on_due=body.auto_star_on_due,
            source="ui",
        )

    @r.get("/todos/{todo_id}")
    def get_todo(todo_id: int, owner: int = Depends(owner_dep)):
        todo = _call(service.get_todo, owner, todo_id)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found", headers=_NO_STORE)
        return todo

    @r.put("/todos/{todo_id}")
    def update_todo(todo_id: int, body: TodoUpdate, owner: int = Depends(owner_dep)):
        # exclude_unset: only fields the client actually sent are updated, so
        # explicit nulls/empties clear values without clobbering the rest.
        todo = _call(service.update_todo, owner, todo_id, body.model_dump(exclude_unset=True))
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found", headers=_NO_STORE)
        return todo

    @r.post("/todos/bulk")
    def bulk_update(body: TodoBulkUpdate, owner: int = Depends(owner_dep)):
        return _call(service.bulk_update, owner, body.ids, body.fields)

    @r.post("/contexts/rename")
    def rename_context(body: ContextRename, owner: int = Depends(owner_dep)):
        """409 = the new name is already a context; resend with merge to confirm."""
        return _call(service.rename_context, owner, body.old, body.new, merge=body.merge)

    # ── Projects ───────────────────────────────────────────────────────────────

    @r.get("/projects")
    def list_projects(status: str | None = None, area: str | None = None, owner: int = Depends(owner_dep)):
        return {"projects": _call(service.list_projects, owner, status=status, area=area)}

    @r.post("/projects")
    def create_project(body: ProjectCreate, owner: int = Depends(owner_dep)):
        return _call(
            service.create_project,
            owner,
            body.name,
            notes=body.notes,
            status=body.status,
            purpose=body.purpose,
            outcome=body.outcome,
            area_id=body.area_id,
        )

    @r.put("/projects/{project_id}")
    def update_project(project_id: int, body: ProjectUpdate, owner: int = Depends(owner_dep)):
        project = _call(service.update_project, owner, project_id, body.model_dump(exclude_unset=True))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found", headers=_NO_STORE)
        return project

    # A project's home in Projects GTD (project_links.py). Not under /projects/…: both
    # apps have routes there.

    @r.get("/project-links")
    def list_project_links(owner: int = Depends(owner_dep)):
        return {"links": project_links.links(owner)}

    @r.post("/project-links")
    def create_project_link(body: ProjectLinkCreate, owner: int = Depends(owner_dep)):
        """The link, made now or already there: a repeated request makes nothing more."""
        return _call(project_links.promote, owner, body.project_id)

    # ── Areas of focus ─────────────────────────────────────────────────────────

    @r.get("/areas")
    def list_areas(status: str | None = None, owner: int = Depends(owner_dep)):
        return {"areas": _call(service.list_areas, owner, status=status)}

    @r.post("/areas")
    def create_area(body: AreaCreate, owner: int = Depends(owner_dep)):
        return _call(service.create_area, owner, body.name, notes=body.notes)

    @r.put("/areas/{area_id}")
    def update_area(area_id: int, body: AreaUpdate, owner: int = Depends(owner_dep)):
        area = _call(service.update_area, owner, area_id, body.model_dump(exclude_unset=True))
        if not area:
            raise HTTPException(status_code=404, detail="Area not found", headers=_NO_STORE)
        return area

    # ── Filters ────────────────────────────────────────────────────────────────

    @r.get("/filters")
    def get_filters(owner: int = Depends(owner_dep)):
        return service.get_filters(owner)

    # ── Weekly review ──────────────────────────────────────────────────────────
    # The Review page's "review due" line, and the one write that quiets it: the
    # same stamp an agent's todo_weekly_review leaves.

    @r.get("/review")
    def review_status(owner: int = Depends(owner_dep)):
        return lists.review_status(owner)

    @r.post("/review/done")
    def mark_review_done(owner: int = Depends(owner_dep)):
        lists.start_review(owner)
        return lists.review_status(owner)

    return r


router = APIRouter(prefix="/api")
router.include_router(build_router(active_owner, prefix="/app"))

# The agent and capture links, name and time zone. Every response carries a link
# or belongs to one; the owner dependency marks them all no-store.
links_router = APIRouter(prefix="/app", dependencies=[Depends(active_owner)])


def _capture_link(request: Request, token: str) -> dict:
    return {"url": f"{_base_url(request)}/c/{token}", "token": token}


def agent_url(request: Request, token: str) -> str:
    """The agent link — the ONE place the backend builds its address. The path
    names no protocol: an assistant handed a link with "mcp" in it reasons about
    MCP clients instead of opening it. The server also answers /mcp/<token> (the
    shape shown before 2026-10-11), /<token>/mcp and /mcp with a bearer header."""
    return f"{settings.app_url(apps.ANCHOR, request) if request.scope.get('app_prefix') else _base_url(request)}/link/{token}"


def _agent_link(request: Request, token: str) -> dict:
    return {"url": agent_url(request, token), "token": token}


@links_router.get("/agent-link")
def get_agent_link(request: Request, owner: int = Depends(active_owner)):
    return _agent_link(request, cast(dict, lists.get_list(owner))["agent_token"])


@links_router.post("/agent-link/rotate")
def rotate_agent_link(request: Request, owner: int = Depends(active_owner)):
    """A new agent link. Signed-in browsers are untouched; AI tools must be re-added."""
    return _agent_link(request, cast(str, lists.rotate_agent(owner)))


@links_router.get("/ai-tools")
def get_ai_tools(owner: int = Depends(active_owner)):
    """Which AI tools have called the account, read again by a page that is waiting for
    one to (the session answer carries the same list at page load)."""
    return {"ai_tools": lists.ai_tools(owner)}


@links_router.get("/capture-link")
def get_capture_link(request: Request, owner: int = Depends(active_owner)):
    return _capture_link(request, cast(dict, lists.get_list(owner))["capture_token"])


@links_router.post("/capture-link/rotate")
def rotate_capture_link(request: Request, owner: int = Depends(active_owner)):
    return _capture_link(request, cast(str, lists.rotate_capture(owner)))


@links_router.get("/name")
def get_name(owner: int = Depends(active_owner)):
    return {"name": cast(dict, lists.get_list(owner))["name"]}


@links_router.put("/name")
def set_name(body: NameUpdate, owner: int = Depends(active_owner)):
    """The list's optional name; it is read back with the filters payload."""
    return {"name": _call(lists.set_name, owner, body.name)}


@links_router.put("/tz")
def set_tz(body: TzUpdate, owner: int = Depends(active_owner)):
    """The zone "today" is computed in; it is read back with the filters payload."""
    return {"tz": _call(lists.set_tz, owner, body.tz)}


@links_router.get("/keys")
def list_keys(owner: int = Depends(active_owner)):
    """The program keys (keys.py), without the keys themselves."""
    return {"keys": keys.list_keys(owner)}


@links_router.post("/keys")
def create_key(body: KeyCreate, request: Request, owner: int = Depends(active_owner)):
    """A new program key. The answer carries the key itself, the only time it is shown."""
    made = _call(keys.create, owner, body.name, body.apps, body.access, body.folders, body.brains, body.kind)
    if body.kind == "link":
        made["link"] = agent_url(request, made["key"])
    return made


@links_router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: int, owner: int = Depends(active_owner)):
    _call(keys.revoke, owner, key_id)
    return {"ok": True}


@links_router.get("/brains")
def list_brains(owner: int = Depends(active_owner)):
    return {
        "brains": brain.brains(owner),
        "caps": brain.account_caps(owner),
        "link_brains": [b["id"] for b in brain.main_brains(owner)],
    }


@links_router.post("/brains")
def create_brain(body: BrainSettings, owner: int = Depends(active_owner)):
    return _call(brain.create_brain, owner, **body.model_dump())


@links_router.put("/brains/{brain_id}")
def update_brain(brain_id: int, body: BrainSettings, owner: int = Depends(active_owner)):
    return _call(brain.update_brain, owner, brain_id, **body.model_dump(exclude_unset=True))


@links_router.post("/brains/{brain_id}/archive")
def archive_brain(brain_id: int, owner: int = Depends(active_owner)):
    return _call(brain.brain_status, owner, brain_id, "archived")


@links_router.post("/brains/{brain_id}/restore")
def restore_brain(brain_id: int, owner: int = Depends(active_owner)):
    return _call(brain.brain_status, owner, brain_id, "active")


@links_router.put("/link-brains")
def link_brains(body: BrainGrant, owner: int = Depends(active_owner)):
    return {"brains": _call(brain.set_link_brains, owner, body.brains)}


@links_router.post("/brain/move")
def move_brain_item(body: BrainMove, owner: int = Depends(active_owner)):
    def move():
        with db.transaction() as conn:
            brain.grant_in(conn, owner, [body.to_brain])
            table = "brain_memories" if body.kind == "memory" else "brain_pages"
            item = conn.execute(f"SELECT 1 FROM {table} WHERE id = ? AND list_id = ?", (body.id, owner)).fetchone()
            if item is None:
                raise NotFoundError("Item not found")
            return brain.move_to_brain_in(
                conn, body.kind, body.id, body.to_brain, body.path, brain.YOU, body.expected_version
            )

    return _call(move)


router.include_router(links_router)

# The signed-in browser's own account: S, not A — these do not count as using the
# list, and they work on a put-away list (the put-away page uses email, restore
# and signout).
account_router = APIRouter(prefix="/app", dependencies=[Depends(session_owner)])


@account_router.put("/email")
def set_email(body: EmailUpdate, request: Request, background: BackgroundTasks, owner: int = Depends(session_owner)):
    """Set, change or clear ('') the list's email, all in one transaction. A new
    address is unconfirmed: the sign-in links already out are cancelled (this
    browser stays signed in) and, when mail is on, a confirmation link is minted
    for it. Saving the same unconfirmed address again is "Send again": the links
    already out stay, and one more is minted. Either way at most one mail per
    address per 15 minutes (signin.address_limiter), and the asking address shares
    the sign-in form's budget, so a list cannot mail address after address;
    ``sent`` says whether one is on its way. Only the send runs after the
    response, with the link already built."""
    email = _call(validate_email, body.email)
    token = None
    with db.transaction() as conn:
        if not email:
            paid_routes.require_email_in(conn, owner)
        stored, verified = lists.set_email_in(conn, owner, email)
        existing, taken = [], []
        if (
            stored
            and not verified
            and signin.available()
            and recover_limiter.allow(client_ip(request))
            and signin.confirm_limiter.allow(stored)
        ):
            # One account per address: when another list has it confirmed, the mail
            # leads back there instead (a disabled one holds its address too, but is
            # mailed nothing). The answer is the same either way, so it never says
            # whether the address has an account.
            taken = signin.confirmed_elsewhere_in(conn, stored, owner)
            existing = [
                (f"{_base_url(request)}/signin/{signin.issue_link_in(conn, row['id'], mailed_to=stored)[0]}", row)
                for row in taken
                if not row["disabled"]
            ]
            if not taken:
                token, _ = signin.issue_link_in(conn, owner, mailed_to=stored)
    if existing:
        assert stored is not None  # Existing-account links are issued only for a stored email.
        background.add_task(signin.send_existing, existing, stored, settings.app_for(request))
    elif token:
        assert stored is not None  # A confirmation token is issued only for a stored email.
        background.add_task(
            signin.send_verification, f"{_base_url(request)}/signin/{token}", stored, settings.app_for(request)
        )
    # Caps follow verification, so the page can show the right numbers without a reload.
    return {
        "email": stored,
        "verified": verified,
        "sent": bool(token or taken),
        "caps": _caps(verified, settings.open_signup(), plans.of(lists.get_list(owner))),
    }


@account_router.post("/restore")
def restore(owner: int = Depends(session_owner)):
    """The put-away page's "Bring it back": an archived list is used, so it is
    active again. A removed list is 403 {state}: its way back is a confirmed
    email (PUT /email, then the mailed link), which also keeps it for good."""
    if lifecycle.state(lists.get_list(owner)) == "removed":
        raise _put_away("removed")
    lists.touch(owner)
    return {"state": "active"}


@account_router.post("/signin-link")
def create_signin_link(request: Request, app: str | None = None, owner: int = Depends(session_owner)):
    """Connect's "Sign in on another device": a link (and so a QR code) that signs
    in whichever browser opens it and presses the button. Once, within the hour.
    With ``app`` (a key in apps.py), the link is on that app's
    address instead: the way from one app to another on the same account."""
    base = _base_url(request)
    if app is not None:
        base = settings.app_url(app, request) if app in apps.APPS else ""
        if not base:
            raise HTTPException(status_code=404, detail="Not found", headers=_NO_STORE)
    token, expires_at = signin.issue_link(owner)
    return {"url": f"{base}/signin/{token}", "expires_at": expires_at}


@account_router.put("/apps/{key}")
def switch_app(key: str, body: AppSwitch, owner: int = Depends(session_owner)):
    """Apps under Connect: turn one app on or off for the account. Off hides it
    from the agent link and the menus; its data stays, and it comes back as it was.
    An unknown app is a 404."""
    if not lists.served(key):
        raise HTTPException(status_code=404, detail="Not found", headers=_NO_STORE)
    with db.transaction() as conn:
        lists.set_app_in(conn, owner, key, body.on)
    return {"apps": lists.apps_on(owner)}


@account_router.post("/signout")
def sign_out(request: Request):
    """Sign this browser out. The cookie stays (see sessions.py) and now answers 401."""
    sessions.revoke(request.cookies.get(sessions.COOKIE))
    return {"ok": True}


@account_router.post("/signout-all")
def sign_out_everywhere(owner: int = Depends(session_owner)):
    """Sign every browser out of the list, this one included, and cancel its
    unspent sign-in links. The agent and capture links are untouched."""
    sessions.revoke_all(owner)
    return {"ok": True}


paid_routes.mount(router, account_router, session_owner, _base_url)
router.include_router(account_router)


@router.get("/app/session")
def get_session(request: Request, response: Response):
    """The app's first call, and the only /api/app route that needs no X-List:
    which list this browser is signed in to, and what the app should show for it.
    It answers in every list state: ``state`` other than active means the put-away
    page."""
    owner = _signed_in(request, response, pinned=False)
    row = lists.get_list(owner)
    assert row is not None  # The session owner has already been resolved.
    verified, hosted = row["email_verified_at"] is not None, settings.open_signup()
    plan = plans.of(row)
    return {
        "list_id": owner,
        "account_no": row["account_no"],
        "state": lifecycle.state(row),
        "email": row["email"],
        "verified": verified,
        "hosted": hosted,
        "mail": signin.available(),
        "caps": {
            **_caps(verified, hosted, plan),
            **brain.account_caps(owner),
            "storage": common.storage_quota_for(verified, hosted, plans.of(row)),
            "storage_used": storage.used(db.get_db(), owner),
        },
        "brains": [{k: b[k] for k in ("id", "name", "folder", "status")} for b in brain.brains(owner)],
        "apps": row["apps"],  # the apps turned on (lists.apps_on)
        "ai_tools": lists.ai_tools(owner),  # which AI tools have called: Settings › Connect your AI, the setup steps
        "plan": paid_routes.session_plan(row),
    }


# ── Public: what this server offers ───────────────────────────────────────────


@router.get("/config")
def get_config(request: Request, response: Response):
    """Lets the pages hide what the server cannot do. ``claimed``: this is a
    one-list server and its list exists, so there is nothing left to create.
    ``reset``: the operator has set a reset code for it. ``signed_in``: this
    browser has a live session."""
    open_signup = settings.open_signup()
    claimed = not open_signup and lists.any_list()
    response.headers.update(_NO_STORE)
    return {
        "mail": signin.available(),
        "open_signup": open_signup,
        "claimed": claimed,
        "reset": claimed and bool(settings.reset_code()),
        "signed_in": sessions.resolve(request.cookies.get(sessions.COOKIE)) is not None,
        "billing": billing.selling(),
        # This page's app, and every app's reachable address: the menus offer the way across.
        "app": settings.app_for(request),
        "apps": {
            key: {"title": app.title, "url": url}
            for key, app in apps.APPS.items()
            if (url := settings.app_url(key, request))
        },
        # On an app's old host: where it lives now ("" anywhere else). The page offers the way over.
        "moved": settings.moved_to(request),
        # Where Simple Sites hands its addresses out, when that is not its own host.
        "sites_short_host": urlsplit(settings.sites_short_url()).netloc,
    }


@router.post("/connect")
def start_connect(request: Request, response: Response, body: ConnectStart | None = None):
    """A device asks for a connection code (body ``{"client": "springform"}`` for a Springform
    install, else Simple Sites); the person approves it at ``url``, the device polls."""
    client = body.client if body else "sites"
    if not lists.served("sites"):
        raise HTTPException(404, "Not found", headers=_NO_STORE)
    limiter = ratelimit.springform_connect_limiter if client == "springform" else ratelimit.connect_limiter
    if not limiter.allow(client_ip(request)):
        raise HTTPException(
            429, "Too many connections. Try again in an hour.", headers={**_NO_STORE, "Retry-After": "3600"}
        )
    result = connect.start(client)
    response.headers.update(_NO_STORE)
    url = f"{settings.app_url('sites', request)}/connect?code={result['user_code']}"
    return {**result, "url": url + ("&client=springform" if client == "springform" else "")}


@router.post("/connect/poll")
def poll_connect(body: ConnectPoll, request: Request, response: Response):
    result = connect.poll(body.device_token)
    if result is None:
        raise _wrong_token(request)
    response.headers.update(_NO_STORE)
    if result["status"] == "approved":
        return {"status": "approved", "agent_url": agent_url(request, result["agent_token"])}
    return result


@router.post("/app/connect/{user_code}")
def approve_connect(user_code: str, body: ConnectApproval | None = None, owner: int = Depends(session_owner)):
    _call(connect.approve, owner, user_code, body.typed_code if body else None, body.client if body else "sites")
    return {"ok": True}


# ── Public: create a list ─────────────────────────────────────────────────────


@router.post("/lists")
def create_list(request: Request, response: Response, body: ListCreate | None = None):
    """Create a list and sign this browser in to it. The answer carries the
    agent link (the app shows it again in Settings › Connect your AI); the session is only in
    the cookie."""
    _same_origin(request)
    if sessions.resolve(request.cookies.get(sessions.COOKIE)) is not None:
        # One browser, one list: there is no chooser to switch between them.
        raise HTTPException(
            status_code=409,
            headers=_NO_STORE,
            detail=(
                "This browser is already signed in to a list. Sign out in "
                f"{apps.settings_page(settings.app_for(request))} to make another."
            ),
        )
    if not create_limiter.allow(client_ip(request)):
        raise _too_many()
    # Self-host: the first visitor claims the one list; the check is in the insert's transaction.
    body = body or ListCreate()
    created = _call(
        lists.create_list,
        body.tz,
        body.name,
        only_if_none=not settings.open_signup(),
        app=settings.app_for(request),
        connect=body.connect,
    )  # its starting apps follow the app it was made in (lists.create_list)
    if created is None:
        raise HTTPException(status_code=409, detail="This list is already set up.", headers=_NO_STORE)
    sessions.set_cookie(response, created["session_token"])
    response.headers.update(_NO_STORE)
    return {
        "agent_token": created["agent_token"],
        "agent_url": agent_url(request, created["agent_token"]),
        "tz": created["tz"],
        "name": created["name"],
    }


# ── Public: self-host reset ───────────────────────────────────────────────────


@router.post("/reset")
def reset_access(body: ResetRequest, request: Request, response: Response):
    """Take a one-list server back, for whoever knows RESET_CODE: every browser
    is signed out, sign-in links are cancelled, the email is cleared, the agent
    and capture links are replaced — and this browser is signed in. It keeps no
    state: the operator sets the variable, resets, and removes it. Does not exist
    (404) on an open-signup server or while the variable is unset."""
    code = settings.reset_code()
    if settings.open_signup() or not code:
        raise HTTPException(status_code=404, detail="Not found", headers=_NO_STORE)
    _same_origin(request)
    if not reset_limiter.allow(client_ip(request)):
        raise _too_many()
    if not secrets.compare_digest(body.code.encode(), code.encode()):
        raise HTTPException(status_code=403, detail="That reset code is not right.", headers=_NO_STORE)
    token = lists.reset_single()
    if token is None:
        raise HTTPException(status_code=404, detail="There is no single list to reset.", headers=_NO_STORE)
    sessions.set_cookie(response, token)
    response.headers.update(_NO_STORE)
    return {"ok": True}


# ── Public: sign in ───────────────────────────────────────────────────────────


@router.post("/signin")
def request_signin(body: SignInRequest, request: Request, background: BackgroundTasks):
    """Always the same answer: it never says whether a list uses the address.
    The lookup and the mail run after the response, so timing says nothing either."""
    if not signin.available():
        raise HTTPException(status_code=404, detail="Not found")
    if not recover_limiter.allow(client_ip(request)):
        raise _too_many()
    try:
        email = validate_email(body.email)
    except ValidationError:
        email = None
    if email:
        background.add_task(signin.request_signin, email, _base_url(request), settings.app_for(request))
    return {"ok": True}


@router.post("/signin/{token}")
def redeem_signin(token: str, request: Request, response: Response, background: BackgroundTasks):
    """The sign-in page's button: this browser is signed in to the link's list.
    Works once; a spent, expired or unknown token is a 404. Same-origin first, so
    a cross-site POST cannot spend the link or sign the browser in. A link mailed
    to the list's email also confirms it; ``verified`` says whether it is now.
    Signing in on an app's host turns that app on: it is how one app opens another."""
    _same_origin(request)
    redeemed = signin.redeem(token, settings.app_for(request))
    if redeemed is None:
        raise _wrong_token(request)
    sessions.set_cookie(response, redeemed["session_token"])
    if redeemed["verified"] and billing.syncing():
        # A customer's receipts follow the confirmed address (billing.push_email).
        background.add_task(billing.push_email, redeemed["list_id"])
    response.headers.update(_NO_STORE)
    return {"verified": redeemed["verified"]}


# ── Public: capture ───────────────────────────────────────────────────────────


def _capture(token: str, text: str) -> dict:
    list_id = lists.resolve_capture(token)
    if list_id is None:
        raise NotFoundError("Unknown capture token")
    lists.touch(list_id)
    return service.capture(list_id, text)


@router.post("/c/{token}")
async def public_capture(token: str, request: Request):
    """The WRITE-ONLY endpoint: a leaked capture link can add to an inbox but
    never read it. Takes the raw ``Request`` deliberately — a Pydantic body
    parameter would make FastAPI read and validate the JSON BEFORE the rate
    limit runs. Size is checked against Content-Length AND as the bytes stream
    in (a chunked body declares no length), before json.loads. Async, so the
    blocking INSERT runs behind asyncio.to_thread — never on the event loop. The traffic limits run
    BEFORE the token is looked up, so an over-budget request to an unknown token
    answers 429 rather than 404."""
    if not (capture_ip_limiter.allow(client_ip(request)) and capture_token_limiter.allow(token)):
        raise _too_many()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Capture too large")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Capture too large")
    try:
        payload = json.loads(body or b"{}")
    except (ValueError, RecursionError):  # RecursionError: deeply nested brackets
        raise HTTPException(status_code=400, detail="Invalid JSON")
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="Nothing to capture")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Capture text too long (max {MAX_TEXT_CHARS} characters)",
        )
    try:
        todo = await asyncio.to_thread(_call, _capture, token, text)
    except HTTPException as e:
        if e.status_code == 404:
            raise _wrong_token(request)
        raise
    return {"ok": True, "id": todo["id"]}
