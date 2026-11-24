"""Common Brain's files: what is not a page (PDFs, images, recordings, raw exports), kept in
an object store (objectstore.py) and recorded here, one ``brain_files`` row per version.

Ordinary uploads go straight to the store; brain_import uploads zip attachments on the
server through this same flow. An upload takes three steps:

  1. reserve: the client names each file (path, size, sha256, content type). One transaction
     checks the quota and the unfinished-upload limit and inserts `pending` rows; each gets a
     15-minute presigned PUT to a staging key of its own, signed with its length and checksum,
     so the store keeps exactly the reserved bytes or nothing.
  2. the client PUTs the bytes straight to the store.
  3. done: claim the row (pending → finalizing); then, outside the write lock, HEAD the staged
     object, copy it to the row's final key and delete the staged one; then, only if the row
     is still finalizing, make it active and the path's previous active file `replaced`.
     Until then the previous version is the one served.

A download is a 5-minute presigned GET (an AI's link, brain_file_link, lasts 10).

A path keeps its case and characters, so raw names and the notes that mention them keep
working. It is never part of an object key, which is ``<list_id>/<random>``: the store holds
keys, never URLs, so the provider stays a setting.

The quota (common.file_quota_for) counts the size of every row, tombstones included, so a
reservation stays charged until its bytes are gone. `abandoned` (an upload left unfinished
for an hour, claimed by the sweeper) and `forgotten` (the person's Forget) are tombstones:
rows that hold only the keys of bytes still to delete. The sweeper deletes those bytes and
only then the row. Like cleanup.py's unused lists, a tombstone holds no content, so that is
no exception to "nothing is deleted".

No store call ever runs inside db.transaction().

# simplification: one PUT per file, at most 5 GB (500 MB from the browser, which hashes the file in memory); multipart and a streaming hash when bigger files matter
# simplification: during a finish's few seconds, the staged and the final copy both exist and are charged once
# simplification: a finish cut off by a restart stays `finalizing` until the sweeper abandons it an hour later, and the client uploads again; a copy that outlives that hour could leave its final object behind
"""

import datetime
import logging
import re
import secrets

from backend.plans import extension
from backend import brain, common, db, keys, objectstore, readlog, settings, storage, sites
from backend.common import ConflictError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)

TOMBSTONES = ("abandoned", "forgotten")
SETTLED = ("active", "archived", "replaced")  # finished uploads: their bytes are at object_key
MAX_PATH = 1024
MAX_BATCH = 100
MAX_PENDING = 200
MAX_SIZE = 5_000_000_000  # one PUT (S3's limit is 5 GiB)
BROWSER_MAX_SIZE = 500_000_000
LIST_MAX = 200  # files in brain_page_list
UPLOAD_SECONDS = 15 * 60
DOWNLOAD_SECONDS = 5 * 60
LINK_SECONDS = 10 * 60
STALE = datetime.timedelta(hours=1)
OFF = "Files are off on this server: it has no file store set up (FILES_S3_*)."
_COLS = "id, path, size, sha256, content_type, import_source, status, created_by, created_at, updated_at"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def on() -> bool:
    return settings.files_s3() is not None


def _require_on() -> None:
    if not on():
        raise ValidationError(OFF)


def file_path(path) -> str:
    """A file's path, exactly as given: folders and a name joined by '/', in any case and
    characters but control characters and '\\', with no empty, '.' or '..' part."""
    path = path if isinstance(path, str) else ""
    if (
        not path
        or len(path) > MAX_PATH
        or _CONTROL.search(path)
        or "\\" in path
        or any(part in ("", ".", "..") for part in path.split("/"))
    ):
        raise ValidationError(
            f"Invalid file path. Use folders and a name joined by '/', like "
            f"raw/2026/scan.pdf: no '..', '\\', control characters or leading "
            f"or trailing '/', {MAX_PATH} characters at most."
        )
    return path


