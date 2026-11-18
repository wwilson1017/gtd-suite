"""Isolated Sites origins: this outer ASGI layer never dispatches them to the app."""

import asyncio
import collections
import contextlib
import threading
import hashlib
import ipaddress
import re
from urllib.parse import parse_qs, urlsplit, unquote_to_bytes, quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse

from backend import db, objectstore, pages, ratelimit, settings, sites

_HEADERS = {
    "Origin-Agent-Cluster": "?1",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cache-Control": "no-store",
}
_COOKIE = "__Host-ss-pass"
_UNLOCK = "/__simplesites/unlock"
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _host(value: str) -> tuple[str, int | None]:
    """Strict Host parsing; retain the port for the unlock origin comparison."""
    if not value or not value.isascii() or any(c in value for c in "/\\?#@ \t\r\n"):
        raise ValueError("Malformed Host")
    parts = urlsplit("//" + value)
    port = parts.port
    host = (parts.hostname or "").lower().removesuffix(".")
    if value.endswith(":") or not host or len(host) > 253:
        raise ValueError("Malformed Host")
    if value.startswith("["):
        if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", value):
            raise ValueError("Malformed Host")
        ipaddress.IPv6Address(host)
    elif any(not _LABEL.fullmatch(label) for label in host.split(".")):
        raise ValueError("Malformed Host")
    return host, port


def _locked(*, wrong: bool = False, status: int = 403) -> Response:
    response = pages._locked("", wrong, status, action=_UNLOCK)
    response.headers.update(_HEADERS)
    return response


def _miss(request: Request, *, clear: bool = False) -> Response:
    status = ratelimit.wrong_token_status(request)
    headers = dict(_HEADERS)
    if clear:
        headers["Clear-Site-Data"] = '"cache", "storage"'
    if status == 429:
        headers["Retry-After"] = "600"
    return PlainTextResponse(
        f"Nothing here. Report abuse to abuse@{settings.sites_content_domain()}.", status_code=status, headers=headers
    )


async def _unlock(request: Request, row, authority: tuple[str, int | None]) -> Response:
    # Match the actual content origin, never an app origin or a sibling. The configured
    # URLs use HTTPS even when the reverse proxy talks HTTP to this worker.
    try:
        origins = request.headers.getlist("origin")
        origin = urlsplit(origins[0]) if len(origins) == 1 else None
        origin_host, origin_port = _host(origin.netloc) if origin else ("", None)
        same = bool(
            origin
            and origin.scheme == "https"
            and not origin.path
            and not origin.query
            and not origin.fragment
            and origin_host == authority[0]
            and (443 if origin_port is None else origin_port) == (443 if authority[1] is None else authority[1])
        )
    except ValueError:
        same = False
    if not same:
        return PlainTextResponse("Forbidden", status_code=403, headers=_HEADERS)
    if not ratelimit.password_limiter.allow(ratelimit.client_ip(request)):
        return PlainTextResponse("Too many tries", status_code=429, headers={**_HEADERS, "Retry-After": "600"})
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > sites.PASSWORD_LIMITS[1] * 4 * 3 + 64:
            return PlainTextResponse("Too large", status_code=413, headers=_HEADERS)
    password = (parse_qs(body.decode("utf-8", "replace")).get("password") or [""])[0]
    try:
        right = await asyncio.to_thread(sites.check_password, row, password)
    except sites.Busy:
        return PlainTextResponse("Try again shortly", status_code=429, headers={**_HEADERS, "Retry-After": "5"})
    if not right:
        return _locked(wrong=True)
    response = RedirectResponse("/", status_code=303, headers=_HEADERS)
    response.set_cookie(
        _COOKIE,
        sites.unlock_cookie(row),
        max_age=sites.UNLOCK_DAYS * 86400,
        secure=True,
        httponly=True,
        path="/",
        samesite="lax",
    )
    return response


async def _site(request: Request, label: str, authority: tuple[str, int | None]) -> Response:
    row = await asyncio.to_thread(sites.lookup_host, label)
    if row is None:
        clear = await asyncio.to_thread(sites.host_taken_down, label)
        return _miss(request, clear=clear)
    if row["password_hash"]:
        if request.url.path == _UNLOCK and request.method == "POST":
            return await _unlock(request, row, authority)
        if not sites.unlocked(row, request.cookies.get(_COOKIE)):
            return _locked()
    if request.method not in ("GET", "HEAD"):
        return _miss(request)
    if row["layout"] == "files":
        return await _file_site(request, row)
    if request.url.path != "/":
        return _miss(request)
    body = await asyncio.to_thread(sites.render, row)
    etag = '"' + hashlib.sha256(body.encode()).hexdigest() + '"'
    headers = {**_HEADERS, "Cache-Control": "no-cache", "ETag": etag}
    if request.method == "GET" and request.headers.get("sec-fetch-dest") == "document":
        sites.count_view(row["id"])
    if any(
        tag.strip().removeprefix("W/") in (etag, "*") for tag in request.headers.get("if-none-match", "").split(",")
    ):
        return Response(status_code=304, headers=headers)
    return HTMLResponse(body, headers=headers)


