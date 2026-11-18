"""Common Brain's files (files.py, objectstore.py): reserve, upload, finish, download, archive,
forget and sweep, with the object store faked at the httpx boundary (FakeStore), and SigV4
checked against AWS's own published examples."""

import base64
import contextlib
from xml.etree import ElementTree
import datetime
import hashlib
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx2 as httpx
import pytest

from backend import brain, common, db, files, lists, logscrub, objectstore
from backend.common import ConflictError, NotFoundError, ValidationError
from backend.tests.conftest import confirm_list
from backend.tests.test_keys import acct, bearer, new_key, rest  # noqa: F401 (fixtures)
from backend.tests.test_mcp import anyio_backend, app, browser, http  # noqa: F401 (fixtures)

BUCKET = "cb"
MB = 1_000_000
CFG = {
    "ENDPOINT": "https://store.example",
    "BUCKET": BUCKET,
    "KEY_ID": "key-id",
    "SECRET": "shh",
    "REGION": "us-east-1",
}


class FakeStore:
    """A bucket in a dict, behind httpx.request: the server's HEAD, copy (a PUT with
    x-amz-copy-source) and DELETE, and `put` for a client's presigned upload, which it
    checks as S3 does: the signature over the sent length and checksum, then the bytes
    against the checksum. Every server call asserts the write lock is free, so no store
    call runs inside a transaction. `hooks[method]` runs once before the next such call
    (to race it); a method in `fail` answers 500, after its hook."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.modified: dict[str, datetime.datetime] = {}
        self.page_size = 1000
        self.calls: list[tuple[str, str]] = []
        self.hooks: dict = {}
        self.fail: set[str] = set()

    @staticmethod
    def _key(path: str) -> str:
        assert path.startswith(f"/{BUCKET}/")
        return unquote(path[len(BUCKET) + 2 :])

    def request(self, method, url, headers=None, timeout=None):
        assert not db.write_lock().locked(), f"a store {method} inside a transaction"
        assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=key-id/")
        key, req = self._key(urlsplit(url).path), httpx.Request(method, url)
        self.calls.append((method, key))
        if hook := self.hooks.pop(method, None):
            hook()
        if method in self.fail:
            return httpx.Response(500, request=req)
        if method == "GET":
            params = dict(parse_qsl(urlsplit(url).query))
            if params.get("list-type") == "2":
                keys = sorted(k for k in self.objects if k.startswith(params["prefix"]))
                keys = [k for k in keys if k > params.get("continuation-token", "")]
                selected = keys[: self.page_size]
                root = ElementTree.Element("ListBucketResult", xmlns="http://s3.amazonaws.com/doc/2006-03-01/")
                for name in selected:
                    entry = ElementTree.SubElement(root, "Contents")
                    ElementTree.SubElement(entry, "Key").text = name
                    ElementTree.SubElement(entry, "LastModified").text = common.to_iso(
                        self.modified.get(name, common.utcnow())
                    )
                more = len(selected) < len(keys)
                ElementTree.SubElement(root, "IsTruncated").text = "true" if more else "false"
                if more:
                    ElementTree.SubElement(root, "NextContinuationToken").text = selected[-1]
                return httpx.Response(200, content=ElementTree.tostring(root), request=req)
            return (
                httpx.Response(200, content=self.objects[key], request=req)
                if key in self.objects
                else httpx.Response(404, request=req)
            )
        if method == "HEAD":
            if key not in self.objects:
                return httpx.Response(404, request=req)
            if headers.get("accept-encoding") != "identity":  # as R2 does: gzipped, so no length
                return httpx.Response(200, headers={"content-encoding": "gzip"}, request=req)
            return httpx.Response(200, headers={"content-length": str(len(self.objects[key]))}, request=req)
        if method == "PUT":
            source = self._key(unquote(headers["x-amz-copy-source"]))
            if source not in self.objects:
                return httpx.Response(404, request=req)
            self.objects[key] = self.objects[source]
            return httpx.Response(200, content=b"<CopyObjectResult/>", request=req)
        assert method == "DELETE"
        self.objects.pop(key, None)
        return httpx.Response(204, request=req)

    @contextlib.contextmanager
    def stream(self, method, url, headers=None, timeout=None):
        response = self.request(method, url, headers, timeout)
        try:
            yield response
        finally:
            response.close()

    def put(self, upload: dict, body: bytes) -> int:
        url = urlsplit(upload["url"])
        params = dict(parse_qsl(url.query))
        signature = params.pop("X-Amz-Signature")
        sent = {"host": url.netloc, "content-length": str(len(body)), **upload["headers"]}
        sent = {k: v for k, v in sent.items() if k in params["X-Amz-SignedHeaders"].split(";")}
        cfg = {k.lower(): v for k, v in CFG.items()}
        if (
            objectstore._signature(cfg, "PUT", url.path, params, sent, "UNSIGNED-PAYLOAD", params["X-Amz-Date"])
            != signature
        ):
            return 403
        if base64.b64encode(hashlib.sha256(body).digest()).decode() != upload["headers"]["x-amz-checksum-sha256"]:
            return 400
        self.objects[self._key(url.path)] = body
        self.modified[self._key(url.path)] = common.utcnow()
        return 200


@pytest.fixture()
def store(todo_db, monkeypatch):
    for name, value in CFG.items():
        monkeypatch.setenv(f"FILES_S3_{name}", value)
    fake = FakeStore()
    monkeypatch.setattr(objectstore.httpx, "request", fake.request)
    monkeypatch.setattr(objectstore.httpx, "stream", fake.stream)
    return fake


@pytest.fixture()
def L(store) -> int:
    """A list with a confirmed email: Free's 500 MB for files."""
    list_id = lists.create_list("UTC")["list_id"]
    confirm_list(list_id)
    return list_id


