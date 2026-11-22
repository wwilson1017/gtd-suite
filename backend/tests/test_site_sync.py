"""File-site protocol, storage races and the isolated host, using the Brain FakeStore."""

import asyncio
import datetime
from types import SimpleNamespace
import hashlib
import io
import zipfile
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend import (
    backup,
    brain,
    common,
    db,
    files,
    lists,
    objectstore,
    sessions,
    site_host,
    site_routes,
    sites,
    storage,
)
from backend.common import NotFoundError, ValidationError
from backend.tests.conftest import confirm_list, turn_on
from backend.tests.test_files import store as store, item
from scripts import admin, restore_list


@pytest.fixture()
def account(store, monkeypatch):
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    lid = lists.create_list("UTC")["list_id"]
    confirm_list(lid)
    turn_on(lid, "sites")
    with site_host._cache_lock:
        site_host._cache.clear()
        site_host._cache_size = 0
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (lid,))
    return lid


@pytest.fixture()
def client(account):
    from backend.main import app

    with TestClient(app, follow_redirects=False) as client:
        yield client


def manifest(data):
    return [item(path, body) for path, body in data.items()]


def publish(store, account, data=None, **kw):
    data = data or {"index.html": b"<h1>Hello</h1>"}
    args = {"client_ref": "deck", **kw}
    first = sites.sync(account, manifest(data), **args)
    if first["status"] == "upload":
        by_hash = {hashlib.sha256(body).hexdigest(): body for body in data.values()}
        for missing in first["missing"]:
            assert store.put(missing["put"], by_hash[missing["sha256"]]) == 200
        first = sites.sync(account, manifest(data), **args)
    assert first["status"] == "published"
    return first["site"]


def blob(sha=None):
    if sha:
        return dict(db.get_db().execute("SELECT * FROM site_blobs WHERE sha256 = ?", (sha,)).fetchone())
    return dict(db.get_db().execute("SELECT * FROM site_blobs ORDER BY id LIMIT 1").fetchone())


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/index.html",
        "../index.html",
        "a/./b",
        "a//b",
        "a\\b",
        "a\x00b",
        "a\x1fb",
        "a/" + "b" * 256,
        "/".join(["a" * 250] * 5),
        "cafe\u0301.html",
        "__simplesites/unlock",
    ],
)
def test_paths_refused(account, path):
    with pytest.raises(ValidationError):
        sites.sync(account, [item(path, b"a")], client_ref="bad")
    assert db.get_db().execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 0


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [item("other", b"a")],
        [item("index.html", b"a")] * 2,
        [item("index.html", b"a", size=True)],
        [item("index.html", b"a", size=-1)],
        [item("index.html", b"a", sha256="x" * 64)],
        [item("index.html", b"a"), item("a", b"a", size=2)],
        [item("index.html" if i == 0 else str(i), b"") for i in range(1001)],
    ],
)
def test_bad_manifests(account, entries):
    with pytest.raises(ValidationError):
        sites.sync(account, entries, client_ref="bad")


def test_idempotent_reservations_reuse_and_checksum(store, account):
    data = {"index.html": b"hello", "a.txt": b"same", "b.txt": b"same"}
    first = sites.sync(account, manifest(data), client_ref="deck")
    repeat = sites.sync(account, manifest(data), client_ref="deck")
    assert first["site"]["id"] == repeat["site"]["id"]
    assert len(first["missing"]) == 2
    assert storage.used(db.get_db(), account) == 9
    up = first["missing"][0]["put"]
    assert store.put(up, b"wrong") == 400
    page = publish(store, account, data)
    store.calls.clear()
    second = sites.sync(account, manifest(data), client_ref="other")
    assert second["status"] == "published" and second["sent"] == 0 and second["reused"] == 2
    assert store.calls == []
    assert page["size"] == 13 and page["file_count"] == 3 and page["layout"] == "files"
    changed = {**data, "a.txt": b"new"}
    waiting = sites.sync(account, manifest(changed), site_id=page["id"])
    assert len(waiting["missing"]) == 1 and waiting["missing"][0]["sha256"] == hashlib.sha256(b"new").hexdigest()
    with pytest.raises(ValidationError, match="different sizes"):
        sites.sync(account, [item("index.html", b"hello", size=1)], site_id=page["id"])
    other = lists.create_list("UTC")["list_id"]
    confirm_list(other)
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (other,))
    assert len(sites.sync(other, manifest(data), client_ref="deck")["missing"]) == 2
    with pytest.raises(NotFoundError):
        sites.sync(other, manifest(data), site_id=page["id"])