def _size(n: float) -> str:
    """Decimal units, as the quotas are (common.FILE_*_QUOTA)."""
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1000
    raise AssertionError("The GB iteration always returns")


def _item(item, limit: int) -> dict:
    if not isinstance(item, dict):
        raise ValidationError("Each file is an object: {path, size, sha256, content_type}")
    path = file_path(item.get("path"))
    size = item.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= limit:
        raise ValidationError(
            f"{path}: size is its length in bytes, at most {_size(limit)}"
            + (" from the browser" if limit < MAX_SIZE else "")
        )
    sha256 = str(item.get("sha256") or "").lower()
    if not _SHA256.fullmatch(sha256):
        raise ValidationError(f"{path}: sha256 is the file's SHA-256, as 64 hex digits")
    content_type = str(item.get("content_type") or "").strip() or "application/octet-stream"
    if len(content_type) > 200 or _CONTROL.search(content_type):
        raise ValidationError(f"{path}: content_type is a MIME type, like application/pdf")
    return {"path": path, "size": size, "sha256": sha256, "content_type": content_type}


def _out(row) -> dict:
    return {k: row[k] for k in _COLS.split(", ")}


def _row(conn, brain_id: int, file_id) -> dict:
    row = conn.execute("SELECT * FROM brain_files WHERE id = ? AND brain_id = ?", (file_id, brain_id)).fetchone()
    if row is None:
        raise NotFoundError(f"File not found: {file_id}")
    return dict(row)


def get(brain_id: int, file_id: int) -> dict:
    row = _row(db.get_db(), brain_id, file_id)
    if row["status"] in TOMBSTONES:
        raise NotFoundError(f"File not found: {file_id}")
    return _out(row)


def _used(conn, brain_id: int) -> int:
    return storage.used(conn, brain._list_of(conn, brain_id))


# ── Upload ────────────────────────────────────────────────────────────────────


def reserve(
    brain_id: int, items: list, by: str = brain.YOU, *, browser: bool = False, import_source: str | None = None
) -> dict:
    """Reserve room for 1 to 100 files and hand back an upload for each."""
    _require_on()
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        raise ValidationError(f"Reserve 1 to {MAX_BATCH} files at a time")
    items = [_item(i, BROWSER_MAX_SIZE if browser else MAX_SIZE) for i in items]
    now = common.now_iso()
    with db.transaction() as conn:
        brain._policy_in(conn, brain_id, by, *(i["path"] for i in items))
        brain._writer_in(conn, brain_id, by)
        quota = brain._plan(conn, brain_id)
        pending = conn.execute(
            "SELECT COUNT(*) FROM brain_files WHERE list_id = ? AND status IN ('pending', 'finalizing')",
            (brain._list_of(conn, brain_id),),
        ).fetchone()[0]
        if pending + len(items) > MAX_PENDING:
            raise ValidationError(
                f"At most {MAX_PENDING} uploads can be unfinished at once: finish "
                "the others first (or wait an hour). Nothing was reserved."
            )
        used, adding = _used(conn, brain_id), sum(i["size"] for i in items)
        if used + adding > quota["files"]:
            raise ValidationError(_full(quota, used, adding))
        for i in items:
            i["staging_key"] = f"staging/{secrets.token_urlsafe(24)}"
            i["id"] = conn.execute(
                "INSERT INTO brain_files (list_id, brain_id, path, object_key, staging_key, size, sha256, "
                "content_type, import_source, status, created_by, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (
                    brain._list_of(conn, brain_id),
                    brain_id,
                    i["path"],
                    f"{brain._list_of(conn, brain_id)}/{secrets.token_urlsafe(24)}",
                    i["staging_key"],
                    i["size"],
                    i["sha256"],
                    i["content_type"],
                    import_source,
                    by,
                    now,
                    now,
                ),
            ).lastrowid
    return {
        "files": [
            {
                "id": i["id"],
                "path": i["path"],
                "size": i["size"],
                "upload": objectstore.presigned_put(i["staging_key"], i["size"], i["sha256"], UPLOAD_SECONDS),
            }
            for i in items
        ],
        "next": "PUT each file's bytes to its upload url with its headers within 15 minutes, then call done for it.",
    }


