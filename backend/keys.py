"""Program keys: how a program reaches an account without the agent link.

A key is named by the person (it is the writer's label in the brain, never its
authority), shown once and stored as a SHA-256 hash, revoked on its own, and
scoped three ways:

  apps     'brain' (Common Brain only) or 'all' (every app the account has on)
  access   'read' (the read-only tools) or 'write' (every tool)
  folders  Brain keys only: page writes only inside these folders, and a narrow
           surface (mcp_server.FOLDER_KEY_TOOLS) that never shows a confidential page

A key travels only in an ``Authorization: Bearer`` header, on /mcp and the REST
API (api_v1.py), never in a path, so it never sits in a URL or a log. Like the
agent link, a disabled or removed list refuses its keys.

Staff links share these rows with kind='link': an unprefixed token accepted only
in token paths by resolve_link. They are Brain-only, default to read, and have a
separate level cap. Both kinds carry ordered brain ids validated against the account.

Named revoke, not delete: a revoked credential keeps its row.
"""

import datetime
import json
import re

from backend.plans import extension
from backend import brain, common, db, lists

PREFIX = "cb_"
MAX_PER_LIST = 20
MAX_NAME = 60
MAX_FOLDERS = 20
APPS = ("brain", "all")
ACCESS = ("read", "write")
_TOUCH_INTERVAL = datetime.timedelta(hours=1)
_COLS = "id, name, last4, apps, access, folders, brains, kind, created_at, last_used_at"


def _out(row) -> dict:
    try:
        brains = json.loads(row["brains"])
    except ValueError:
        brains = []
    return {**dict(row), "folders": json.loads(row["folders"]), "brains": brains}


def _name(name) -> str:
    name = " ".join(str(name or "").split())
    if not name or len(name) > MAX_NAME:
        raise common.ValidationError(
            f"A key needs a name, {MAX_NAME} characters at most, like the program that uses it"
        )
    # The brain's writer label: "you" is the person alone (brain.YOU), whatever the spacing.
    if re.sub(r"\s", "", name).lower() == brain.YOU:
        raise common.ValidationError(
            f"A key cannot be called '{name}': that is you. Name it after the program that uses it."
        )
    return name


def _folders(folders, app: str) -> list[str]:
    folders = [brain.path_of(f) for f in folders or []]
    if folders and app != "brain":
        raise common.ValidationError("Folders limit a Common Brain key: choose Brain only")
    if len(folders) > MAX_FOLDERS:
        raise common.ValidationError(f"At most {MAX_FOLDERS} folders")
    return sorted(set(folders))


