"""todo-gtd — scheduled snapshots of the database.

Each run copies the database with ``VACUUM INTO`` (compact, and consistent while the app
keeps writing) into a temp file, then renames it into ``DATA_DIR/backups/``, so a half-written
snapshot is never mistaken for a good one. Every snapshot of the last 6 hours
is kept, then the newest of each day for 7 days: longer history belongs off the volume
(docs/self-hosting.md "Backups"), and each copy kept here is the whole database again.
After each run the snapshots are dropped from the page cache (_uncache).

With SNAPSHOT_AGE_RECIPIENT set, the temp file is compressed with ``zstd`` and encrypted to
that public key with ``age``, and only the result (``….db.zst.age``) is kept; older
``….db.age`` files still list, prune and restore. The private key is never here: restoring
needs it (scripts/restore_list.py). A failed ``zstd`` or ``age`` is a failed snapshot; nothing
plain is ever kept in its place.

The app, scripts/admin.py and scripts/restore_list.py all take snapshots. A file lock
(``backups/.lock``) makes them take turns, pruning included, so two processes never share a
temp file or delete each other's.

A snapshot that fails is logged and skipped; the next run tries again. Snapshots
stop, with a warning, while free space is under a floor, so they can never
starve the live database.

# simplification: snapshots share the volume with the DB; add off-volume copy before charging
"""

import datetime
import fcntl
import logging
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from backend import common, db, settings

logger = logging.getLogger(__name__)

KEEP_ALL = datetime.timedelta(hours=6)
KEEP_DAILY = datetime.timedelta(days=7)
# Free space that must remain AFTER a snapshot the size of the live database.
MIN_FREE_BYTES = 100 * 1024 * 1024
_NAME = "todo-%Y%m%dT%H%M%SZ.db"


def backups_dir() -> Path:
    return db.db_path().parent / "backups"


def files() -> list[Path]:
    """Every snapshot, plain and encrypted, oldest first: names sort by time."""
    out = backups_dir()
    return sorted([*out.glob("todo-*.db"), *out.glob("todo-*.db.age"), *out.glob("todo-*.db.zst.age")])


def _taken(path: Path) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(path.name.removesuffix(".age").removesuffix(".zst"), _NAME).replace(
            tzinfo=datetime.timezone.utc
        )
    except ValueError:
        return None


def due_in(interval: float) -> float:
    """Seconds until the newest snapshot is `interval` old: what a starting app waits, so
    restarts (each deploy is one) cannot keep putting the next snapshot off. 0 with none."""
    taken = [t for t in map(_taken, files()) if t]
    if not taken:
        return 0.0
    return max(0.0, interval - (common.utcnow() - max(taken)).total_seconds())


def prune(now: datetime.datetime) -> None:
    """Delete snapshots past retention, and temp files a crash left behind.
    The newest snapshot is kept whatever its age, so a long pause never empties the folder."""
    out = backups_dir()
    for stale in out.glob("*.tmp"):
        stale.unlink(missing_ok=True)
    kept_days = set()
    newest_seen = False
    for path in reversed(files()):  # newest first
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


def _uncache(paths: list[Path]) -> None:
    """Ask the kernel to drop every snapshot from the page cache. Railway bills cached file
    pages as the service's memory (2.3 GB of 2.7 GB on 2026-11-14, nearly all snapshots), and a
    snapshot is read again only to restore it or copy it off. Linux only; elsewhere a no-op."""
    if not hasattr(os, "posix_fadvise"):
        return
    for path in paths:
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


def _seal(plain: Path, sealed: Path, recipient: str) -> None:
    """``plain`` compressed and encrypted into ``sealed``: zstd piped into age. Arguments as
    lists, never a shell; both must exit 0. Their own messages go to the app's stderr."""
    with open(sealed, "wb") as out:
        # --long=27: a 128 MB window, which finds the repeats a database is full of.
        zstd = subprocess.Popen(["zstd", "-3", "--long=27", "-q", "-c", str(plain)], stdout=subprocess.PIPE)
        assert zstd.stdout is not None
        try:
            age = subprocess.Popen(["age", "-r", recipient], stdin=zstd.stdout, stdout=out)
        except BaseException:
            zstd.kill()
            raise
        finally:
            zstd.stdout.close()  # age holds its own end; zstd sees a broken pipe if age dies
            zstd.wait()
        for proc in (age, zstd):
            if proc.wait():
                raise subprocess.CalledProcessError(proc.returncode, proc.args)


def _snapshot() -> Path | None:
    out = backups_dir()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one snapshot at a time, across processes; released on close
        return _locked_snapshot(out)


def _locked_snapshot(out: Path) -> Path | None:
    source = db.db_path()
    now = common.utcnow()
    prune(now)
    recipient = settings.snapshot_recipient()
    # The copy holds what the WAL holds too. Encrypting needs the plain temp file and the
    # sealed one side by side; compression is not a promise, so the sealed one counts in full.
    wal = source.with_name(source.name + "-wal")
    size = source.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    free, need = shutil.disk_usage(out).free, size * (2 if recipient else 1) + MIN_FREE_BYTES
    if free < need:
        logger.warning(
            "Snapshots are paused: %d MB free, %d MB needed. Free up or grow the volume.", free // 2**20, need // 2**20
        )
        return None
    name = now.strftime(_NAME)
    final = out / (name + ".zst.age" if recipient else name)
    if final.exists():  # names are per second; a snapshot is never overwritten
        raise FileExistsError(f"{final.name} already exists")
    plain, sealed = out / (name + ".tmp"), out / (name + ".zst.age.tmp")
    try:
        src = sqlite3.connect(source)
        try:
            # A single self-contained file in rollback-journal mode: no -wal/-shm needed to open it.
            src.execute("VACUUM INTO ?", (str(plain),))
        finally:
            src.close()
        if recipient:
            _seal(plain, sealed, recipient)
        os.replace(sealed if recipient else plain, final)
    finally:  # whatever happened, neither a plain copy nor a partial file stays
        plain.unlink(missing_ok=True)
        sealed.unlink(missing_ok=True)
    return final


def snapshot() -> Path | None:
    """Take a snapshot; the new file's path, or None when skipped or failed. Never raises."""
    try:
        path = _snapshot()
    except Exception:
        logger.exception("Snapshot failed; skipped until the next run")
        path = None
    try:  # every run, taken or not: an off-site copy reads older ones back in
        _uncache(files())
    except Exception:
        logger.exception("Dropping snapshots from the page cache failed; tried again next run")
    if path:
        logger.info("Snapshot written: %s", path.name)
    return path