def test_configuration_and_live_checks(store, account, monkeypatch):
    entries = [item("index.html", b"x")]
    for setting in ("SITES_CONTENT_DOMAIN", "FILES_S3_SECRET"):
        with monkeypatch.context() as m:
            m.delenv(setting)
            with pytest.raises(ValidationError, match="needs a content domain and a file store"):
                sites.sync(account, entries, client_ref="d")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 0 WHERE id = ?", (account,))
    with pytest.raises(ValidationError, match="A folder site needs its own address.*an AI cannot turn it on"):
        sites.sync(account, entries, client_ref="d")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (account,))

    def disable():
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET disabled_at = 'now' WHERE id = ?", (account,))

    store.hooks["HEAD"] = disable
    with pytest.raises(NotFoundError):
        sites.sync(account, entries, client_ref="d")
    assert blob()["status"] == "pending"


def test_disable_before_commit_and_delete_during_head(store, account):
    first = sites.sync(account, [item("index.html", b"x")], client_ref="deck")
    store.put(first["missing"][0]["put"], b"x")

    def remove():
        admin.main(["delete", str(account), f"--yes-delete-list-{account}", "--no-snapshot"])

    store.hooks["HEAD"] = remove
    with pytest.raises(NotFoundError):
        sites.sync(account, [item("index.html", b"x")], client_ref="deck")
    assert not store.objects
    # Even a PUT finishing after the inventory vanished is found by the daily pass.
    store.put(first["missing"][0]["put"], b"x")
    for key in store.objects:
        store.modified[key] = common.utcnow() - datetime.timedelta(days=2)
    assert sites.reconcile_blobs() == 1 and not store.objects


def test_site_pool_and_pending_limits(store, account, monkeypatch):
    with pytest.raises(ValidationError, match="25 MB"):
        sites.sync(account, [item("index.html", b"x", size=25_000_001)], client_ref="large")
    files.reserve(brain.first_brain(account), [item("large.bin", b"z", size=490_000_000)])
    with pytest.raises(ValidationError, match="storage pool"):
        sites.sync(account, [item("index.html", b"x", size=11_000_000)], client_ref="large")
    pending = sites.sync(account, [item("index.html", b"x", size=10_000_000)], client_ref="fits")
    assert pending["status"] == "upload"
    with pytest.raises(ValidationError):
        files.reserve(brain.first_brain(account), [item("too-much", b"z")])
    monkeypatch.setattr(common, "SITE_MAX_PENDING", 1)
    with pytest.raises(ValidationError, match="pending blobs"):
        sites.sync(account, [item("index.html", b"", size=0)], client_ref="zero")


def test_abandoned_and_concurrent_syncs_are_whole(store, account, client):
    old = {"index.html": b'<script src="old.js"></script>', "old.js": b"old"}
    page = publish(store, account, old)
    url = page["address"]
    assert client.get(url).content == old["index.html"]
    a = {"index.html": b"A", "a.js": b"A-js"}
    waiting = sites.sync(account, manifest(a), site_id=page["id"])
    assert client.get(url).content == old["index.html"]
    for f in waiting["missing"]:
        store.put(f["put"], next(v for v in a.values() if hashlib.sha256(v).hexdigest() == f["sha256"]))
    store.hooks["HEAD"] = lambda: publish(store, account, {"index.html": b"B", "b.js": b"B-js"}, site_id=page["id"])
    sites.sync(account, manifest(a), site_id=page["id"])
    assert client.get(url).content == b"A" and client.get(url + "a.js").content == b"A-js"
    assert client.get(url + "b.js").status_code == 404
    # The old HTML was read before the commit: its old asset can now be absent.
    assert client.get(url + "old.js").status_code == 404
    assert client.get(url).content == b"A"


