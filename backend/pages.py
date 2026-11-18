"""todo-gtd — the HTML pages: the built SPA shell, the manifests, and the
"this link isn't valid" pages.

    GET /                         landing: create a list or sign in; a signed-in browser → /app
    GET /app[/...]                the web app (shell + manifest), for a signed-in browser; else → /
    GET /signin/{token}           the sign-in page; loading it redeems NOTHING
    GET /c/{capture token}[/...]  the write-only capture page (shell + manifest)
    GET /c                        no token at all: the invalid-link page
    GET /w[/...]                  the old web links: "this address is no longer used"
    GET /{name}                   a file from the build's root, else the landing shell

Every page here is ``no-store`` + ``noindex`` + ``no-referrer``: a sign-in or
capture address IS a credential, so it must not be cached, indexed, or leaked to
a site the user clicks through to. An unknown or rotated token is a 404, never a
401, and it is an HTML page a person can act on: an installed home-screen app
relaunches into a window with no address bar, where a raw JSON body would be a
dead end. The redirects never touch the session cookie (sessions.py).

The catch-all is LAST — main.py includes this router after everything else —
and only one path segment deep, so it can never shadow the API or the MCP routes.
"""

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from backend import apps, lists, ratelimit, sessions, settings, sites
from backend.router import _same_origin

PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
}

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"

# Where the per-page markup is injected. Pinned against the real
# frontend/index.html by a test: if the anchor drifts, the page still answers
# 200 — just without its base or manifest.
INJECT_ANCHOR = "</head>"

# Each app's browser bar and installed-app colour: its tile's (frontend/public/icon*.svg).
_THEME_COLORS = {"todo": "#c0272d", "notes": "#f9cf3a", "projects": "#047a5c", "sites": "#1a3fc7", "brain": "#070b1a"}
# The light palette's page background and brand red (frontend/src/index.css).
_BACKGROUND_COLOR = "#f1f1e8"

_index_cache: tuple[float, str] | None = None


def index_html() -> str:
    """The built SPA shell, cached on mtime. Empty string if not built."""
    global _index_cache
    try:
        mtime = INDEX_PATH.stat().st_mtime
    except OSError:
        return ""
    if _index_cache and _index_cache[0] == mtime:
        return _index_cache[1]
    html = INDEX_PATH.read_text(encoding="utf-8")
    _index_cache = (mtime, html)
    return html


