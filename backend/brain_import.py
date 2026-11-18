"""Markdown zip import: validate everything first, then resumable chunks under one pass.

Files go through reserve/PUT/done before each chunk's database transaction. The report
contains paths and counts, never bodies, memory text, or upload URLs.
"""

import asyncio
from collections import Counter
from contextlib import contextmanager
import hashlib
import io
import mimetypes
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import threading
from urllib.parse import unquote
import zipfile
import zlib

import httpx2 as httpx
from fastapi import HTTPException, Request

from backend import brain, common, db, files, objectstore
from backend.common import ConflictError, ValidationError

MAX_ENTRIES = 50_000
MAX_BYTES = 1_000_000_000
MAX_FILE = 100_000_000
MAX_UPLOAD = 200_000_000
CHUNK = 500
# Attachments read as text, so their secrets are blanked like a page's.
TEXT_FILES = {".txt", ".csv", ".json", ".jsonl", ".yaml", ".yml", ".toml"}
_running: set[int] = set()
_guard = threading.Lock()


@contextmanager
def _account(brain_id):
    list_id = brain._list_of(db.get_db(), brain_id)
    with _guard:
        if list_id in _running:
            raise ConflictError("An import is already running for this account.")
        _running.add(list_id)
    try:
        yield
    finally:
        with _guard:
            _running.remove(list_id)


def _report():
    return {
        "complete": False,
        "processed": 0,
        "written": 0,
        "skipped": 0,
        "archived": 0,
        "counts": {"pages": 0, "memories": 0, "files": 0},
        "entries": [],
        "path_changes": [],
        "removed": [],
        "decoded": [],
        "oversized": [],
        "warnings": [],
        "over_cap": [],
        "error": None,
    }


