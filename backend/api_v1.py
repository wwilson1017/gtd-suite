"""todo-gtd — the REST API: a program's way in with a key (keys.py), no MCP client needed.

    GET  /api/v1                 the account, the key, and the tools it may call
    POST /api/v1/tools/{name}    call one: a JSON object of arguments in, its result out
    POST /api/v1/import          a raw zip; dry_run, label and archive_missing query options
    GET  /api/v1/export?since=   a consistent snapshot, optionally only changes after a date

The key travels only as ``Authorization: Bearer cb_…``. A missing, unknown or revoked
key is 403 {error}, with no WWW-Authenticate (CLAUDE.md: no 401 on a token route). A
miss is charged to the address's wrong-token bucket first, and a valid key is always
served. Then the account's call budget, shared with the agent link
(mcp_server.call_limiter).

A call goes through ``mcp.call_tool``, the MCP server's own path: argument validation,
the apps-on middleware, the tool and its error mapping. So REST mirrors every tool with
no second copy. The status is decided before the call, never by reading error text: a
name that is no tool is 404, and a tool this key may not call is 403
(mcp_server.refusal). During the call, a refused argument or the tool's own refusal is
400 {error}. Every answer is no-store.

_authorize is the one check for the routes of their own (files, import and export):
Brain on and in the key's apps, its access, and its folders.

Common Brain's files (files.py), whose bytes go straight between the program and the store:

    POST /api/v1/files              reserve one file {path, size, sha256, content_type}, or
                                    {files: [up to 100]}: each gets an upload (a PUT)
    POST /api/v1/files/{id}/done    after its PUT: the file goes live (a retry is fine)
    GET  /api/v1/files?path=        302 to a 5-minute download of the file at that path
    GET  /api/v1/files/{id}         302 to that exact file version
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastmcp.exceptions import ToolError, ValidationError

from backend import brain, brain_agent, brain_import, common, files, keys, lists, mcp_server, ratelimit

_NO_STORE = {"Cache-Control": "no-store"}
router = APIRouter(prefix="/api/v1")


class Refused(Exception):
    """A refusal, answered as {error} with this status (refused, registered in main.py)."""

    def __init__(self, status: int, error: str, headers: dict | None = None):
        super().__init__(error)
        self.status, self.error, self.headers = status, error, headers or {}


def refused(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Refused)  # Registered only for Refused.
    return JSONResponse({"error": exc.error}, exc.status, {**_NO_STORE, **exc.headers})


async def _authorize(
    request: Request,
    need: str | None = None,
    path: str | None = None,
    open_folders: bool = False,
    *,
    files: list | None = None,
) -> dict:
    """The live key on this request (keys.resolve), or Refused. With `need` ('read' or
    'write'), for a Brain route of its own: _allow."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip() if scheme.lower() == "bearer" else ""
    key = await asyncio.to_thread(keys.resolve, token) if token else None
    if key is None:
        # A request with no key at all is not a guess, so it is not charged.
        if token and ratelimit.wrong_token_status(request) == 429:
            raise Refused(429, ratelimit.TOO_MANY_WRONG_LINKS, {"Retry-After": "600"})
        raise Refused(403, "unknown or revoked key")
    if not mcp_server.call_limiter.allow(str(key["list_id"])):
        raise Refused(429, "Too many requests. Please wait a moment and try again.", {"Retry-After": "60"})
    if key["apps"] == "brain" and not key["active_brains"]:
        raise Refused(403, "This link reaches no active brain")
    key["selected_brain"] = request.query_params.get("brain")
    if need is not None:
        _allow(key, need, path, open_folders, files=files)
    return key


def _allow(
    key: dict, need: str, path: str | None = None, open_folders: bool = False, *, files: list | None = None
) -> None:
    """Brain on and in the key's apps, the key's access (`need`: 'read' or 'write'), and
    for a folder-limited key `path` inside its folders, or each of `files` (file paths,
    exactly); with `open_folders` (import, export: the whole brain) no folder limit at all."""
    with _as(key):
        if why := mcp_server.refusal("brain_page_write" if need == "write" else "brain_page_get"):
            raise Refused(403, why)
        _brain_id(key)
    if key["folders"] and (
        open_folders
        or not (
            all(keys.inside(f, key["folders"], file=True) for f in files)
            if files is not None
            else keys.inside(path, key["folders"])
        )
    ):
        raise Refused(403, "This key is limited to its folders.")


@contextlib.contextmanager
def _as(key: dict):
    """The MCP server's contextvars for this key's call, reset however it ends."""
    resets = (
        mcp_server._list_id.set(key["list_id"]),
        mcp_server._apps_on.set(key["on"]),
        mcp_server._key.set(key),
        mcp_server._brains.set(key["active_brains"]),
    )
    try:
        yield
    finally:
        mcp_server._brains.reset(resets[3])
        mcp_server._key.reset(resets[2])
        mcp_server._apps_on.reset(resets[1])
        mcp_server._list_id.reset(resets[0])