def test_serving_paths_mime_etags_cache_and_stream(store, account, client, monkeypatch):
    data = {
        "index.html": b"hello",
        "dir/index.html": b"directory",
        "dir/exact": b"raw",
        "404.html": b"not here",
        "movie.mp4": b"video",
        "a%2Fb.txt": b"literal",
        "script.js": b"js",
        "big.txt": b"big-text",
    }
    page = publish(store, account, data)
    url = page["address"]
    assert client.get(url).content == b"hello"
    etag = client.get(url).headers["etag"]
    assert client.get(url, headers={"if-none-match": etag}).status_code == 304
    assert client.head(url).content == b""
    assert client.get(url + "dir").status_code == 301
    assert client.get(url + "dir?mode=present").headers["location"] == "/dir/?mode=present"
    assert client.get(url + "dir/").content == b"directory"
    assert client.get(url + "a%252Fb.txt").content == b"literal"
    for path in ("a%2Fb.txt", "a%00b.txt", "%2e%2e/index.html"):
        assert client.get(url + path).status_code == 404
    assert client.get(url + "missing").status_code == 404
    assert client.get(url + "missing").content == b"not here"
    script = client.get(url + "script.js")
    assert script.content == b"js" and script.headers["content-type"] == "text/javascript"
    movie = client.get(url + "movie.mp4")
    assert movie.status_code == 302 and movie.headers["cache-control"] == "no-store"
    query = parse_qs(urlsplit(movie.headers["location"]).query)
    assert query["X-Amz-Expires"] == ["43200"]
    assert query["response-content-disposition"][0].startswith("inline;")
    monkeypatch.setattr(site_host, "_CACHE_FILE_BYTES", 4)
    assert client.get(url + "big.txt").content == b"big-text"
    assert hashlib.sha256(b"big-text").hexdigest() not in site_host._cache
    monkeypatch.setattr(site_host, "_CACHE_FILE_BYTES", 10_000_000)
    store.calls.clear()
    client.get(url)
    assert not store.calls


def test_blob_lease_gc_rereference_and_reconcile(store, account, freeze):
    freeze("2026-11-15T12:00:00")
    page = publish(store, account)
    old = blob()
    sites.update(account, page["id"], content="# body")
    assert files.sweep() == 0
    assert blob()["unref_since"]
    freeze("2026-12-16T12:00:00")
    publish(store, account, site_id=page["id"])
    assert files.sweep() == 0 and blob()["unref_since"] is None
    sites.delete_site(account, page["id"])
    assert files.sweep() == 0
    freeze("2027-01-17T12:00:00")
    assert files.sweep() == 1 and old["object_key"] not in store.objects
    first = sites.sync(account, [item("index.html", b"x")], client_ref="new")
    up = first["missing"][0]["put"]
    stamp = parse_qs(urlsplit(up["url"]).query)["X-Amz-Date"][0]
    assert stamp == "20270117T120000Z"
    freeze("2027-01-17T12:15:59")
    assert sites.sweep_blobs() == 0
    freeze("2027-01-17T12:16:01")
    assert sites.sweep_blobs() == 1
    store.put(up, b"x")  # late arrival after the inventory row was removed
    assert sites.reconcile_blobs() == 0
    freeze("2027-01-19T12:16:01")
    assert sites.reconcile_blobs() == 1


def test_gc_wins_during_head_uses_new_key_on_retry(store, account, freeze):
    freeze("2026-11-15T12:00:00")
    entries = [item("index.html", b"x")]
    first = sites.sync(account, entries, client_ref="deck")
    old_key = blob()["object_key"]
    store.put(first["missing"][0]["put"], b"x")

    def sweep():
        freeze("2026-11-15T13:00:00")
        sites.sweep_blobs()

    store.hooks["HEAD"] = sweep
    raced = sites.sync(account, entries, client_ref="deck")
    assert raced["status"] == "upload" and raced["missing"] == []
    again = sites.sync(account, entries, client_ref="deck")
    assert again["missing"] and blob()["object_key"] != old_key