def _page_chrome(title: str, body_html: str) -> str:
    """A status page with no stylesheet, script, image or font to fail to load.
    Nothing caller-controlled belongs in ``body_html``: there is no escaping
    here, and the token in the address is attacker-supplied."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{title}</title>"
        "<style>"
        "body{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:40px 24px;"
        "background:#f1f1e8;color:#292929;line-height:1.55;color-scheme:light dark}"
        "main{max-width:26rem;margin:0 auto}"
        "h1{font-size:1.25rem;margin:0 0 .75rem}p{margin:0 0 .75rem}a{color:inherit}"
        "@media(prefers-color-scheme:dark){body{background:#1c1b19;color:#f0efe8}}"
        "</style></head><body><main>"
        f"{body_html}"
        "</main></body></html>"
    )


_UNBUILT_HTML = _page_chrome(
    "Todo GTD",
    "<p>Frontend build not found. Run <code>npm run build</code> in "
    "<code>frontend/</code> (or start the Vite dev server) and reload.</p>",
)

_READD = (
    "<p>If you added this to your home screen, remove it and "
    "<strong>re-add it from the new link</strong> &mdash; an installed app keeps "
    "the old one.</p>"
)

# The old /w/<token> web links (and home-screen apps installed from them). It
# resolves nothing: whatever the token was, it means nothing now.
_RETIRED_WEB_HTML = _page_chrome(
    "Todo GTD",
    "<h1>This address is no longer used</h1>"
    '<p>Lists now open at one address for everyone. <a href="/">Open the home page</a> '
    "to sign in.</p>"
    "<p>If you added this to your home screen, remove it and add it again once you "
    "are signed in.</p>",
)

_INVALID_CAPTURE_HTML = _page_chrome(
    "Capture",
    "<h1>This link isn&rsquo;t valid</h1>"
    "<p>It may have been regenerated. Open your list, go to <strong>&#9881; Connect</strong>, "
    "and copy your current capture link.</p>" + _READD,
)


def _shell(request: Request, head_html: str = "") -> HTMLResponse:
    """The SPA shell with ``head_html`` injected before ``</head>``. On another
    app's host (apps.py) it carries that app's title and a ``gtd-app`` meta naming
    it, which is what makes the one bundle that app (frontend/src/core/app.ts).

    Callers build ``head_html`` only from a token they have already RESOLVED (a
    server-minted ``lists.mint_token`` value) and from user text they
    have escaped (the list's name), so it is safe inside the HTML attributes."""
    html = index_html()
    if not html:
        return HTMLResponse(_UNBUILT_HTML, status_code=503, headers=PAGE_HEADERS)
    app = settings.app_for(request)
    if app != apps.ANCHOR:
        html = html.replace(
            f"<title>{apps.APPS[apps.ANCHOR].title}</title>", f"<title>{apps.APPS[app].title}</title>", 1
        )
        # The app's colours from the first paint (index.css [data-app="…"]).
        html = html.replace('<html lang="en">', f'<html lang="en" data-app="{app}">', 1)
        # Each app's own mark (frontend/public/icon-<app>*): its favicon and home-screen icon.
        html = html.replace('href="/icon.svg"', f'href="/icon-{app}.svg"', 1)
        html = html.replace('href="/apple-touch-icon.png"', f'href="/apple-touch-icon-{app}.png"', 1)
        head_html = "\n  ".join(filter(None, (f'<meta name="gtd-app" content="{app}">', head_html)))
    prefix = request.scope.get("app_prefix", "")
    if prefix:
        head_html = f'<meta name="gtd-base" content="{prefix}">\n' + head_html
    if head_html:
        html = html.replace(INJECT_ANCHOR, f"  {head_html}\n  {INJECT_ANCHOR}", 1)
    return HTMLResponse(html, headers=PAGE_HEADERS)


def _pwa_head(base_path: str, title: str, app: str) -> str:
    # use-credentials: a manifest is fetched without cookies by default, and the
    # web app's manifest needs the session to carry the list's name.
    return (
        f'<link rel="manifest" href="{base_path}/manifest.webmanifest" crossorigin="use-credentials">\n'
        '  <meta name="mobile-web-app-capable" content="yes">\n'
        '  <meta name="apple-mobile-web-app-capable" content="yes">\n'
        '  <meta name="apple-mobile-web-app-status-bar-style" content="default">\n'
        f'  <meta name="apple-mobile-web-app-title" content="{title}">\n'
        f'  <meta name="theme-color" content="{_THEME_COLORS[app]}">'
    )


def _manifest(
    start_url: str,
    name: str,
    description: str,
    scope: str | None = None,
    app: str = apps.ANCHOR,
    icon: str | None = None,
) -> Response:
    """Web app manifest so Add to Home Screen installs a standalone app.

    No trailing slash on a path scope on purpose (a base + "/" scope would put
    the launch page itself outside its own scope). The scopes never overlap and
    each manifest has its own `id`: a page inside an installed app's scope is
    "already installed" to the browser, which is what kept Capture from
    installing beside the app."""
    icon = icon if icon is not None else ("" if app == apps.ANCHOR else f"-{app}")
    manifest = {
        "id": start_url,
        "name": name,
        "short_name": name,
        "description": description,
        "start_url": start_url,
        "scope": scope or start_url,
        "display": "standalone",
        "background_color": _BACKGROUND_COLOR,
        "theme_color": _THEME_COLORS[app],
        "icons": [
            {
                "src": f"/icon{icon}-{size}.png",
                "sizes": f"{size}x{size}",
                "type": "image/png",
                "purpose": "any maskable",
            }
            for size in (192, 512)
        ],
    }
    return Response(json.dumps(manifest), media_type="application/manifest+json", headers=PAGE_HEADERS)


def _not_found() -> HTTPException:
    # HTTPException responses do not inherit a handler's headers; pass them.
    return HTTPException(status_code=404, detail="Not found", headers=PAGE_HEADERS)


def _resolve(request: Request, resolver, token: str) -> int | None:
    """The token's list id, or None — counting the miss against the caller's
    address, and answering 429 once that address has missed too often. A valid
    link is always served (ratelimit.bad_token_limiter).

    # simplification: the refusal is the API's JSON 429, not a styled page
    """
    list_id = resolver(token)
    if list_id is None and ratelimit.wrong_token_status(request) == 429:
        raise HTTPException(
            status_code=429,
            detail=ratelimit.TOO_MANY_WRONG_LINKS,
            headers={**PAGE_HEADERS, "Retry-After": "600"},
        )
    return list_id


# Plain `def` handlers: the token lookup is blocking SQLite, so FastAPI runs
# them in its threadpool. None of them is in the OpenAPI schema (pages, not API).
router = APIRouter(include_in_schema=False)


def _signed_in_list(request: Request) -> int | None:
    session = sessions.resolve(request.cookies.get(sessions.COOKIE))
    return session["list_id"] if session else None


def _to(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303, headers=PAGE_HEADERS)


def _moved(request: Request) -> RedirectResponse | None:
    """A signed-out visitor on an app's old host: on to its address today. A 303, never a
    permanent redirect: the old host still serves the browsers signed in there."""
    moved = settings.moved_to(request)
    return _to(moved) if moved and _signed_in_list(request) is None else None


# ── Web app ───────────────────────────────────────────────────────────────────
# The manifest route MUST stay registered before the page's path catch-all.


@router.get("/app/manifest.webmanifest")
def app_manifest(request: Request):
    """One manifest for every list, named after the app, never the list. Scope
    is /app only, so the capture page (/c/...) installs as an app of its own."""
    app = settings.app_for(request)
    return _manifest(
        request.scope.get("app_prefix", "") + "/app",
        _installed_name(app),
        f"Your {apps.APPS[app].title}",
        scope=request.scope.get("app_prefix", "") + "/app",
        app=app,
    )


def _installed_name(app: str) -> str:
    """Todo GTD for the todo list; the other apps keep their short names."""
    return apps.APPS[app].title if app == apps.ANCHOR else apps.APPS[app].short


@router.get("/app")
@router.get("/app/{rest:path}")
def app_page(request: Request, rest: str = ""):
    """The app, for a signed-in browser; anyone else goes to the home page. No
    touch, so opening the app never counts as using the list by itself."""
    list_id = _signed_in_list(request)
    if list_id is None:
        return _to(settings.moved_to(request) or request.scope.get("app_prefix", "") + "/")
    app = settings.app_for(request)
    return _shell(request, _pwa_head(request.scope.get("app_prefix", "") + "/app", _installed_name(app), app))


@router.get("/w")
@router.get("/w/{token}")
@router.get("/w/{token}/{rest:path}")
def retired_web_link(token: str = "", rest: str = ""):
    return HTMLResponse(_RETIRED_WEB_HTML, status_code=404, headers=PAGE_HEADERS)


# ── Capture page ──────────────────────────────────────────────────────────────


@router.get("/c/{token}/manifest.webmanifest")
def capture_manifest(token: str, request: Request):
    if _resolve(request, lists.resolve_capture, token) is None:
        raise _not_found()
    # On the todo host its own mark, a plus in a box, so installed beside Todo GTD
    # the two differ; another app's host keeps that app's mark.
    app = settings.app_for(request)
    return _manifest(
        f"{request.scope.get('app_prefix', '')}/c/{token}",
        "Capture",
        "Add to your Todo GTD inbox",
        app=app,
        icon="-capture" if app == apps.ANCHOR else None,
    )


@router.get("/c")
@router.get("/c/{token}")
@router.get("/c/{token}/{rest:path}")
def capture_page(request: Request, token: str = "", rest: str = ""):
    if not token or _resolve(request, lists.resolve_capture, token) is None:
        return HTMLResponse(_INVALID_CAPTURE_HTML, status_code=404, headers=PAGE_HEADERS)
    app = settings.app_for(request)
    head = _pwa_head(f"{request.scope.get('app_prefix', '')}/c/{token}", "Capture", app)
    if app == apps.ANCHOR:
        # The home-screen icon iOS takes (it ignores the manifest's). Sized, so it
        # beats the shell's unsized one.
        head += '\n  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon-capture.png">'
    return _shell(request, head)


# ── Landing, sign-in, and the build's root files ──────────────────────────────


@router.get("/")
def landing(request: Request):
    """The plain shell, or the app for a browser that is signed in. On an old host
    (settings.old_url) a signed-out visitor goes to where the app lives now."""
    if _signed_in_list(request) is not None:
        return _to(request.scope.get("app_prefix", "") + "/app")
    return _moved(request) or _shell(request)


@router.get("/signin/{token}")
def signin_page(token: str, request: Request):
    """The plain shell. Loading it redeems NOTHING — mail scanners and link
    previews fetch links; only the page's button POSTs."""
    return _shell(request)


# Never a page: an unmatched API or MCP address must stay a 404, not the landing
# shell — and so must the addresses an AI client probes when it goes looking for
# a sign-in (mcp_server.py answers those for every method; listing them here
# keeps that true whatever order the routers are included in).
_NOT_PAGES = ("api", "mcp", "link", "assets", ".well-known", "register", "authorize", "token", "app", "signin")


def _site_host(request: Request) -> bool:
    return not request.scope.get("app_prefix") and (
        settings.app_for(request) == "sites" or (not settings.app_base_url("sites") and settings.on_main_host(request))
    )


def _site(request: Request, path: str):
    """A Simple Sites address. A page is served sandboxed (sites.SANDBOX), a link
    redirects, and neither sends a referrer onward or counts as using the list. A
    miss (unknown, unpublished, a wrong name, a list that is off) is a wrong link:
    404, then 429 for an address that keeps guessing."""
    row = sites.lookup(path)
    if row is None:
        if ratelimit.wrong_token_status(request) == 429:
            return HTMLResponse(
                ratelimit.TOO_MANY_WRONG_LINKS, status_code=429, headers={**PAGE_HEADERS, "Retry-After": "600"}
            )
        return HTMLResponse(_page_chrome("Not found", _SITE_MISSING), status_code=404, headers=PAGE_HEADERS)
    if sites.hosted(row):
        target = sites.host_url(row) + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(target, status_code=302, headers=PAGE_HEADERS)
    if row["password_hash"] and not sites.unlocked(row, request.cookies.get(_unlock_cookie(row))):
        return _locked(path)
    if request.method == "GET":  # not a link checker's HEAD
        sites.count_view(row["id"])
    if row["kind"] == "link":
        return RedirectResponse(row["target"], status_code=302, headers=PAGE_HEADERS)
    return HTMLResponse(
        sites.render(row),
        headers={**PAGE_HEADERS, "Content-Security-Policy": sites.SANDBOX, "X-Content-Type-Options": "nosniff"},
    )


def _unlock_cookie(row) -> str:
    return f"sp_{row['code']}"


# The password form: ours, so no sandbox, but nothing else may load or post elsewhere.
_LOCKED_HEADERS = {
    **PAGE_HEADERS,
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
}


def _locked(path: str, wrong: bool = False, status: int = 403, *, action: str | None = None) -> HTMLResponse:
    """A locked page's password form, never its content. 403, not 401: an AI client
    reads 401 as "start a sign-in" (CLAUDE.md). ``path`` matched sites.ADDRESS_RE."""
    action = action or f"/{path}/unlock"
    note = '<p style="color:#a3282e">Wrong password. Try again.</p>' if wrong else ""
    body = (
        f"<h1>This page is locked</h1><p>Its owner gave it a password.</p>{note}"
        f'<form method="post" action="{action}">'
        # No maxlength: HTML counts UTF-16 units, the server counts characters (sites.py).
        '<label>Password <input type="password" name="password" required autofocus '
        'autocomplete="current-password"></label> <button>Open</button></form>'
    )
    return HTMLResponse(_page_chrome("Locked page", body), status_code=status, headers=_LOCKED_HEADERS)


_SITE_MISSING = "<h1>Nothing here</h1><p>This address has no page or link, or it was taken down.</p>"


def _data_response(body=None, status=200, headers=None):
    headers = {
        **PAGE_HEADERS,
        "Access-Control-Allow-Origin": "*",
        "X-Content-Type-Options": "nosniff",
        **(headers or {}),
    }
    if status == 204:
        return Response(status_code=status, headers=headers)
    return Response(
        json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        status_code=status,
        media_type="application/json",
        headers=headers,
    )


@router.api_route("/{name}/data", methods=["GET", "POST", "OPTIONS"])
async def site_data(name: str, request: Request):
    def miss():
        status = ratelimit.wrong_token_status(request)
        return _data_response(
            {"ok": False, "error": "not found"}, status, {"Retry-After": "600"} if status == 429 else None
        )

    if request.scope.get("app_prefix"):
        return _data_response({"ok": False, "error": "not found"}, 404)
    if not _site_host(request) or not sites.ADDRESS_RE.fullmatch(name):
        return miss()
    try:
        await asyncio.to_thread(sites._data_page, name)
        if request.method == "OPTIONS":
            return _data_response(
                status=204,
                headers={
                    "Access-Control-Allow-Methods": "GET, POST",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "600",
                },
            )
        limiter = ratelimit.data_write_limiter if request.method == "POST" else ratelimit.data_read_limiter
        if not limiter.allow(ratelimit.client_ip(request)):
            return _data_response({"ok": False, "error": "rate limit"}, 429, {"Retry-After": "60"})
        if request.method == "GET":
            answer = await asyncio.to_thread(sites.page_data, name, request.query_params.multi_items())
        else:
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > sites.DATA_MAX_BYTES:
                    return _data_response({"ok": False, "error": "too large"}, 413)
            answer = await asyncio.to_thread(sites.add_record, name, "visitor", body)
        return _data_response(answer)
    except sites.NotFoundError:
        return miss()
    except sites.DataFull:
        return _data_response({"ok": False, "error": "full"}, 409)
    except sites.DataTooLarge:
        return _data_response({"ok": False, "error": "too large"}, 413)
    except sites.ValidationError as e:
        return _data_response({"ok": False, "error": str(e)}, 400)


@router.post("/{name}/unlock")
async def site_unlock(name: str, request: Request):
    """A locked page's password form posts here. Every try is charged to the address
    first (ratelimit.password_limiter), before any hashing; a miss is a wrong link.
    Right: a pass for this page (sites.unlock_cookie) and back to it. Wrong: the form."""
    if not _site_host(request) or not sites.ADDRESS_RE.fullmatch(name):
        raise _not_found()
    # Only this site's own form, before anything is charged: another site could make a
    # visitor's browser post here and spend that address's tries.
    _same_origin(request)
    if not ratelimit.password_limiter.allow(ratelimit.client_ip(request)):
        return HTMLResponse(
            _page_chrome("Too many tries", "<p>Too many tries from this address. Wait ten minutes and try again.</p>"),
            status_code=429,
            headers={**PAGE_HEADERS, "Retry-After": "600"},
        )
    # Room for the longest password a page takes: 200 characters of up to 4 UTF-8 bytes,
    # each byte percent-encoded (3 characters), plus the field name.
    limit = sites.PASSWORD_LIMITS[1] * 4 * 3 + 64
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="Too large", headers=PAGE_HEADERS)
    password = (parse_qs(body.decode("utf-8", "replace")).get("password") or [""])[0]
    row = await asyncio.to_thread(sites.lookup, name)
    if row is None or row["kind"] != "page" or not row["password_hash"]:
        if ratelimit.wrong_token_status(request) == 429:
            return HTMLResponse(
                ratelimit.TOO_MANY_WRONG_LINKS, status_code=429, headers={**PAGE_HEADERS, "Retry-After": "600"}
            )
        return HTMLResponse(_page_chrome("Not found", _SITE_MISSING), status_code=404, headers=PAGE_HEADERS)
    try:
        right = await asyncio.to_thread(sites.check_password, row, password)
    except sites.Busy:
        return HTMLResponse(
            _page_chrome("Busy", "<p>Too many tries at once. Wait a moment.</p>"),
            status_code=429,
            headers={**PAGE_HEADERS, "Retry-After": "5"},
        )
    if not right:
        return _locked(name, wrong=True)
    res = RedirectResponse(f"/{name}", status_code=303, headers=PAGE_HEADERS)
    res.set_cookie(
        _unlock_cookie(row),
        sites.unlock_cookie(row),
        path=f"/{name}",
        max_age=sites.UNLOCK_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=(settings.app_base_url("sites") or settings.app_url("todo", request)).startswith("https://"),
    )
    return res