def _scan(zip_path, directory, by, report):
    entries, names, targets, long_memories = [], set(), set(), []
    total = hidden = 0

    def room():
        if len(entries) + len(long_memories) >= MAX_ENTRIES:
            raise ValidationError(f"A zip holds at most {MAX_ENTRIES:,} entries, memory lines included.")

    def add(entry):
        room()
        if entry["kind"] != "memory":
            target = entry["path"]
            if target in targets:
                raise ValidationError("Zip paths collide after normalising: " + entry["path"])
            targets.add(target)
        entries.append(entry)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise ValidationError(f"A zip holds at most {MAX_ENTRIES:,} entries.")
            if any(
                "/" not in info.filename
                and info.file_size < 100
                and archive.read(info).strip() == b"common-brain-export: 1"
                for info in infos
            ):
                raise ValidationError("restoring from an export isn't supported yet")
            for i, info in enumerate(infos):
                name = info.orig_filename
                path = name[:-1] if info.is_dir() else name
                if (
                    not path
                    or re.match(r"^[A-Za-z]:", path)
                    or "\x00" in name
                    or stat.S_ISLNK(info.external_attr >> 16)
                ):
                    raise ValidationError("Zip contains an unsafe path or symlink.")
                files.file_path(path)  # absolute paths, traversal, backslashes and controls
                if path in names:
                    raise ValidationError("Zip contains duplicate names: " + path)
                names.add(path)
                if info.is_dir():
                    continue
                if any(part.startswith(".") or part == "__MACOSX" for part in path.split("/")):
                    hidden += 1
                    continue
                local = Path(directory) / str(i)
                size = 0
                with archive.open(info) as source, local.open("wb") as dest:
                    while chunk := source.read(min(64 * 1024, MAX_BYTES - total + 1, MAX_FILE - size + 1)):
                        size += len(chunk)
                        total += len(chunk)
                        if total > MAX_BYTES or size > MAX_FILE:
                            raise ValidationError("Zip exceeds 1 GB total or 100 MB per file.")
                        dest.write(chunk)
                suffix = PurePosixPath(path).suffix.lower()
                is_memory = path.lower() in ("memory.md", "memories.md")
                is_page = suffix in (".md", ".markdown", ".html", ".htm")
                if is_page:
                    raw = local.read_bytes()
                    try:
                        body = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        body = raw.decode("utf-8", errors="replace")
                        report["decoded"].append(path)
                    if is_memory:
                        locked, gone = False, Counter()
                        for line in io.StringIO(body):  # line by line: no list of a huge file's lines
                            line = line.rstrip("\r\n")
                            if line.lstrip().startswith("#"):
                                locked = bool(re.search(r"\blocked\b", line, re.I))
                            if not re.match(r"[-*+] ", line):
                                continue
                            lock = locked or "🔒" in line
                            text, removed = brain._blank_secrets(" ".join(line[2:].replace("🔒", "").split()))
                            gone += removed
                            if not text:
                                continue
                            if lock and by != brain.YOU:
                                report["warnings"].append({"path": path, "reason": "locks need the person"})
                            if len(text) > brain.MEMORY_CHARS:
                                room()
                                long_memories.append("- " + text)
                            else:
                                add({"kind": "memory", "path": path, "text": text, "locked": lock and by == brain.YOU})
                        if gone:
                            report["removed"].append({"path": path, "counts": brain._removed(gone)})
                        continue
                    body, removed = brain._blank_secrets(body)
                    if removed:
                        report["removed"].append({"path": path, "counts": brain._removed(removed)})
                    if len(body) <= brain.PAGE_CHARS:
                        target = path[: -len(suffix)]
                        while (normal := brain.path_of(target)) != target:
                            target = normal
                        if target != path:
                            report["path_changes"].append({"from": path, "to": target})
                        local.write_text(body, encoding="utf-8")
                        add(
                            {
                                "kind": "page",
                                "path": target,
                                "local": local,
                                "format": "html" if suffix in (".html", ".htm") else "markdown",
                                "status": "archived" if brain._front(body).get("archived") is True else "active",
                            }
                        )
                        continue
                    report["oversized"].append(path)
                    local.write_bytes(body.encode("utf-8"))
                    if local.stat().st_size > MAX_FILE:
                        raise ValidationError("An oversized page exceeds 100 MB as a file.")
                elif suffix in TEXT_FILES:
                    raw = local.read_bytes()
                    text, removed = brain._blank_secrets(raw.decode("utf-8", errors="replace"))
                    if removed:  # only then rewritten, so a bad byte alone never changes a file
                        if "\ufffd" in text:
                            report["decoded"].append(path)
                        local.write_text(text, encoding="utf-8")
                        report["removed"].append({"path": path, "counts": brain._removed(removed)})
                with local.open("rb") as content:
                    digest = hashlib.file_digest(content, "sha256").hexdigest()
                add(
                    {
                        "kind": "file",
                        "path": path,
                        "local": local,
                        "size": local.stat().st_size,
                        "sha256": digest,
                        "content_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
                    }
                )
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        RuntimeError,
        NotImplementedError,
        EOFError,
        zlib.error,
        UnicodeDecodeError,
    ):
        raise ValidationError("Malformed or unsupported zip.") from None
    if hidden:
        report["warnings"].append({"path": "", "reason": f"{hidden} hidden files (like .obsidian/) not imported"})
    if long_memories:
        body = "\n".join(long_memories)
        local = Path(directory) / "long-memories"
        local.write_text(body, encoding="utf-8")
        if len(body) <= brain.PAGE_CHARS:
            add(
                {
                    "kind": "page",
                    "path": "inbox/long-memories",
                    "local": local,
                    "format": "markdown",
                    "status": "active",
                }
            )
        else:
            path = "inbox/long-memories.md"
            report["oversized"].append(path)
            if local.stat().st_size > MAX_FILE:
                raise ValidationError("Long memories exceed 100 MB as a file.")
            with local.open("rb") as content:
                digest = hashlib.file_digest(content, "sha256").hexdigest()
            add(
                {
                    "kind": "file",
                    "path": path,
                    "local": local,
                    "size": local.stat().st_size,
                    "sha256": digest,
                    "content_type": "text/markdown",
                }
            )
        report["warnings"].append(
            {"path": "inbox/long-memories", "reason": f"{len(long_memories)} long memories became page lines"}
        )
    for entry in entries:
        report["counts"][{"page": "pages", "memory": "memories", "file": "files"}[entry["kind"]]] += 1
        entry["result"] = {"kind": entry["kind"], "path": entry["path"], "result": "pending"}
        report["entries"].append(entry["result"])
    return entries