def test_reconcile_pages_keep_inventory_and_recent_orphans(store, account):
    publish(store, account)
    old = common.utcnow() - datetime.timedelta(days=2)
    store.objects.update({"sites/orphan-a": b"a", "sites/orphan-b": b"b", "sites/recent": b"c", "brain/kept": b"d"})
    store.modified.update({k: old for k in store.objects if k != "sites/recent"})
    store.page_size = 2
    assert len(list(objectstore.list("sites/"))) == 2
    assert sites.reconcile_blobs() == 2
    assert set(store.objects) == {blob()["object_key"], "sites/recent", "brain/kept"}


def test_restore_keeps_inventory_suspension_and_readopts(store, account, capsys):
    page = publish(store, account)
    before = backup.snapshot()
    sites.update(account, page["id"], content="new body")
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET suspended_at = 'taken-down' WHERE id = ?", (page["id"],))
    sites.sweep_blobs()
    inventory = blob()
    restore_list.restore(before, account, db.db_path())
    restored = sites.get_site(account, page["id"])
    assert restored["layout"] == "files" and restored["suspended_at"] == "taken-down"
    assert blob() == inventory
    sites.sweep_blobs()
    assert blob()["unref_since"] is None
    with db.transaction() as conn:
        conn.execute("DELETE FROM site_blobs")
    restore_list.restore(before, account, db.db_path())
    assert sites.get_site(account, page["id"])["status"] == "unpublished"
    assert "file bytes are no longer available" in capsys.readouterr().out


def test_zip_snapshot_body_cleanup_failures_and_slot(store, account, client, monkeypatch):
    data = {"index.html": b"html", "movie.mp4": b"video", "dir/picture.png": b"image"}
    page = publish(store, account, data)
    response = site_routes._zip(account, page["id"])
    assert site_routes._zip_slot.locked()
    with zipfile.ZipFile(response.path) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == data
    response.remove()
    assert not site_routes._zip_slot.locked()
    # Read the manifest once; a sync during the first GET cannot alter zip entries.
    store.hooks["GET"] = lambda: publish(store, account, {"index.html": b"new"}, site_id=page["id"])
    response = site_routes._zip(account, page["id"])
    with zipfile.ZipFile(response.path) as archive:
        assert set(archive.namelist()) == set(data)
    response.remove()
    store.fail.add("GET")
    with pytest.raises(objectstore.StoreError):
        site_routes._zip(account, page["id"])
    assert not site_routes._zip_slot.locked()
    assert not list(db.db_path().parent.glob("site-zip-*"))
    store.fail.clear()
    sites.update(account, page["id"], content="# body")
    with db.transaction() as conn:
        cookie = sessions.create_in(conn, account)
    # The real cookie name is kept in sessions.py.
    headers = {"X-List": str(account), "Cookie": f"{sessions.COOKIE}={cookie}"}
    link = client.post(
        f"/api/app/sites/{page['id']}/zip-link", headers={**headers, "Sec-Fetch-Site": "same-origin"}
    ).json()["url"]
    result = client.get(urlsplit(link).path)  # the ticket alone: a plain browser download
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert client.get(urlsplit(link).path).status_code == 404  # one use
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert b"body" in archive.read("index.html")
    assert not site_routes._zip_slot.locked()
    assert not list(db.db_path().parent.glob("site-zip-*"))