def item(path: str, body: bytes, **kw) -> dict:
    return {
        "path": path,
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "content_type": "application/pdf",
        **kw,
    }


def big(path: str, size: int) -> dict:
    return {"path": path, "size": size, "sha256": "0" * 64}


def staged(store, list_id: int, path: str, body: bytes) -> int:
    """Reserve and PUT: the upload's id, ready for done."""
    r = files.reserve(brain.first_brain(list_id), [item(path, body)])["files"][0]
    assert store.put(r["upload"], body) == 200
    return r["id"]


def upload(store, list_id: int, path: str, body: bytes) -> dict:
    return files.done(brain.first_brain(list_id), staged(store, list_id, path, body))


def status(file_id: int) -> str | None:
    row = db.get_db().execute("SELECT status FROM brain_files WHERE id = ?", (file_id,)).fetchone()
    return row and row["status"]


def later(freeze, hours: float) -> None:
    freeze(common.to_iso(common.utcnow() + datetime.timedelta(hours=hours))[:-1])


def copies(store) -> int:
    return sum(m == "PUT" for m, _ in store.calls)


# ── Signing ───────────────────────────────────────────────────────────────────

AWS = {
    "endpoint": "https://examplebucket.s3.amazonaws.com",
    "key_id": "AKIAIOSFODNN7EXAMPLE",
    "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "region": "us-east-1",
}