def _full(quota: dict, used: int, adding: int) -> str:
    if quota["needs_email"] and not quota["files"]:
        return "Files need a confirmed email: add yours in Settings. It's free. Nothing was reserved."
    return (
        f"That needs {_size(adding)}, and {_size(max(0, quota['files'] - used))} of the "
        f"brain's {_size(quota['files'])} for files is free.{extension.cap_note(quota['raisable'])} "
        "Forget files no longer needed to make room. Nothing was reserved."
    )


def done(brain_id: int, file_id: int) -> dict:
    """Finish an upload whose bytes are in the store. A retry after a finish returns the file."""
    _require_on()
    claimed_at = common.now_iso()
    with db.transaction() as conn:
        reservation = _row(conn, brain_id, file_id)
        if reservation["status"] in SETTLED:
            return _out(reservation)  # a retry after a finish, whatever the policy is now
        brain._policy_in(conn, brain_id, reservation["created_by"], reservation["path"])
        claimed = conn.execute(
            "UPDATE brain_files SET status = 'finalizing', updated_at = ? WHERE "
            "id = ? AND brain_id = ? AND status = 'pending'",
            (claimed_at, file_id, brain_id),
        ).rowcount
        row = _row(conn, brain_id, file_id)
    if not claimed:
        if row["status"] in SETTLED:
            return _out(row)
        if row["status"] == "finalizing":
            raise ConflictError("This upload is finishing already. Try again in a minute.")
        raise ConflictError(_CANCELLED)
    try:
        staged = objectstore.head(row["staging_key"])
        if staged is None:
            # An earlier try copied and deleted the staged bytes, then lost the answer.
            if objectstore.head(row["object_key"]) != row["size"]:
                raise ValidationError(
                    "Nothing has been uploaded for this file yet: PUT it to its upload url, then call done again."
                )
        elif staged != row["size"]:
            raise ValidationError("The uploaded bytes are not the size reserved. Upload it again.")
        else:
            objectstore.copy(row["staging_key"], row["object_key"])
            objectstore.delete(row["staging_key"])
    except ValidationError:  # objectstore.StoreError too: the client may try again
        with db.transaction() as conn:
            conn.execute(
                "UPDATE brain_files SET status = 'pending' WHERE id = ? AND brain_id = ? AND status = 'finalizing' AND updated_at = ?",
                (file_id, brain_id, claimed_at),
            )
        raise
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT path, status, created_by FROM brain_files WHERE id = ? AND brain_id = ?", (file_id, brain_id)
        ).fetchone()
        # The sweeper or Forget got there first: its tombstone owns both keys.
        if row is None or row["status"] != "finalizing":
            raise ConflictError(_CANCELLED)
        brain._policy_in(conn, brain_id, row["created_by"], row["path"])
        now = common.now_iso()
        conn.execute(
            "UPDATE brain_files SET status = 'replaced', updated_at = ? WHERE brain_id = ? "
            "AND path = ? AND status = 'active'",
            (now, brain_id, row["path"]),
        )
        conn.execute(
            "UPDATE brain_files SET status = 'active', updated_at = ? WHERE id = ? AND brain_id = ?",
            (now, file_id, brain_id),
        )
        return _out(_row(conn, brain_id, file_id))


_CANCELLED = (
    "This upload was cancelled before it finished (forgotten, or left unfinished for an hour). Upload it again."
)


# ── Reading ───────────────────────────────────────────────────────────────────


