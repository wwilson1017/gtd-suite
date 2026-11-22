"""todo-gtd — scheduled snapshots of the database.

Each run takes an SQLite online backup (consistent while the app keeps writing)
into a temp file, then renames it into ``DATA_DIR/backups/``, so a half-written
snapshot is never mistaken for a good one. Every snapshot of the last 6 hours
is kept, then the newest of each day for 7 days: longer history belongs off the volume
(docs/self-hosting.md "Backups"), and each copy kept here is the whole database again.
After each run the snapshots are dropped from the page cache (_uncache).

A snapshot that fails is logged and skipped; the next run tries again. Snapshots
stop, with a warning, while free space is under a floor, so they can never
starve the live database.

# simplification: snapshots share the volume with the DB; add off-volume copy before charging
"""

import datetime
import logging
import os
import shutil
import sqlite3
from pathlib import Path

from backend import common, db

logger = logging.getLogger(__name__)

KEEP_ALL = datetime.timedelta(hours=6)
KEEP_DAILY = datetime.timedelta(days=7)
# Free space that must remain AFTER a snapshot the size of the live database.
MIN_FREE_BYTES = 100 * 1024 * 1024
_NAME = "todo-%Y%m%dT%H%M%SZ.db"


def backups_dir() -> Path:
    return db.db_path().parent / "backups"


def _taken(path: Path) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(path.name, _NAME).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def prune(now: datetime.datetime) -> None:
    """Delete snapshots past retention, and temp files a crash left behind.
    The newest snapshot is kept whatever its age, so a long pause never empties the folder."""
    out = backups_dir()
    for stale in out.glob("*.tmp"):
        stale.unlink(missing_ok=True)
    kept_days = set()
    newest_seen = False
    for path in sorted(out.glob("todo-*.db"), reverse=True):  # newest first: names sort by time
        taken = _taken(path)
        if taken is None:
            continue
        if not newest_seen:
            newest_seen = True
            continue
        if now - taken <= KEEP_ALL:
            continue
        if now - taken <= KEEP_DAILY and taken.date() not in kept_days:
            kept_days.add(taken.date())
            continue
        path.unlink(missing_ok=True)


def _uncache(out: Path) -> None:
    """Ask the kernel to drop every snapshot from the page cache. Railway bills cached file
    pages as the service's memory (2.3 GB of 2.7 GB on 2026-11-14, nearly all snapshots), and a
    snapshot is read again only to restore it or copy it off. Linux only; elsewhere a no-op."""
    if not hasattr(os, "posix_fadvise"):
        return
    for path in out.glob("todo-*.db"):
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            continue
        try:
            os.fsync(fd)  # dirty pages cannot be dropped until written
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass
        finally:
            os.close(fd)


def _snapshot() -> Path | None:
    source = db.db_path()
    out = backups_dir()
    out.mkdir(parents=True, exist_ok=True)
    now = common.utcnow()
    prune(now)
    free, need = shutil.disk_usage(out).free, source.stat().st_size + MIN_FREE_BYTES
    if free < need:
        logger.warning(
            "Snapshots are paused: %d MB free, %d MB needed. Free up or grow the volume.", free // 2**20, need // 2**20
        )
        return None
    final = out / now.strftime(_NAME)
    if final.exists():  # names are per second; a snapshot is never overwritten
        raise FileExistsError(f"{final.name} already exists")
    tmp = out / (final.name + ".tmp")
    src, dst = sqlite3.connect(source), sqlite3.connect(tmp)
    try:
        src.backup(dst)
        # A single self-contained file: no -wal/-shm needed to open it read-only.
        dst.execute("PRAGMA journal_mode=DELETE")
    finally:
        dst.close()
        src.close()
    os.replace(tmp, final)
    return final


def snapshot() -> Path | None:
    """Take a snapshot; the new file's path, or None when skipped or failed. Never raises."""
    try:
        path = _snapshot()
    except Exception:
        logger.exception("Snapshot failed; skipped until the next run")
        path = None
    try:  # every run, taken or not: an off-site copy reads older ones back in
        _uncache(backups_dir())
    except Exception:
        logger.exception("Dropping snapshots from the page cache failed; tried again next run")
    if path:
        logger.info("Snapshot written: %s", path.name)
    return path