def test_sigv4_matches_aws_presigned_url_example(freeze):
    # docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
    freeze("2013-05-24T00:00:00")
    assert objectstore._presign(AWS, "GET", "/test.txt", 86400) == (
        "https://examplebucket.s3.amazonaws.com/test.txt?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        "&X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request"
        "&X-Amz-Date=20130524T000000Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host"
        "&X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )


def test_sigv4_matches_aws_header_example():
    # docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html, GET Object
    headers = {
        "host": "examplebucket.s3.amazonaws.com",
        "range": "bytes=0-9",
        "x-amz-content-sha256": objectstore._EMPTY,
        "x-amz-date": "20130524T000000Z",
    }
    assert objectstore._signature(AWS, "GET", "/test.txt", {}, headers, objectstore._EMPTY, "20130524T000000Z") == (
        "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


def test_the_presigned_put_signs_the_length_and_the_checksum(store, L):
    body = b"%PDF the scan"
    up = files.reserve(brain.first_brain(L), [item("raw/scan.pdf", body)])["files"][0]["upload"]
    params = dict(parse_qsl(urlsplit(up["url"]).query))
    assert params["X-Amz-SignedHeaders"] == "content-length;host;x-amz-checksum-sha256"
    assert params["X-Amz-Expires"] == "900" and urlsplit(up["url"]).path.startswith("/cb/staging/")
    assert up["headers"] == {"x-amz-checksum-sha256": base64.b64encode(hashlib.sha256(body).digest()).decode()}
    assert store.put(up, body + b"!") == 403  # another length: the signature fails
    assert store.put(up, body.upper()) == 400  # the same length, other bytes: the checksum fails
    assert store.objects == {} and store.put(up, body) == 200


def test_a_download_names_the_file_in_rfc_5987(store, L):
    upload(store, L, "raw/Résumé – 2026.pdf", b"cv")
    url = files.link(brain.first_brain(L), path="raw/Résumé – 2026.pdf")["url"]
    params = dict(parse_qsl(urlsplit(url).query))
    assert params["response-content-disposition"] == (
        "attachment; filename*=UTF-8''R%C3%A9sum%C3%A9%20%E2%80%93%202026.pdf"
    )
    assert params["response-content-type"] == "application/pdf" and params["X-Amz-Expires"] == "300"


def test_the_fake_refuses_a_store_call_inside_a_transaction(store):
    with pytest.raises(AssertionError, match="inside a transaction"):
        with db.transaction():
            objectstore.head("staging/x")


# ── Reserving ─────────────────────────────────────────────────────────────────


def test_paths_keep_their_case_and_characters():
    for good in ("raw/Keep/IMG 0001 (1).JPG", "Notes..txt", "raw/日本/ファイル.pdf"):
        assert files.file_path(good) == good
    for bad in ("", "/raw/x", "raw/x/", "raw//x", "raw/../x", "./x", "raw\\x", "raw/\x00x", "x" * 1025, None, 7):
        with pytest.raises(ValidationError, match="Invalid file path"):
            files.file_path(bad)


def test_a_batch_is_one_to_a_hundred_and_all_or_nothing(store, L):
    assert len(files.reserve(brain.first_brain(L), [big(f"f/{i}", 1) for i in range(100)])["files"]) == 100
    for items in ([], [big(f"g/{i}", 1) for i in range(101)], [big("ok", 1), big("bad/", 1)]):
        with pytest.raises(ValidationError):
            files.reserve(brain.first_brain(L), items)
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_files").fetchone()[0] == 100


def test_at_most_two_hundred_unfinished_uploads(store, L):
    for batch in range(2):
        files.reserve(brain.first_brain(L), [big(f"{batch}/{i}", 1) for i in range(100)])
    with pytest.raises(ValidationError, match="At most 200 uploads"):
        files.reserve(brain.first_brain(L), [big("one-more", 1)])


def test_files_are_off_without_a_store(todo_db):
    list_id = lists.create_list("UTC")["list_id"]
    assert not files.on() and files.overview(brain.first_brain(list_id))["on"] is False
    with pytest.raises(ValidationError, match="Files are off"):
        files.reserve(brain.first_brain(list_id), [item("a.txt", b"a")])
    assert files.sweep() == 0


# ── Finishing ─────────────────────────────────────────────────────────────────


def test_done_copies_the_staged_bytes_and_a_retry_returns_the_file(store, L):
    file_id = staged(store, L, "raw/scan.pdf", b"bytes")
    row = db.get_db().execute("SELECT * FROM brain_files WHERE id = ?", (file_id,)).fetchone()
    assert row["object_key"].startswith(f"{L}/") and "scan" not in row["object_key"]
    first = files.done(brain.first_brain(L), file_id)
    assert first["status"] == "active" and store.objects == {row["object_key"]: b"bytes"}
    assert files.done(brain.first_brain(L), file_id) == first and copies(store) == 1


def test_a_retried_done_returns_the_file_after_the_brain_turns_read_only(store, L):
    bid = brain.first_brain(L)
    done, waiting = files.reserve(bid, [item("raw/a.pdf", b"a"), item("raw/b.pdf", b"b")], by="claude")["files"]
    store.put(done["upload"], b"a")
    store.put(waiting["upload"], b"b")
    first = files.done(bid, done["id"])
    brain.update_brain(L, bid, ai_access="read")
    assert files.done(bid, done["id"]) == first
    with pytest.raises(ValidationError, match="read-only"):
        files.done(bid, waiting["id"])
    assert status(waiting["id"]) == "pending"


def test_done_refuses_a_missing_upload_and_can_be_tried_again(store, L):
    r = files.reserve(brain.first_brain(L), [item("raw/scan.pdf", b"bytes")])["files"][0]
    with pytest.raises(ValidationError, match="Nothing has been uploaded"):
        files.done(brain.first_brain(L), r["id"])
    assert status(r["id"]) == "pending" and copies(store) == 0
    store.put(r["upload"], b"bytes")
    assert files.done(brain.first_brain(L), r["id"])["status"] == "active"


def test_a_delete_whose_answer_was_lost_finishes_on_the_retry(store, L):
    file_id = staged(store, L, "raw/scan.pdf", b"bytes")
    staging = db.get_db().execute("SELECT staging_key FROM brain_files WHERE id = ?", (file_id,)).fetchone()[0]
    store.hooks["DELETE"] = lambda: store.objects.pop(staging)  # deleted, then a 500
    store.fail.add("DELETE")
    with pytest.raises(objectstore.StoreError):
        files.done(brain.first_brain(L), file_id)
    assert status(file_id) == "pending"
    store.fail.clear()
    assert files.done(brain.first_brain(L), file_id)["status"] == "active" and copies(store) == 1


def test_two_concurrent_dones_copy_once(store, L):
    file_id = staged(store, L, "raw/scan.pdf", b"bytes")
    refused = []

    def second():
        with pytest.raises(ConflictError, match="finishing already") as e:
            files.done(brain.first_brain(L), file_id)
        refused.append(e)

    store.hooks["HEAD"] = second
    assert files.done(brain.first_brain(L), file_id)["status"] == "active"
    assert refused and copies(store) == 1


def test_the_previous_version_is_served_until_the_commit(store, L):
    v1 = upload(store, L, "raw/scan.pdf", b"one")
    v2 = staged(store, L, "raw/scan.pdf", b"two!")
    seen = []
    store.hooks["DELETE"] = lambda: seen.append(files.link(brain.first_brain(L), path="raw/scan.pdf")["file"]["id"])
    files.done(brain.first_brain(L), v2)
    assert seen == [v1["id"]] and files.link(brain.first_brain(L), path="raw/scan.pdf")["file"]["id"] == v2
    assert status(v1["id"]) == "replaced"
    assert files.link(brain.first_brain(L), file_id=v1["id"])["file"]["size"] == 3  # an old version still downloads


def test_two_racing_replacements_last_wins_with_one_active_row(store, L):
    upload(store, L, "notes.txt", b"v1")
    a, b = staged(store, L, "notes.txt", b"A"), staged(store, L, "notes.txt", b"B")
    store.hooks["PUT"] = lambda: files.done(brain.first_brain(L), b)  # b commits while a is copying
    files.done(brain.first_brain(L), a)
    active = db.get_db().execute("SELECT id FROM brain_files WHERE path = 'notes.txt' AND status = 'active'").fetchall()
    assert [r["id"] for r in active] == [a] and status(b) == "replaced"


# ── Forget, the sweeper and the races ─────────────────────────────────────────


def test_forget_during_a_finish_leaves_the_tombstone_owning_both_keys(store, L, freeze):
    freeze("2026-10-31T12:00:00")
    old = upload(store, L, "raw/scan.pdf", b"old")
    later(freeze, 0.5)  # its upload link has expired
    file_id = staged(store, L, "raw/scan.pdf", b"new")
    store.hooks["PUT"] = lambda: files.forget(brain.first_brain(L), file_id)  # while the copy runs
    with pytest.raises(ConflictError, match="cancelled"):
        files.done(brain.first_brain(L), file_id)
    assert status(old["id"]) is None  # finished, its link expired: its bytes went at once
    assert status(file_id) == "forgotten" and len(store.objects) == 1  # the copy landed
    later(freeze, 2)
    store.fail.add("DELETE")  # a crash before the delete: the row stays, still charged
    assert files.sweep() == 0 and status(file_id) == "forgotten"
    store.fail.clear()
    assert files.sweep() == 1 and status(file_id) is None and store.objects == {}


def test_the_sweeper_wins_against_a_late_done(store, L, freeze):
    freeze("2026-10-31T12:00:00")
    file_id = staged(store, L, "raw/scan.pdf", b"bytes")
    later(freeze, 1.5)
    assert files.sweep() == 1 and store.objects == {}
    with pytest.raises(NotFoundError):
        files.done(brain.first_brain(L), file_id)


def test_a_sweep_during_a_finish_wins_and_no_active_file_loses_its_bytes(store, L, freeze):
    freeze("2026-10-31T12:00:00")
    live = upload(store, L, "raw/scan.pdf", b"live")
    file_id = staged(store, L, "raw/scan.pdf", b"next")

    def sweep_now():  # the finish's claim is over an hour old by now
        later(freeze, 2)
        assert files.sweep() == 1

    store.hooks["HEAD"] = sweep_now
    with pytest.raises(ValidationError):
        files.done(brain.first_brain(L), file_id)
    assert status(file_id) is None and status(live["id"]) == "active"
    assert list(store.objects.values()) == [b"live"]
    assert files.sweep() == 0 and status(live["id"]) == "active"  # nothing settled is swept


def test_an_upload_link_still_live_never_outlasts_the_charge(store, L, freeze):
    freeze("2026-10-31T12:00:00")
    r = files.reserve(brain.first_brain(L), [item("a.txt", b"abc")])["files"][0]
    store.put(r["upload"], b"abc")
    forgotten = files.done(brain.first_brain(L), r["id"])
    assert store.put(r["upload"], b"abc") == 200  # the link outlives done: staged again
    files.forget(brain.first_brain(L), forgotten["id"])
    assert status(forgotten["id"]) == "forgotten" and files.overview(brain.first_brain(L))["used"] == 3
    r = files.reserve(brain.first_brain(L), [item("b.txt", b"defg")])["files"][0]
    store.put(r["upload"], b"defg")
    kept = files.done(brain.first_brain(L), r["id"])
    store.put(r["upload"], b"defg")
    assert len(store.objects) == 4
    later(freeze, 2)
    assert files.sweep() == 1 and list(store.objects.values()) == [b"defg"]
    assert status(kept["id"]) == "active" and files.overview(brain.first_brain(L))["used"] == 4
    calls = len(store.calls)
    assert files.sweep() == 0 and len(store.calls) == calls  # its staging key is cleared


def test_a_reservation_stays_charged_until_its_bytes_are_deleted(store, L, freeze):
    freeze("2026-10-31T12:00:00")
    files.reserve(brain.first_brain(L), [big("a.bin", 400 * MB)])
    later(freeze, 2)
    store.fail.add("DELETE")
    assert files.sweep() == 0
    with pytest.raises(ValidationError, match="That needs 200 MB"):
        files.reserve(brain.first_brain(L), [big("b.bin", 200 * MB)])
    store.fail.clear()
    assert files.sweep() == 1 and files.overview(brain.first_brain(L))["used"] == 0
    files.reserve(brain.first_brain(L), [big("b.bin", 200 * MB)])


def test_archive_and_bring_back(store, L):
    one = upload(store, L, "a.txt", b"1")
    assert files.set_status(brain.first_brain(L), one["id"], "archived")["status"] == "archived"
    assert [f["status"] for f in files.overview(brain.first_brain(L))["files"]] == ["archived"]
    with pytest.raises(NotFoundError):
        files.link(brain.first_brain(L), path="a.txt")
    two = upload(store, L, "a.txt", b"2")
    with pytest.raises(ConflictError, match="Another file is at that path"):
        files.set_status(brain.first_brain(L), one["id"], "active")
    files.set_status(brain.first_brain(L), two["id"], "archived")
    assert files.set_status(brain.first_brain(L), one["id"], "active")["status"] == "active"


def test_find_file_matches_the_path_exactly(store, L):
    upload(store, L, "raw/Scan.pdf", b"x")
    assert files.find_file(brain.first_brain(L), "raw/Scan.pdf")["path"] == "raw/Scan.pdf"
    assert files.find_file(brain.first_brain(L), "raw/scan.pdf") is None


def test_a_link_reaches_a_file_after_every_page_step(store, L):
    pdf = upload(store, L, "raw/Scan 1.PDF", b"x")
    upload(store, L, "notes/menu", b"x")
    page = brain.write_page(brain.first_brain(L), "notes/menu", "# Menu", title="Menu")
    links = brain.resolve(brain.first_brain(L), ["raw/Scan 1.PDF", "notes/menu", "raw/scan 1.pdf"])
    assert links == {
        "raw/Scan 1.PDF": {"kind": "file", "id": pdf["id"], "path": "raw/Scan 1.PDF"},
        "notes/menu": {"kind": "page", "id": page["id"], "path": "notes/menu"},
    }
    assert brain.resolve(brain.first_brain(L), ["raw/Scan 1.PDF"], restricted=True) == {}


# ── Routes, keys and the agent link ───────────────────────────────────────────


@pytest.mark.anyio
async def test_the_app_uploads_downloads_and_forgets(store, http, acct):
    me = browser(acct)
    body = b"%PDF"
    res = await http.post("/api/app/brain/files", json=item("raw/a.pdf", body), headers=me)
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    reserved = res.json()["files"][0]
    store.put(reserved["upload"], body)
    assert (await http.post(f"/api/app/brain/files/{reserved['id']}/done", headers=me)).json()["status"] == "active"
    got = await http.get(f"/api/app/brain/files/{reserved['id']}", headers=me)
    assert got.status_code == 302 and got.headers["cache-control"] == "no-store"
    assert got.headers["location"].startswith("https://store.example/cb/")
    listed = (await http.get("/api/app/brain/files", headers=me)).json()
    assert listed["on"] and listed["used"] == 4 and [f["path"] for f in listed["files"]] == ["raw/a.pdf"]
    res = await http.post("/api/app/brain/files", json=big("v.mp4", 600 * MB), headers=me)
    assert res.status_code == 400 and "from the browser" in res.json()["detail"]
    assert (await http.post(f"/api/app/brain/files/{reserved['id']}/forget", headers=me)).json()["versions"] == 1
    listed = (await http.get("/api/app/brain/files", headers=me)).json()
    assert listed["files"] == [] and listed["used"] == 4  # charged until the sweeper deletes it


@pytest.mark.anyio
async def test_rest_reserves_finishes_and_redirects(store, http, acct):
    key, body = new_key(acct["list_id"], name="vm-jobs"), b"0123456789"
    res = await http.post("/api/v1/files", json={"files": [item("raw/x.bin", body)]}, headers=bearer(key))
    assert res.status_code == 200
    reserved = res.json()["files"][0]
    store.put(reserved["upload"], body)
    done = await http.post(f"/api/v1/files/{reserved['id']}/done", headers=bearer(key))
    assert done.status_code == 200 and done.json()["created_by"] == "vm-jobs"
    got = await http.get("/api/v1/files", params={"path": "raw/x.bin"}, headers=bearer(key))
    assert got.status_code == 302 and got.headers["cache-control"] == "no-store"
    assert (await http.get("/api/v1/files", params={"path": "raw/nope"}, headers=bearer(key))).status_code == 404
    reader = new_key(acct["list_id"], name="reader", access="read")
    assert (await http.post("/api/v1/files", json=item("raw/y", b"y"), headers=bearer(reader))).status_code == 403
    assert (await http.get("/api/v1/files", params={"path": "raw/x.bin"}, headers=bearer(reader))).status_code == 302


@pytest.mark.anyio
async def test_a_folder_key_reads_and_writes_only_its_folders_files(store, http, acct):
    list_id = acct["list_id"]
    upload(store, list_id, "acme/secret.pdf", b"s")
    upload(store, list_id, "ACME/INBOX/odd.pdf", b"o")
    raw = new_key(list_id, name="example-agents", folders=["acme/inbox"])
    key = bearer(raw)
    ok = await http.post("/api/v1/files", json=item("acme/inbox/Call (1).m4a", b"a"), headers=key)
    assert ok.status_code == 200
    for path in ("acme/secret.pdf", "ACME/INBOX/x.pdf", "acme/inbox/../x"):
        assert (await http.post("/api/v1/files", json=item(path, b"a"), headers=key)).status_code == 403
        assert (await http.get("/api/v1/files", params={"path": path}, headers=key)).status_code == 403
    batch = {"files": [item("acme/inbox/b", b"b"), item("acme/c", b"c")]}
    assert (await http.post("/api/v1/files", json=batch, headers=key)).status_code == 403
    mine = upload(store, list_id, "acme/inbox/mine.pdf", b"m")
    theirs = files.reserve(brain.first_brain(list_id), [item("acme/theirs.pdf", b"t")])["files"][0]
    assert (await http.post(f"/api/v1/files/{theirs['id']}/done", headers=key)).status_code == 403
    assert (await http.post(f"/api/v1/files/{2**70}/done", headers=key)).status_code == 400
    listed = (await rest(http, raw, "brain_page_list")).json()
    assert [f["path"] for f in listed["files"]] == ["acme/inbox/mine.pdf"]
    link = await rest(http, raw, "brain_file_link", path="acme/inbox/mine.pdf")
    assert link.status_code == 200 and link.json()["link"].startswith("https://store.example/cb/")
    assert link.json()["file"]["sha256"] == mine["sha256"]
    refused = await rest(http, raw, "brain_file_link", path="acme/secret.pdf")
    assert refused.status_code == 400 and "only files inside acme/inbox/" in refused.json()["error"]


@pytest.mark.anyio
async def test_the_agent_link_lists_files_counts_them_and_links_one(store, http, acct):
    list_id = acct["list_id"]
    for i in range(files.LIST_MAX + 1):
        with db.transaction() as conn:  # rows alone: the listing reads no bytes
            conn.execute(
                "INSERT INTO brain_files (list_id, brain_id, path, object_key, staging_key, size, sha256, "
                "content_type, status, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, '', 1, "
                "'', 'text/plain', 'active', 'you', '', '')",
                (list_id, brain.first_brain(list_id), f"raw/{i:03}.txt", f"k{i}"),
            )
    key = new_key(list_id, name="reader", access="read")
    listed = (await rest(http, key, "brain_page_list", folder="raw")).json()
    assert len(listed["files"]) == files.LIST_MAX and listed["more_files"].startswith("1 more files")
    assert (await rest(http, key, "brain_page_list", folder="other")).json()["files"] == []
    assert (await rest(http, key, "brain_start")).json()["files"]["count"] == files.LIST_MAX + 1
    assert (await rest(http, key, "brain_file_link", path="raw/007.txt")).json()["minutes"] == 10


def test_admin_delete_removes_the_lists_objects_first(store, L, capsys):
    from scripts import admin

    upload(store, L, "a.txt", b"a")
    files.reserve(brain.first_brain(L), [item("b.txt", b"b")])  # pending: its staging key goes too
    other = lists.create_list("UTC")["list_id"]
    confirm_list(other)
    upload(store, other, "kept.txt", b"k")
    assert "brain_files" in admin._LIST_TABLES
    store.calls.clear()
    assert admin.main(["delete", str(L), f"--yes-delete-list-{L}", "--no-snapshot"]) == 0
    assert list(store.objects.values()) == [b"k"]
    assert len({k for m, k in store.calls if m == "DELETE"}) == 4  # two rows: staging and final keys


def test_admin_delete_refuses_files_without_a_store(store, L, monkeypatch):
    from scripts import admin

    upload(store, L, "a.txt", b"a")
    monkeypatch.delenv("FILES_S3_SECRET")
    with pytest.raises(SystemExit, match="FILES_S3_"):
        admin.main(["delete", str(L), f"--yes-delete-list-{L}", "--no-snapshot"])
    assert lists.get_list(L) is not None and status(1) == "active"


def test_a_files_path_in_a_query_never_reaches_a_log():
    line = "GET /api/v1/files?path=people/maya%20medical.pdf&x=1 HTTP/1.1"
    assert logscrub.scrub(line) == "GET /api/v1/files?path=***&x=1 HTTP/1.1"


def test_one_list_repair_leaves_the_files_as_they_are(store, L):
    from backend import backup
    from scripts import restore_list

    before = upload(store, L, "a.txt", b"a")
    snapshot = backup.snapshot()
    after = upload(store, L, "b.txt", b"b")
    files.forget(brain.first_brain(L), before["id"])
    restore_list.restore(snapshot, L, db.db_path())
    assert [status(before["id"]), status(after["id"])] == ["forgotten", "active"]