def test_agents_sync_and_publish_layout_switches(store, account, client):
    from backend import mcp_server, sites_agent

    token = db.get_db().execute("SELECT agent_token FROM lists WHERE id = ?", (account,)).fetchone()[0]
    path = f"/link/{token}"
    payload = {"client_ref": "command", "manifest": [item("index.html", b"hello")]}
    assert client.get(path + "?cmd=SITE_SYNC").status_code == 405
    first = client.post(path + "?cmd=SITE_SYNC", json=payload).json()
    assert first["ok"] and first["status"] == "upload"
    store.put(first["missing"][0]["put"], b"hello")
    page = client.post(path + "?cmd=SITE_SYNC", json=payload).json()["site"]
    context = mcp_server._list_id.set(account)
    try:
        # Call the registered tool wrapper's function, not only sites.update.
        body = sites_agent.site_publish("# body", id=page["id"])["page"]
        assert body["layout"] == "body" and body["format"] == "markdown" and body["size"] == 6
        sync = sites_agent.site_sync(payload["manifest"], id=page["id"])
        assert sync["status"] == "published" and sync["site"]["layout"] == "files"
    finally:
        mcp_server._list_id.reset(context)
    response = client.post(path + f"?cmd=PUBLISH&id={page['id']}", json={"format": "html"})
    assert response.status_code == 400 and "supply content" in response.json()["error"]
    assert sites.get_site(account, page["id"])["layout"] == "files"
    assert blob()["status"] == "active"
    off = lists.create_list("UTC")
    refused = client.post(f"/link/{off['agent_token']}?cmd=SITE_SYNC", json=payload)
    assert refused.status_code == 400 and "Simple Sites is off" in refused.json()["error"]


def test_gc_claim_cannot_delete_newly_reserved_hash(store, account, freeze):
    freeze("2026-11-15T12:00:00")
    page = publish(store, account)
    original = blob()
    sites.update(account, page["id"], content="body")
    sites.sweep_blobs()
    freeze("2026-12-16T12:00:00")
    store.hooks["DELETE"] = lambda: publish(store, account, site_id=page["id"])
    assert sites.sweep_blobs() == 1
    current = blob()
    assert current["status"] == "active" and current["object_key"] != original["object_key"]
    assert current["object_key"] in store.objects


def test_zip_slot_low_space_and_disconnect(store, account, monkeypatch):
    page = publish(store, account)
    response = site_routes._zip(account, page["id"])
    with pytest.raises(HTTPException) as busy:
        site_routes._zip(account, page["id"])
    assert busy.value.status_code == 429

    async def disconnected(message):
        raise OSError("client disconnected")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(OSError):
        asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, disconnected))
    assert not site_routes._zip_slot.locked()
    assert not list(db.db_path().parent.glob("site-zip-*"))
    monkeypatch.setattr(site_routes.shutil, "disk_usage", lambda path: SimpleNamespace(free=2_000_000_000))
    with pytest.raises(HTTPException) as full:
        site_routes._zip(account, page["id"])
    assert full.value.status_code == 503 and not site_routes._zip_slot.locked()


def test_restore_new_host_confirmed_expiry_and_inventory_not_snapshot(store, account, capsys):
    page = publish(store, account)
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET expires_at = '2026-01-01' WHERE id = ?", (page["id"],))
    before = backup.snapshot()
    sites.delete_site(account, page["id"])
    restore_list.restore(before, account, db.db_path())
    row = sites._row(db.get_db(), account, page["id"])
    assert sites.address(row) != page["address"]
    assert row["expires_at"] is None and row["status"] == "published"
    assert "fresh host" in capsys.readouterr().out


def test_migration_29_idempotent_and_old_body_size(account):
    page = sites.publish(account, "# body")
    with db.transaction() as conn:
        conn.execute("DROP INDEX idx_sites_client_ref")
        for column in ("layout", "size", "client_ref"):
            conn.execute(f"ALTER TABLE sites DROP COLUMN {column}")
    db._migrate(db.get_db())
    restored = sites.get_site(account, page["id"])
    assert restored["size"] == 6 and restored["layout"] == "body"
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET client_ref = 'kept' WHERE id = ?", (page["id"],))
    db._migrate(db.get_db())
    assert sites._row(db.get_db(), account, page["id"])["client_ref"] == "kept"


