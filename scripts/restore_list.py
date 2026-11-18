"""One-list repair: put ONE list's content (every app's, apps.py) back the way a snapshot has it.

    python -m scripts.restore_list backups/todo-20261004T120000Z.db --list-id 7

The snapshot is attached as a second database and, in one transaction, the
list's current rows in every content table are replaced with the snapshot's (a
table made after the snapshot is emptied for the list: it held nothing then).
Everything else is left alone: the list's own row (so its CURRENT links, email
and time zone keep working), its signed-in browsers, program keys, brain settings and
every other list. Live files keep their brains and their object-store records. Other
content added after the snapshot is gone afterwards, so a fresh snapshot of the live
database is taken first. Snapshot-only brains return archived and read-only; old
snapshots without brain ids restore into the live first brain.

Safe while the app is running: it is one more SQLite writer, and waits its turn.
Run it from the app directory with the same DATA_DIR as the app.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from backend import apps, backup, common, db, sites

# Insert parents first, delete children first (apps.content_tables is children
# first). Content only: a restore never brings back sessions or sign-in links. Common
# Brain's files are left as they are: their bytes are in the object store, which no
# snapshot holds, so the live rows are the only true record of what is there.
_TABLES = tuple(reversed([t for t in apps.content_tables() if t not in ("brain_files", "site_blobs")]))


def restore(snapshot: Path, list_id: int, live: Path) -> dict[str, int]:
    """Replace ``list_id``'s rows in ``live`` with the snapshot's; rows copied per table."""
    if not Path(snapshot).is_file():
        raise SystemExit(f"No such snapshot: {snapshot}")
    conn = sqlite3.connect(live, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("ATTACH DATABASE ? AS snap", (str(snapshot),))
        if not conn.execute("SELECT 1 FROM main.lists WHERE id = ?", (list_id,)).fetchone():
            raise SystemExit(f"List {list_id} does not exist in the live database")
        if not conn.execute("SELECT 1 FROM snap.lists WHERE id = ?", (list_id,)).fetchone():
            raise SystemExit(f"List {list_id} is not in that snapshot")
        copied = {}
        tables = [
            t
            for t in _TABLES
            if conn.execute("SELECT 1 FROM snap.sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone()
        ]
        with db.transaction(conn=conn):
            # Brain settings and live files are never restored. Only content is mapped.
            first = conn.execute(
                "SELECT id FROM main.brains WHERE list_id = ? ORDER BY id LIMIT 1", (list_id,)
            ).fetchone()[0]
            live_brains = {r[0] for r in conn.execute("SELECT id FROM main.brains WHERE list_id = ?", (list_id,))}
            brain_map = {bid: bid for bid in live_brains}
            snapshot_brains = set()
            for table in tables:
                if table.startswith("brain_") and "brain_id" in {
                    r[1] for r in conn.execute(f"PRAGMA snap.table_info({table})")
                }:
                    snapshot_brains.update(
                        r[0]
                        for r in conn.execute(
                            f"SELECT DISTINCT brain_id FROM snap.{table} WHERE list_id = ?", (list_id,)
                        )
                    )
            for bid in sorted(snapshot_brains - live_brains):
                now = common.now_iso()
                folder = f"restored-{bid}"
                suffix = 1
                while conn.execute(
                    "SELECT 1 FROM main.brains WHERE list_id = ? AND folder = ?", (list_id, folder)
                ).fetchone():
                    suffix += 1
                    folder = f"restored-{bid}-{suffix}"
                brain_map[bid] = conn.execute(
                    "INSERT INTO main.brains (list_id, name, folder, ai_access, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'read', 'archived', ?, ?)",
                    (list_id, f"Restored {now[:10]}", folder, now, now),
                ).lastrowid
            # Rows made since the snapshot are about to go: send syncing tools back to
            # a full sync (service.changes `reset`).
            conn.execute(
                f"UPDATE lists SET rev = rev + 1, sync_floor = rev + 1, changed_at = {db.NOW_SQL} WHERE id = ?",
                (list_id,),
            )
            # Sites' host, short name/grace and operator takedown are live state, never rolled back.
            live_sites = {
                r[0]: (r[1], r[2], r[3], r[4])
                for r in conn.execute(
                    "SELECT id, host, suspended_at, short_name, short_grace_until FROM main.sites WHERE list_id = ?",
                    (list_id,),
                )
            }
            # Every table is cleared: one the snapshot predates held nothing of this list then.
            for table in reversed(_TABLES):
                conn.execute(f"DELETE FROM main.{table} WHERE list_id = ?", (list_id,))
            for table in tables:
                # Only the columns both sides have, so an older snapshot still restores.
                names = [r[1] for r in conn.execute(f"PRAGMA snap.table_info({table})")]
                have = {r[1] for r in conn.execute(f"PRAGMA main.table_info({table})")}
                shared = [
                    n
                    for n in names
                    if n in have
                    and n != "brain_id"
                    and not (table == "sites" and n in ("host", "short_name", "short_grace_until"))
                ]
                cols = ", ".join(shared)
                selected = cols
                params = []
                if "brain_id" in have:
                    cols += ", brain_id"
                    if "brain_id" in names and brain_map:
                        selected += ", CASE brain_id " + " ".join("WHEN ? THEN ?" for _ in brain_map) + " END"
                        params.extend(v for pair in brain_map.items() for v in pair)
                    else:
                        selected += ", ?"
                        params.append(first)
                copied[table] = conn.execute(
                    f"INSERT INTO main.{table} ({cols}) SELECT {selected} FROM snap.{table} WHERE list_id = ?",
                    (*params, list_id),
                ).rowcount
            if "sites" in tables:
                _restore_site_state(conn, list_id, live_sites)
            # A snapshot from before card tables took Basecamp's shape restores the
            # old columns: give them Triage, Not now and Done again (_migrate step 9).
            db._card_table_kinds(conn)
        return copied
    finally:
        conn.close()


def _restore_site_state(conn, list_id: int, live_sites: dict) -> None:
    """Keep each surviving page's live host and takedown; give hostless pages a host, and mark
    data pages from a snapshot older than legacy_path as legacy (their HTML uses the path)."""
    for site_id, (host, suspended_at, short_name, grace) in live_sites.items():
        conn.execute(
            "UPDATE main.sites SET host = COALESCE(?, host), suspended_at = ?, short_name = ?, "
            "short_grace_until = ? WHERE id = ? AND list_id = ?",
            (host, suspended_at, short_name, grace, site_id, list_id),
        )
    snapshot_columns = {r[1] for r in conn.execute("PRAGMA snap.table_info(sites)")}
    if "short_name" in snapshot_columns:
        for row in conn.execute("SELECT id FROM snap.sites WHERE list_id = ? AND short_name IS NOT NULL", (list_id,)):
            if row[0] not in live_sites:
                print(f"Warning: restored site {row[0]} has no short name; snapshot names are not reclaimed.")
    if "size" not in snapshot_columns:
        conn.execute("UPDATE main.sites SET size = bytes WHERE list_id = ?", (list_id,))
    if "legacy_path" not in snapshot_columns:
        conn.execute(f"UPDATE main.sites SET legacy_path = 1 WHERE list_id = ? AND {sites.LEGACY_PATH_SQL}", (list_id,))
    if conn.execute("SELECT email_verified_at FROM main.lists WHERE id = ?", (list_id,)).fetchone()[0]:
        conn.execute("UPDATE main.sites SET expires_at = NULL WHERE list_id = ?", (list_id,))
    missing = conn.execute(
        "SELECT DISTINCT s.id FROM main.sites s JOIN main.site_files f ON f.site_id = s.id "
        "WHERE s.list_id = ? AND NOT EXISTS (SELECT 1 FROM main.site_blobs b "
        "WHERE b.list_id = s.list_id AND b.sha256 = f.sha256 AND b.status = 'active')",
        (list_id,),
    ).fetchall()
    for row in missing:
        conn.execute("UPDATE main.sites SET status = 'unpublished' WHERE id = ?", (row[0],))
        print(f"Warning: site {row[0]} restored unpublished because file bytes are no longer available.")
    for row in conn.execute(
        "SELECT id, name FROM main.sites WHERE list_id = ? AND kind = 'page' AND host IS NULL", (list_id,)
    ).fetchall():
        while True:
            try:
                conn.execute("UPDATE main.sites SET host = ? WHERE id = ?", (sites._new_host(row[1]), row[0]))
                print(f"Warning: restored site {row[0]} has a fresh host address.")
                break
            except sqlite3.IntegrityError as exc:
                if "sites.host" not in str(exc):
                    raise


def main(argv=None) -> None:
    assert __doc__ is not None  # This module defines the CLI description in its docstring.
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--list-id", type=int, required=True, help="the list's id (scripts.admin find --link=<its agent link>)"
    )
    args = parser.parse_args(argv)

    live = db.db_path()
    if not live.is_file():
        raise SystemExit(f"No database at {live}; is DATA_DIR set as it is for the app?")
    list_id = args.list_id
    before = backup.snapshot()
    if before is None:
        raise SystemExit("Could not snapshot the live database first; nothing was changed")
    copied = restore(args.snapshot, list_id, live)
    print(f"List {list_id} restored from {args.snapshot.name}: " + ", ".join(f"{n} {t}" for t, n in copied.items()))
    print(f"The state just before this is in {before}")


if __name__ == "__main__":
    main(sys.argv[1:])