def listing(brain_id: int, folder: str = "", statuses=("active",), within: list[str] | None = None) -> list[dict]:
    """The files by path, inside `folder` (exactly, at any depth) and, for a folder-limited
    key, inside its folders (`within`)."""
    folder = str(folder or "").strip("/")
    where, params = (["brain_id = ?", f"status IN ({', '.join('?' * len(statuses))})"], [brain_id, *statuses])
    if folder:
        where.append("substr(path, 1, ?) = ?")
        params += [len(folder) + 1, folder + "/"]
    rows = db.get_db().execute(f"SELECT {_COLS} FROM brain_files WHERE {' AND '.join(where)} ORDER BY path, id", params)
    return [_out(r) for r in rows if not within or keys.inside(r["path"], within, file=True)]


def overview(brain_id: int) -> dict:
    """The app's Files panel: whether Files is on, the space used and the quota, and every
    active and archived file."""
    conn = db.get_db()
    return {
        "on": on(),
        "used": _used(conn, brain_id),
        "quota": brain._plan(conn, brain_id)["files"],
        "files": listing(brain_id, statuses=("active", "archived")),
    }


def link(brain_id: int, *, file_id: int | None = None, path=None, seconds: int = DOWNLOAD_SECONDS) -> dict:
    """A presigned download of a finished file (by id, any version) or of the file at a
    path now: {url, file}."""
    _require_on()
    if file_id is not None:
        row = (
            db.get_db()
            .execute(
                f"SELECT * FROM brain_files WHERE id = ? AND brain_id = ? AND status IN {SETTLED}", (file_id, brain_id)
            )
            .fetchone()
        )
    else:
        path = file_path(path)
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM brain_files WHERE brain_id = ? AND path = ? AND status = 'active'", (brain_id, path)
            )
            .fetchone()
        )
    if row is None:
        raise NotFoundError(f"File not found: {path if file_id is None else file_id}")
    return {
        "url": objectstore.presigned_get(
            row["object_key"], row["path"].rsplit("/", 1)[-1], row["content_type"], seconds
        ),
        "file": _out(row),
    }


def find_file(brain_id: int, target: str) -> dict | None:
    """The active file at exactly `target` (case and all), or None: the step that lets a
    [[link]] reach a file (brain.resolve's last step)."""
    row = (
        db.get_db()
        .execute(
            f"SELECT {_COLS} FROM brain_files WHERE brain_id = ? AND path = ? AND status = 'active'",
            (brain_id, str(target)),
        )
        .fetchone()
    )
    return _out(row) if row else None


# ── Archive and forget ────────────────────────────────────────────────────────


def set_status(brain_id: int, file_id: int, status: str) -> dict:
    """Archive a finished file, or bring an archived one back."""
    if status not in ("active", "archived"):
        raise ValidationError("status must be 'active' or 'archived'")
    with db.transaction() as conn:
        row = _row(conn, brain_id, file_id)
        if row["status"] not in ("active", "archived"):
            raise NotFoundError(f"File not found: {file_id}")
        if row["status"] != status:
            if (
                status == "active"
                and conn.execute(
                    "SELECT 1 FROM brain_files WHERE brain_id = ? AND path = ? AND status = 'active'",
                    (brain_id, row["path"]),
                ).fetchone()
            ):
                raise ConflictError("Another file is at that path now: archive or forget it first.")
            conn.execute(
                "UPDATE brain_files SET status = ?, updated_at = ? WHERE id = ? AND brain_id = ?",
                (status, common.now_iso(), file_id, brain_id),
            )
        return _out(_row(conn, brain_id, file_id))


def _link_gone() -> str:
    """Rows reserved before this have no upload link left that works (a minute's slack)."""
    return common.to_iso(common.utcnow() - datetime.timedelta(seconds=UPLOAD_SECONDS + 60))