def create(
    list_id: int, name, app: str = "brain", access: str = "read", folders=None, brains=None, kind: str = "key"
) -> dict:
    """A new key: the row, with the key itself under `key`, the only time it is shown."""
    name = _name(name)
    if app not in APPS:
        raise common.ValidationError("apps must be 'brain' or 'all'")
    if access not in ACCESS:
        raise common.ValidationError("access must be 'read' or 'write'")
    folders = _folders(folders, app)
    if kind not in ("key", "link"):
        raise common.ValidationError("kind must be key or link")
    if kind == "link" and (app != "brain" or folders):
        raise common.ValidationError("Staff links are Brain-only, without folder limits")
    key = (PREFIX if kind == "key" else "") + lists.mint_token()
    # A staff token can never accidentally look like a Bearer-only key.
    while kind == "link" and key.startswith(PREFIX):
        key = lists.mint_token()
    with db.transaction() as conn:
        if brains is None:
            main = brain.main_brains(list_id)
            brains = [main[0]["id"] if main else brain.first_brain(list_id)]
        brain.grant_in(conn, list_id, brains)
        # simplification: folders on a multi-brain key wait until asked for
        if folders and len(brains) != 1:
            raise common.ValidationError("Folders require exactly one brain")
        live = conn.execute(
            "SELECT name, kind FROM api_keys WHERE list_id = ? AND revoked_at IS NULL", (list_id,)
        ).fetchall()
        if kind == "key" and sum(r["kind"] == "key" for r in live) >= MAX_PER_LIST:
            raise common.ValidationError(f"An account holds at most {MAX_PER_LIST} keys: revoke one first")
        cap = brain.account_caps(list_id, conn)
        if kind == "link" and sum(r["kind"] == "link" for r in live) >= cap["links"]:
            raise common.ValidationError(
                f"This account holds at most {cap['links']} staff links.{extension.cap_note(cap['raisable'])}"
            )
        if name.lower() in {r["name"].lower() for r in live}:
            raise common.ValidationError(f"There is already a key called {name}")
        key_id = conn.execute(
            "INSERT INTO api_keys (list_id, name, key_hash, last4, apps, access, folders, brains, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                list_id,
                name,
                lists.hash_token(key),
                key[-4:],
                app,
                access,
                json.dumps(folders),
                json.dumps(brains),
                kind,
                common.now_iso(),
            ),
        ).lastrowid
        row = conn.execute(f"SELECT {_COLS} FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    return {**_out(row), "key": key}


def inside(path, folders: list[str], *, file: bool = False) -> bool:
    """Whether the page or (`file`) the file at `path` is inside one of a key's `folders`.
    A page's path is made canonical first (brain.path_of); a file's keeps its case and
    characters (files.file_path), so it must start with the folder exactly."""
    from backend import files  # here: files imports this module

    try:
        path = files.file_path(path) if file else brain.path_of(path)
    except common.ValidationError:
        return False
    return any(path.startswith(f + "/") for f in folders)


def list_keys(list_id: int) -> list[dict]:
    """The live keys, newest first, without the keys themselves."""
    return [
        _out(r)
        for r in db.get_db().execute(
            f"SELECT {_COLS} FROM api_keys WHERE list_id = ? AND revoked_at IS NULL ORDER BY id DESC", (list_id,)
        )
    ]


def revoke(list_id: int, key_id: int) -> None:
    """The key stops working at once. Its row stays."""
    with db.transaction() as conn:
        if not conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND list_id = ? AND revoked_at IS NULL",
            (common.now_iso(), key_id, list_id),
        ).rowcount:
            raise common.NotFoundError(f"Key not found: {key_id}")


def resolve(key: str) -> dict | None:
    return _resolve(key, "key") if key.startswith(PREFIX) else None


def resolve_link(token: str) -> dict | None:
    """A staff link is accepted only by the token-path resolver."""
    return _resolve(token, "link") if not token.startswith(PREFIX) else None


def _resolve(key: str, kind: str) -> dict | None:
    """The live key behind a Bearer value, or None: unknown, revoked, or its list
    disabled or removed (lists.live_where, as the agent link). Adds `on`, the apps it
    reaches now: those turned on for the account, within its scope. Touches the key
    and the list, so a program's use keeps an archived list, like an AI's."""
    live, params = lists.live_where()
    row = (
        db.get_db()
        .execute(
            f"SELECT list_id, {_COLS} FROM api_keys WHERE key_hash = ? AND kind = ? AND revoked_at IS NULL "
            f"AND list_id IN (SELECT id FROM lists WHERE {live})",
            (lists.hash_token(key), kind, *params),
        )
        .fetchone()
    )
    if row is None:
        return None
    # simplification: hour-granular, a read first, as sessions.touch
    if (row["last_used_at"] or "") < common.to_iso(common.utcnow() - _TOUCH_INTERVAL):
        with db.transaction() as conn:
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (common.now_iso(), row["id"]))
    lists.touch(row["list_id"])
    out = _out(row)
    active = brain.grant_in(db.get_db(), row["list_id"], row["brains"], stored=True)
    if out["folders"] and (not isinstance(out["brains"], list) or len(out["brains"]) != 1):
        active = []
    return {
        **out,
        "active_brains": active,
        "on": [a for a in lists.apps_on(row["list_id"]) if row["apps"] == "all" or a == "brain"],
    }