@router.api_route("/{name}", methods=["GET", "HEAD"])
def root_file(name: str, request: Request):
    """The catch-all, ONE segment deep on purpose: a Simple Sites address on the
    Sites host (HEAD too, for link checkers), a file from the build's root (icons),
    else the landing shell. It cannot match /api/… or /mcp/… paths at
    all, so it never turns their 404/405 answers into a page."""
    if request.scope.get("app_prefix") and (sites.ADDRESS_RE.fullmatch(name) or sites.lookup_short(name) is not None):
        raise _not_found()
    if name in _NOT_PAGES:
        raise _not_found()
    if _site_host(request) and sites.ADDRESS_RE.fullmatch(name):
        return _site(request, name)
    if _site_host(request):
        short = sites.lookup_short(name)
        if short is not None:
            if request.method == "GET":
                sites.count_view(short["id"])
            return RedirectResponse(short["target"], status_code=302, headers=PAGE_HEADERS)
    if name in {"terms.html", "privacy.html", "refunds.html", "support.html", "legal.css"}:
        if not settings.open_signup():
            return _shell(request)
        candidate = STATIC_DIR / "paid" / name
    else:
        candidate = STATIC_DIR / name
    if name != "index.html" and candidate.is_file():
        return FileResponse(candidate)
    return _moved(request) or _shell(request)