def test_cached_reader_bounds_bytes_and_evicts(store, account, client, monkeypatch):
    page = publish(store, account, {"index.html": b"html", "a.txt": b"aaaa", "b.txt": b"bbbb"})
    monkeypatch.setattr(site_host, "_CACHE_BYTES", 8)
    monkeypatch.setattr(site_host, "_CACHE_FILE_BYTES", 4)
    for path in ("", "a.txt", "b.txt"):
        assert client.get(page["address"] + path).status_code == 200
    assert site_host._cache_size == 8
    assert hashlib.sha256(b"html").hexdigest() not in site_host._cache
    row = blob(hashlib.sha256(b"html").hexdigest())
    store.objects[row["object_key"]] = b"x" * 100_000
    assert client.get(page["address"]).status_code == 503
    assert site_host._cache_size == 8


def test_zip_browser_owner_and_pinned_list(store, account, client):
    page = publish(store, account)
    path = f"/api/app/sites/{page['id']}/zip-link"
    assert client.post(path).status_code == 401
    assert client.get("/api/zip/not-a-ticket").status_code == 404
    with db.transaction() as conn:
        cookie = sessions.create_in(conn, account)
    headers = {"Cookie": f"{sessions.COOKIE}={cookie}"}
    assert client.post(path, headers=headers).status_code == 409
    assert client.post(path, headers={**headers, "X-List": str(account + 1)}).status_code == 409
    other = {**headers, "X-List": str(account), "Sec-Fetch-Site": "same-origin"}
    assert client.post(f"/api/app/sites/{page['id'] + 999}/zip-link", headers=other).status_code == 404
    assert not site_routes._zip_slot.locked()


def test_signatures_use_clock_after_head_and_same_lease(store, account, freeze):
    freeze("2026-11-15T12:00:00")
    store.hooks["HEAD"] = lambda: freeze("2026-11-15T12:14:00")
    response = sites.sync(account, [item("index.html", b"x"), item("a.txt", b"a")], client_ref="deck")
    for missing in response["missing"]:
        params = parse_qs(urlsplit(missing["put"]["url"]).query)
        assert params["X-Amz-Date"] == ["20261115T121400Z"]
        assert blob(missing["sha256"])["put_until"] == "2026-11-15T12:29:00.000Z"


def test_admin_delete_store_off_keeps_blob_inventory(store, account, monkeypatch):
    publish(store, account)
    monkeypatch.delenv("FILES_S3_SECRET")
    with pytest.raises(SystemExit, match="FILES_S3_"):
        admin.main(["delete", str(account), f"--yes-delete-list-{account}", "--no-snapshot"])
    assert blob()["status"] == "active" and lists.get_list(account) is not None


def test_reconcile_never_touches_another_deployments_prefix(store, monkeypatch):
    from backend import settings as app_settings

    old = common.utcnow() - datetime.timedelta(days=3)
    store.objects.update({"sites/theirs": b"a", "sites-dev/orphan": b"b"})
    store.modified.update({"sites/theirs": old, "sites-dev/orphan": old})
    monkeypatch.setenv("SITES_FILES_PREFIX", "sites-dev")
    assert app_settings.sites_files_prefix() == "sites-dev/"
    sites.reconcile_blobs()
    assert "sites/theirs" in store.objects and "sites-dev/orphan" not in store.objects
    for bad in ("Bad/Prefix", "12", "staging"):
        monkeypatch.setenv("SITES_FILES_PREFIX", bad)
        with pytest.raises(ValueError):
            app_settings.sites_files_prefix()


def test_restore_unpublishes_folder_sites_while_own_addresses_are_off(store, account, capsys):
    page = publish(store, account)
    before = backup.snapshot()
    sites.update(account, page["id"], status="unpublished")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 0 WHERE id = ?", (account,))
    restore_list.restore(before, account, db.db_path())
    assert sites.get_site(account, page["id"])["status"] == "unpublished"
    assert "own page addresses are off" in capsys.readouterr().out