def _preview(brain_id, entries, report):
    conn = db.get_db()
    caps = brain._plan(conn, brain_id)
    memories = {brain._same(m["text"]): m for m in brain.memories(brain_id)}
    active_files = {
        r["path"]: dict(r)
        for r in conn.execute("SELECT * FROM brain_files WHERE brain_id = ? AND status = 'active'", (brain_id,))
    }
    counts = {
        "pages": brain._count(conn, "brain_pages", brain_id),
        "memories": brain._count(conn, "brain_memories", brain_id),
        "files": files._used(conn, brain_id),
    }
    for e in entries:
        result = "add"
        if e["kind"] == "page":
            old = conn.execute(
                "SELECT body, format, status FROM brain_pages WHERE brain_id = ? AND path = ?", (brain_id, e["path"])
            ).fetchone()
            unchanged = (
                old
                and old["body"] == e["local"].read_bytes().decode("utf-8")
                and all(old[k] == e[k] for k in ("format", "status"))
            )
            result = "unchanged" if unchanged else "update" if old else "add"
            counts["pages"] += int(e["status"] == "active") - int(bool(old and old["status"] == "active"))
        elif e["kind"] == "memory":
            same = brain._same(e["text"])
            result = "unchanged" if same in memories else "add"
            counts["memories"] += int(same not in memories)
            if same in memories and e["locked"] and not memories[same]["locked"]:
                result = "lock"
            memories[same] = {"locked": e["locked"] or memories.get(same, {}).get("locked", False)}
        elif not files.on():
            result = "files are off"
        else:
            old = active_files.get(e["path"])
            result = "unchanged" if old and old["sha256"] == e["sha256"] else "upload"
            if result == "upload":
                counts["files"] += e["size"]
        e["result"]["planned"] = result
        for kind in counts:
            if counts[kind] > caps[kind] and kind not in report["over_cap"]:
                report["over_cap"].append(kind)


def plan(brain_id: int, zip_path, by: str) -> dict:
    with _account(brain_id), tempfile.TemporaryDirectory() as directory:
        report = _report()
        entries = _scan(zip_path, directory, by, report)
        _preview(brain_id, entries, report)
        report["complete"] = True
        return report


def _upload(brain_id, entry, source, by):
    if not files.on():
        return "files are off"
    old = (
        db.get_db()
        .execute(
            "SELECT sha256 FROM brain_files WHERE brain_id = ? AND path = ? AND status = 'active'",
            (brain_id, entry["path"]),
        )
        .fetchone()
    )
    if old and old["sha256"] == entry["sha256"]:
        return "unchanged"
    mine = (
        db.get_db()
        .execute(
            "SELECT id, staging_key FROM brain_files WHERE brain_id = ? AND path = ? AND sha256 = ? AND size = ? "
            "AND import_source = ? AND status = 'pending' ORDER BY id DESC",
            (brain_id, entry["path"], entry["sha256"], entry["size"], source),
        )
        .fetchone()
    )
    if mine:
        reserved = {
            "id": mine["id"],
            "upload": objectstore.presigned_put(
                mine["staging_key"], entry["size"], entry["sha256"], files.UPLOAD_SECONDS
            ),
        }
    else:
        item = {k: entry[k] for k in ("path", "size", "sha256", "content_type")}
        reserved = files.reserve(brain_id, [item], by=by, import_source=source)["files"][0]
    try:
        with entry["local"].open("rb") as body:
            response = httpx.put(
                reserved["upload"]["url"], headers=reserved["upload"]["headers"], content=body, timeout=120
            )
        response.raise_for_status()
    except httpx.HTTPError:
        # A provider exception can contain the signed URL: never return it.
        raise ValidationError("Could not upload a file. Try the import again.") from None
    files.done(brain_id, reserved["id"])
    return "written"


def _write_in(conn, brain_id, e, by, pass_label, reason):
    kwargs = {"by": by, "pass_label": pass_label, "reason": reason}
    if e["kind"] == "memory":
        result = brain.remember_in(conn, brain_id, [e["text"]], **kwargs)
        memory_id = (result["added"] or result["skipped"])[0]["id"]
        memory = brain._memory(conn, brain_id, memory_id)
        lock = e["locked"] and not memory["locked"]
        if lock:
            brain.update_memory_in(conn, brain_id, memory_id, locked=True, **kwargs)
        return "written" if result["added"] or lock else "unchanged"
    old = conn.execute(
        "SELECT version FROM brain_pages WHERE brain_id = ? AND path = ?", (brain_id, e["path"])
    ).fetchone()
    saved = brain.write_page_in(
        conn,
        brain_id,
        e["path"],
        e["local"].read_bytes().decode("utf-8"),
        fmt=e["format"],
        status=e["status"],
        **kwargs,
    )
    return "unchanged" if old and old["version"] == saved["version"] else "written"


def _counted(report, entry, result):
    entry["result"]["result"] = result
    report["processed"] += 1
    report["written" if result == "written" else "skipped"] += 1