class SiteHost:
    """Outside _ShortHost: content hosts answer here for every path and method."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        domain = settings.sites_content_domain()
        if not domain or scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        values = [v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"host"]
        try:
            if len(values) != 1:
                raise ValueError("One Host required")
            authority = _host(values[0])
        except ValueError:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await PlainTextResponse("Invalid Host", status_code=400, headers=_HEADERS)(scope, receive, send)
        host, _ = authority
        if host != domain and not host.endswith("." + domain):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        request = Request(scope, receive)
        # simplification: no service workers, allow them once takedowns can evict workers.
        if any(value.strip().lower() == "script" for value in request.headers.getlist("service-worker")):
            response = PlainTextResponse("Service workers are not supported", status_code=403, headers=_HEADERS)
        elif host == domain:
            response = PlainTextResponse(
                f"Simple Sites hosts pages here. Report abuse to abuse@{settings.sites_content_domain()}.",
                headers=_HEADERS,
            )
        else:
            label = host[: -len(domain) - 1]
            response = await _site(request, label, authority) if "." not in label else _miss(request)
        # ASGI responses don't strip bodies for HEAD themselves.
        if request.method == "HEAD":
            response.body = b""
        return await response(scope, receive, send)


# These are byte limits, not an entry count: decks contain very different asset sizes.
_CACHE_BYTES = 128_000_000
_CACHE_FILE_BYTES = 10_000_000
_cache: collections.OrderedDict[str, bytes] = collections.OrderedDict()
_cache_size = 0
_cache_lock = threading.Lock()


def _path(raw: bytes) -> tuple[str, bool]:
    if not raw.startswith(b"/"):
        raise sites.ValidationError("Invalid path")
    segments = raw.split(b"?", 1)[0].split(b"/")
    if segments[0] != b"":
        raise sites.ValidationError("Invalid path")
    decoded = []
    for segment in segments[1:]:
        text = unquote_to_bytes(segment).decode("utf-8")
        if "/" in text or "\x00" in text:
            raise sites.ValidationError("Invalid path")
        decoded.append(text)
    trailing = decoded[-1] == ""
    if trailing:
        decoded.pop()
    path = "/".join(decoded)
    if path:
        sites.file_key(path)
    elif decoded:
        raise sites.ValidationError("Invalid path")
    return path, trailing


def _chunks(file):
    read = 0
    with contextlib.closing(objectstore.stream(file["object_key"])) as chunks:
        for chunk in chunks:
            read += len(chunk)
            if read > file["bytes"]:
                raise objectstore.StoreError("The file store returned an incorrect size")
            yield chunk
    if read != file["bytes"]:
        raise objectstore.StoreError("The file store returned an incorrect size")


def _cached(file) -> bytes:
    global _cache_size
    sha = file["sha256"]
    with _cache_lock:
        if sha in _cache:
            _cache.move_to_end(sha)
            return _cache[sha]
    body = b"".join(_chunks(file))
    if hashlib.sha256(body).hexdigest() != sha:
        raise objectstore.StoreError("The file store returned an incorrect checksum")
    with _cache_lock:
        if sha not in _cache:
            while _cache and _cache_size + len(body) > _CACHE_BYTES:
                _, old = _cache.popitem(last=False)
                _cache_size -= len(old)
            _cache[sha] = body
            _cache_size += len(body)
    return body


async def _file_site(request: Request, row) -> Response:
    if not settings.files_s3():
        return PlainTextResponse("File store unavailable.", status_code=503, headers=_HEADERS)
    try:
        path, trailing = _path(request.scope.get("raw_path", b"/"))
    except (sites.ValidationError, UnicodeError):
        return _miss(request)

    def read_manifest():
        return sites.file_manifest(db.get_db(), row["list_id"], row["id"])

    manifest = await asyncio.to_thread(read_manifest)
    files = {f["path"]: f for f in manifest}
    file = files.get(path) if not trailing else None
    if file is None:
        index = f"{path}/index.html" if path else "index.html"
        if index in files:
            if path and not trailing:
                query = request.url.query
                target = "/" + quote(path, safe="/") + "/" + (f"?{query}" if query else "")
                return RedirectResponse(target, status_code=301, headers=_HEADERS)
            file = files[index]
    status = 200
    if file is None:
        file, status = files.get("404.html"), 404
    if file is None or not file["object_key"]:
        return _miss(request)
    if request.method == "GET" and request.headers.get("sec-fetch-dest") == "document":
        sites.count_view(row["id"])
    if file["path"].rsplit(".", 1)[-1].lower() not in sites.TEXT_EXTENSIONS:
        url = objectstore.presigned_get(
            file["object_key"], file["path"].rsplit("/", 1)[-1], file["content_type"], 12 * 3600, disposition="inline"
        )
        return RedirectResponse(url, status_code=302, headers=_HEADERS)
    etag = '"' + file["sha256"] + '"'
    headers = {**_HEADERS, "Cache-Control": "no-cache", "ETag": etag, "Content-Type": file["content_type"]}
    if status == 200 and any(
        tag.strip().removeprefix("W/") in (etag, "*") for tag in request.headers.get("if-none-match", "").split(",")
    ):
        return Response(status_code=304, headers=headers)
    headers["Content-Length"] = str(file["bytes"])
    if request.method == "HEAD":
        return Response(status_code=status, headers=headers)
    # simplification: no Range for same-origin text and no SPA fallback; media seeks at R2.
    if file["bytes"] > _CACHE_FILE_BYTES:
        return StreamingResponse(_chunks(file), status_code=status, headers=headers)
    try:
        body = await asyncio.to_thread(_cached, file)
    except objectstore.StoreError:
        return PlainTextResponse("File unavailable. Try again shortly.", status_code=503, headers=_HEADERS)
    return Response(body, status_code=status, headers=headers)
