"""Restore drill: show that a snapshot can be restored, without touching anything live.

    python -m scripts.restore_drill todo-20261004T120000Z.db.zst.age --same-as nas-copy.db.zst.age

Run it on your own machine, from a checkout, on a snapshot you downloaded from an off-site
copy. In a private folder beside the snapshot, removed when the drill ends (pass or fail), it:

1. with ``--same-as``, checks a second copy of the snapshot is the same file (SHA-256);
2. decrypts it (you type the private key, which goes to ``age`` and nowhere else) and
   requires SQLite's integrity check to answer ``ok``;
3. starts the app on the restored database, on 127.0.0.1, with no setting but ``DATA_DIR``,
   so no file store, backup bucket or mail is reachable from it, and gets ``/healthz``;
4. with the app stopped, removes one todo from one list and puts that list back with
   ``scripts.restore_list``, then checks the todo is back and another list is unchanged.

It does not cover the bytes of Common Brain's files and Simple Sites' files: those are in
the object store, and no snapshot holds them.
"""

import argparse
import hashlib
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from scripts import restore_list

ROOT = Path(__file__).resolve().parent.parent
_START_SECONDS = 120  # the first start on an old snapshot also runs the schema steps


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _todos(path: Path, list_id: int, columns: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT {columns} FROM todos WHERE list_id = ? ORDER BY id", (list_id,)).fetchall()
    finally:
        conn.close()


def _healthz(data: Path, env: dict[str, str]) -> None:
    """Start the app on ``data`` and get /healthz; the app is stopped again either way."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with (data / "app.log").open("w") as log:
        app = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + _START_SECONDS
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as res:
                        if res.status == 200:
                            return
                except OSError:
                    pass
                if app.poll() is not None or time.monotonic() > deadline:
                    tail = (data / "app.log").read_text(errors="replace")[-2000:]
                    raise SystemExit(f"FAIL: the app did not answer /healthz on the restored database\n{tail}")
                time.sleep(0.5)
        finally:
            app.terminate()
            app.wait()


def _one_list(plain: Path, data: Path, env: dict[str, str]) -> str:
    """Remove a todo from the fullest list in ``data``, restore that list from ``plain``, compare."""
    live = data / "todo.db"
    conn = sqlite3.connect(live)
    try:
        counts = conn.execute(
            "SELECT list_id, COUNT(*) FROM todos GROUP BY list_id ORDER BY COUNT(*) DESC LIMIT 2"
        ).fetchall()
        if not counts:
            return "skipped: the snapshot holds no todos"
        list_id = counts[0][0]
        other = counts[1][0] if len(counts) > 1 else None
        want = _todos(plain, list_id, "id, title, status")
        other_before = _todos(live, other, "id, title, status, rev") if other else []
        conn.execute("DELETE FROM todos WHERE id = (SELECT MAX(id) FROM todos WHERE list_id = ?)", (list_id,))
        conn.commit()
    finally:
        conn.close()
    if _todos(live, list_id, "id, title, status") == want:
        raise SystemExit("FAIL: could not remove a todo to restore")
    done = subprocess.run(
        [sys.executable, "-m", "scripts.restore_list", str(plain), "--list-id", str(list_id)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if done.returncode:
        raise SystemExit(f"FAIL: restore_list refused\n{done.stderr[-2000:]}")
    if _todos(live, list_id, "id, title, status") != want:
        raise SystemExit("FAIL: the list's todos are not what the snapshot has")
    if other and _todos(live, other, "id, title, status, rev") != other_before:
        raise SystemExit("FAIL: restoring one list changed another")
    return f"{len(want)} todos back" + (", another list unchanged" if other else ", no second list to compare")


def drill(snapshot: Path, same_as: Path | None, identity: str | None) -> None:
    if not snapshot.is_file():
        raise SystemExit(f"No such snapshot: {snapshot}")
    if same_as:
        if _sha256(snapshot) != _sha256(same_as):
            raise SystemExit(f"FAIL: {same_as.name} is not the same file as {snapshot.name}")
        print("1. Both copies are the same file (SHA-256)")
    else:
        print("1. Skipped: no second copy given (--same-as)")
    # Beside the snapshot, not in /tmp: a confined `age` (a snap) can read only where you can.
    with tempfile.TemporaryDirectory(prefix="restore-drill-", dir=snapshot.resolve().parent) as work:
        folder = Path(work)
        if snapshot.name.endswith(".age"):
            plain = restore_list._decrypt(snapshot, identity or "-", folder)
        else:
            plain = Path(shutil.copy(snapshot, folder / "snapshot.db"))
        conn = sqlite3.connect(plain)
        try:
            answer = conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            raise SystemExit(f"FAIL: not a database: {exc}") from None
        finally:
            conn.close()
        if answer != [("ok",)]:
            raise SystemExit(f"FAIL: integrity check: {answer[:5]}")
        print(f"2. Restored to a {plain.stat().st_size / 1e6:.0f} MB database; integrity check ok")

        data = folder / "data"
        data.mkdir()
        shutil.copy(plain, data / "todo.db")
        # Nothing but DATA_DIR: with the real file-store settings, the app's clean-up would
        # compare the real bucket against this old database and could delete real files.
        env = {"DATA_DIR": str(data), "PATH": os.environ.get("PATH", "")}
        _healthz(data, env)
        print("3. The app starts on it and answers /healthz")
        print(f"4. One-list restore: {_one_list(plain, data, env)}")
    print(f"PASS: {snapshot.name}. Every plain copy made by the drill is deleted.")


def main(argv=None) -> None:
    assert __doc__ is not None
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--same-as", type=Path, help="a second copy of the same snapshot, from another place")
    parser.add_argument("--identity", help="the age key file; without it you type the key in")
    args = parser.parse_args(argv)
    drill(args.snapshot, args.same_as, args.identity)


if __name__ == "__main__":
    main(sys.argv[1:])