def _archive_missing(brain_id, entries, source, by, label, report):
    paths = {e["path"] for e in entries if e["kind"] == "page"}
    memories = {brain._same(e["text"]) for e in entries if e["kind"] == "memory"}
    file_paths = {e["path"] for e in entries if e["kind"] == "file"}
    conn = db.get_db()
    missing = []
    for page in conn.execute("SELECT id, path FROM brain_pages WHERE brain_id = ? AND status = 'active'", (brain_id,)):
        if page["path"] not in paths:
            missing.append(("page", dict(page)))
    for memory in conn.execute(
        "SELECT id, text, locked FROM brain_memories WHERE brain_id = ? AND status = 'active'", (brain_id,)
    ):
        if brain._same(memory["text"]) not in memories and (by == brain.YOU or not memory["locked"]):
            missing.append(("memory", dict(memory)))
    for file in conn.execute(
        "SELECT id, path FROM brain_files WHERE brain_id = ? AND status = 'active' AND import_source = ?",
        (brain_id, source),
    ):
        if file["path"] not in file_paths:
            missing.append(("file", dict(file)))
    kwargs = {"by": by, "pass_label": label, "reason": "Import Markdown"}
    for offset in range(0, len(missing), CHUNK):
        with db.transaction() as conn:
            for kind, item in missing[offset : offset + CHUNK]:
                if kind == "page":
                    brain.write_page_in(
                        conn, brain_id, item["path"], status="archived", expected_id=item["id"], **kwargs
                    )
                elif kind == "memory":
                    brain.update_memory_in(conn, brain_id, item["id"], status="archived", **kwargs)
                else:
                    brain._policy_in(conn, brain_id, by, item["path"])
                    conn.execute(
                        "UPDATE brain_files SET status = 'archived', updated_at = ? "
                        "WHERE id = ? AND brain_id = ? AND status = 'active'",
                        (common.now_iso(), item["id"], brain_id),
                    )
        report["archived"] += len(missing[offset : offset + CHUNK])


def run(brain_id: int, zip_path, label: str, by: str, archive_missing: bool = False) -> dict:
    label = common.validate_short(label, "label") or Path(zip_path).name
    with _account(brain_id), tempfile.TemporaryDirectory() as directory:
        report = _report()
        report["pass"] = label
        entries = _scan(zip_path, directory, by, report)
        _preview(brain_id, entries, report)
        try:
            for offset in range(0, len(entries), CHUNK):
                chunk = entries[offset : offset + CHUNK]
                for entry in chunk:
                    if entry["kind"] == "file":
                        try:
                            result = _upload(brain_id, entry, Path(zip_path).name, by)
                        except Exception:
                            entry["result"]["result"] = "failed"
                            raise
                        _counted(report, entry, result)
                failed, finished = None, []
                with db.transaction() as conn:
                    for entry in chunk:
                        if entry["kind"] == "file":
                            continue
                        conn.execute("SAVEPOINT import_entry")
                        try:
                            result = _write_in(conn, brain_id, entry, by, label, "Import Markdown")
                        except Exception as exc:
                            conn.execute("ROLLBACK TO import_entry")
                            failed = exc
                            entry["result"]["result"] = "failed"
                            break
                        finally:
                            conn.execute("RELEASE import_entry")
                        finished.append((entry, result))
                for entry, result in finished:
                    _counted(report, entry, result)
                if failed:
                    raise failed
            off = sum(e["result"]["result"] == "files are off" for e in entries)
            if off and archive_missing:
                raise ValidationError(f"Files are off, so {off} file(s) weren't imported and nothing was archived.")
            if archive_missing:
                _archive_missing(brain_id, entries, Path(zip_path).name, by, label, report)
            report["complete"] = True
        except Exception as exc:
            # Unexpected exceptions can contain private data; expose only known refusals.
            report["error"] = (
                str(exc) if isinstance(exc, (ValidationError, ConflictError)) else "Import stopped. Try again."
            )
        return report


async def receive(request: Request, brain_id: int, by: str, *, dry_run=False, label="", archive_missing=False):
    """Spool a bounded raw request; the original zip name stays stable across uploads."""
    name = unquote(request.headers.get("X-Import-Name", "import.zip"))
    if (
        not name
        or name in (".", "..")
        or name != PurePosixPath(name).name
        or "\\" in name
        or len(name) > 200
        or any(ord(c) < 32 for c in name)
    ):
        raise HTTPException(400, "Invalid zip name", headers={"Cache-Control": "no-store"})
    # The directory is private; only this fixed, validated basename is caller supplied.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / name
        try:
            size = 0
            with path.open("wb") as dest:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "Zip upload is at most 200 MB", headers={"Cache-Control": "no-store"})
                    await asyncio.to_thread(dest.write, chunk)
            work = (
                asyncio.to_thread(plan, brain_id, path, by)
                if dry_run
                else asyncio.to_thread(run, brain_id, path, label, by, archive_missing)
            )
            task = asyncio.create_task(work)
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # A disconnected browser must not remove the zip while the worker uses it.
                await task
                raise
        finally:
            path.unlink(missing_ok=True)