async def _arguments(request: Request) -> dict:
    """The JSON object of arguments, refused past the MCP body limit as it streams in."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > mcp_server._MAX_BODY_BYTES:
            raise Refused(413, f"Request too large: at most {mcp_server._MAX_BODY_BYTES // 2**20} MB")
    try:
        args = json.loads(body) if body.strip() else {}
    except ValueError:
        args = None
    if not isinstance(args, dict):
        raise Refused(400, "The body must be a JSON object of the tool's arguments")
    return args


@router.get("")
async def about(request: Request):
    key = await _authorize(request)
    with _as(key):
        tools = await mcp_server.mcp.list_tools()
    account = await asyncio.to_thread(lists.get_list, key["list_id"])
    assert account is not None  # The authenticated key belongs to this list.
    return JSONResponse(
        {
            # The number people see (lists.account_no) where the server has one; never the id.
            "account_no": account.get("account_no"),
            "key": {k: key[k] for k in ("name", "apps", "access", "folders")},
            "apps_on": key["on"],
            "tools": [
                {
                    "name": t.name,
                    "title": t.title,
                    "description": t.description,
                    "input_schema": t.parameters,
                    "read_only": mcp_server._TOOL_READONLY[t.name],
                }
                for t in tools
            ],
        },
        headers=_NO_STORE,
    )


@router.post("/tools/{name}")
async def call_tool(name: str, request: Request):
    key = await _authorize(request)
    if name not in mcp_server._TOOL_APPS:
        raise Refused(404, f"There is no tool called {name}. GET /api/v1 lists them.")
    args = await _arguments(request)
    with _as(key):
        if why := mcp_server.refusal(name):
            raise Refused(403, why)
        try:
            result = await mcp_server.mcp.call_tool(name, args)
        except (ToolError, ValidationError) as e:
            raise Refused(400, str(e)) from None
    return JSONResponse(result.structured_content, headers=_NO_STORE)


# ── Files ─────────────────────────────────────────────────────────────────────


def _brain_id(key: dict) -> int:
    with _as(key):
        try:
            return brain_agent._select(key.get("selected_brain"))["id"]
        except common.ValidationError as exc:
            raise Refused(403, str(exc)) from None


async def _files(fn, *args, **kwargs):
    """A files.py call off the event loop, its refusals as {error}."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except common.NotFoundError as e:
        raise Refused(404, str(e)) from None
    except common.ConflictError as e:
        raise Refused(409, str(e)) from None
    except common.ValidationError as e:
        raise Refused(400, str(e)) from None
    except OverflowError:  # sqlite3 refuses an int beyond 64 bits: bad input, not a crash
        raise Refused(400, "Number out of range") from None


@router.post("/files")
async def reserve_files(request: Request):
    key = await _authorize(request)
    body = await _arguments(request)
    items = body["files"] if "files" in body else [body]
    if not isinstance(items, list):
        raise Refused(400, "files is a list of {path, size, sha256, content_type}")
    _allow(key, "write", files=[i.get("path") if isinstance(i, dict) else None for i in items])
    return JSONResponse(await _files(files.reserve, _brain_id(key), items, key["name"]), headers=_NO_STORE)


@router.post("/files/{file_id}/done")
async def finish_file(file_id: int, request: Request):
    key = await _authorize(request)
    _allow(key, "write", files=[(await _files(files.get, _brain_id(key), file_id))["path"]])
    return JSONResponse(await _files(files.done, _brain_id(key), file_id), headers=_NO_STORE)


@router.get("/files")
async def download_file(request: Request, path: str = ""):
    key = await _authorize(request, "read", files=[path])
    got = await _files(files.link, _brain_id(key), path=path)
    return RedirectResponse(got["url"], 302, headers=_NO_STORE)


@router.post("/import")
async def import_markdown(request: Request, dry_run: bool = False, label: str = "", archive_missing: bool = False):
    key = await _authorize(request, need="write", open_folders=True)
    try:
        report = await brain_import.receive(
            request, _brain_id(key), key["name"], dry_run=dry_run, label=label, archive_missing=archive_missing
        )
    except HTTPException as exc:
        raise Refused(exc.status_code, str(exc.detail)) from None
    except common.ConflictError as exc:
        raise Refused(409, str(exc)) from None
    except common.ValidationError as exc:
        raise Refused(400, str(exc)) from None
    return JSONResponse(report, headers=_NO_STORE)


@router.get("/export")
async def export(request: Request, since: str = ""):
    key = await _authorize(request, need="read", open_folders=True)
    return Response(
        await _files(brain.export_zip, _brain_id(key), since or None),
        media_type="application/zip",
        headers={**_NO_STORE, "Content-Disposition": 'attachment; filename="common-brain.zip"'},
    )


@router.get("/files/{file_id}")
async def download_file_version(file_id: int, request: Request):
    key = await _authorize(request)
    item = await _files(files.get, _brain_id(key), file_id)
    _allow(key, "read", files=[item["path"]])
    got = await _files(files.link, _brain_id(key), file_id=file_id)
    return RedirectResponse(got["url"], 302, headers=_NO_STORE)