def forget(brain_id: int, file_id: int) -> dict:
    """The person's Forget (the browser's alone): every version at the file's path, uploads
    in flight included, becomes a `forgotten` tombstone in one transaction. A finished
    version whose upload link has expired loses its bytes now. The rest wait an hour for
    the sweeper: a finish still copying, or a PUT on a live link, could otherwise write
    bytes back after the delete, with no row left to charge or find them."""
    with db.transaction() as conn:
        path = _row(conn, brain_id, file_id)["path"]
        settled = conn.execute(
            f"SELECT id, object_key, staging_key FROM brain_files WHERE "
            f"brain_id = ? AND path = ? AND status IN {SETTLED} AND created_at < ?",
            (brain_id, path, _link_gone()),
        ).fetchall()
        # Each version's rows in the read log (readlog.py) go too: a download link names one version.
        readlog.forget_in(
            conn,
            brain._list_of(conn, brain_id),
            "file",
            [
                r["id"]
                for r in conn.execute("SELECT id FROM brain_files WHERE brain_id = ? AND path = ?", (brain_id, path))
            ],
        )
        n = conn.execute(
            f"UPDATE brain_files SET status = 'forgotten', updated_at = ? WHERE brain_id = ? "
            f"AND path = ? AND status NOT IN {TOMBSTONES}",
            (common.now_iso(), brain_id, path),
        ).rowcount
    if not n:
        raise NotFoundError(f"File not found: {file_id}")
    _purge(settled)
    return {"forgotten": path, "versions": n}


# ── The sweeper ───────────────────────────────────────────────────────────────


def _delete(row) -> None:
    """A row's objects: its final key and, unless the sweeper has cleared it, its staging key."""
    for key in (row["staging_key"], row["object_key"]):
        if key:
            objectstore.delete(key)


def _purge(rows) -> int:
    """Delete each tombstone's bytes, then its row. A store failure stops the pass: the
    rows stay, still charged, for the next one."""
    gone = 0
    for r in rows:
        try:
            _delete(r)
        except objectstore.StoreError:
            logger.warning("Could not delete a file's bytes; the next sweep tries again")
            break
        with db.transaction() as conn:
            gone += conn.execute(
                f"DELETE FROM brain_files WHERE id = ? AND status IN {TOMBSTONES}", (r["id"],)
            ).rowcount
    return gone


def sweep() -> int:
    """The hourly cleanup (main.py). Uploads unfinished for an hour become `abandoned`, by a
    conditional claim of the sweeper's own (so of it and a finish, exactly one wins, and no
    file that went active loses its bytes); their stamp is kept, so this same pass deletes
    them. Then every tombstone an hour old loses its bytes, and then its row. Last, a
    finished upload's staging key is deleted once more after its link expires (a client
    may PUT the same bytes again after done) and then cleared."""
    if not on():
        return 0
    cutoff = common.to_iso(common.utcnow() - STALE)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE brain_files SET status = 'abandoned' WHERE status IN ('pending', 'finalizing') AND updated_at < ?",
            (cutoff,),
        )
        rows = conn.execute(
            f"SELECT id, object_key, staging_key FROM brain_files WHERE status IN "
            f"{TOMBSTONES} AND updated_at < ? ORDER BY id",
            (cutoff,),
        ).fetchall()
        restaged = conn.execute(
            f"SELECT id, staging_key FROM brain_files WHERE status IN {SETTLED} "
            "AND staging_key IS NOT NULL AND created_at < ?",
            (_link_gone(),),
        ).fetchall()
    gone = _purge(rows)
    for r in restaged:
        try:
            objectstore.delete(r["staging_key"])
        except objectstore.StoreError:
            break
        with db.transaction() as conn:
            conn.execute("UPDATE brain_files SET staging_key = NULL WHERE id = ?", (r["id"],))
    return gone + sites.sweep_blobs()


def delete_objects(list_id: int) -> int:
    """Every object of the list's files (scripts/admin.py delete, before the rows go)."""
    rows = (
        db.get_db().execute("SELECT object_key, staging_key FROM brain_files WHERE list_id = ?", (list_id,)).fetchall()
    )
    for r in rows:
        _delete(r)
    return len(rows)
