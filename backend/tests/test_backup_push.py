"""backup.push: encrypted snapshots copied to the backup bucket, with the store faked at the
httpx boundary and every call's signature checked against the backup bucket's own settings."""

import asyncio
import base64
import hashlib
import json
import logging
import re
from urllib.parse import urlsplit

import httpx2 as httpx
import pytest

from backend import backup, objectstore
from backend.tests.test_admin import run  # noqa: F401 (fixture)
from backend.tests.test_files import store  # noqa: F401 (fixture)

CFG = {
    "endpoint": "https://backups.example",
    "bucket": "snaps",
    "key_id": "backup-key-id",
    "secret": "backup-shh",
    "region": "auto",
}


class Bucket:
    """HEAD and PUT on one bucket, as S3 answers them: the signature over what was sent,
    then the body against its signed length and both hashes. A method in `fail` answers
    500 with a body that must never be logged; `down` makes every call a connection error."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail: set[str] = set()
        self.down = False

    def request(self, method, url, headers, timeout, content=None):
        parts, req = urlsplit(url), httpx.Request(method, url)
        assert parts.netloc == "backups.example" and parts.path.startswith("/snaps/") and timeout
        key = parts.path.removeprefix("/snaps/")
        self.calls.append((method, key))
        if self.down:
            raise httpx.ConnectError(f"cannot reach {url}", request=req)
        auth = re.fullmatch(
            r"AWS4-HMAC-SHA256 Credential=backup-key-id/\d{8}/auto/s3/aws4_request, "
            r"SignedHeaders=(\S+), Signature=(\w+)",
            headers["authorization"],
        )
        assert auth is not None
        sent = {"host": parts.netloc, **headers}
        signed = {name: sent[name] for name in auth[1].split(";")}
        payload = headers["x-amz-content-sha256"]
        assert objectstore._signature(CFG, method, parts.path, {}, signed, payload, headers["x-amz-date"]) == auth[2]
        if method in self.fail:
            return httpx.Response(500, content=b"<Error>provider-detail</Error>", request=req)
        if method == "HEAD":
            if key not in self.objects:
                return httpx.Response(404, request=req)
            return httpx.Response(200, headers={"content-length": str(len(self.objects[key]))}, request=req)
        assert method == "PUT" and {"content-length", "x-amz-checksum-sha256"} <= signed.keys()
        body = b"".join(content)
        assert headers["content-length"] == str(len(body))
        assert payload == hashlib.sha256(body).hexdigest()
        assert headers["x-amz-checksum-sha256"] == base64.b64encode(hashlib.sha256(body).digest()).decode()
        self.objects[key] = body
        return httpx.Response(200, request=req)


@pytest.fixture()
def bucket(todo_db, monkeypatch):
    for name, value in CFG.items():
        monkeypatch.setenv(f"BACKUP_S3_{name.upper()}", value)
    monkeypatch.setenv("SNAPSHOT_AGE_RECIPIENT", "age1example")
    fake = Bucket()
    monkeypatch.setattr(objectstore.httpx, "request", fake.request)
    backup.backups_dir().mkdir()
    return fake


def snap(hour: int, body: bytes | None = None, suffix: str = ".db.zst.age") -> str:
    """A snapshot file on the volume, taken at that hour."""
    path = backup.backups_dir() / f"todo-20261004T{hour:02d}0000Z{suffix}"
    path.write_bytes(body if body is not None else b"sealed %d" % hour)
    return path.name


def puts(fake: Bucket) -> list[str]:
    return [key for method, key in fake.calls if method == "PUT"]


def test_nothing_is_called_without_the_bucket_or_without_a_recipient(bucket, monkeypatch):
    snap(1)
    monkeypatch.delenv("SNAPSHOT_AGE_RECIPIENT")
    assert backup.push() == 0
    monkeypatch.setenv("SNAPSHOT_AGE_RECIPIENT", "age1example")
    monkeypatch.delenv("BACKUP_S3_SECRET")
    assert backup.push() == 0
    assert bucket.calls == [] and bucket.objects == {}


def test_a_missing_snapshot_is_uploaded_whole_and_one_already_there_is_skipped(bucket):
    body = bytes(range(256)) * 9000  # more than one chunk
    old, new = snap(1, suffix=".db.age"), snap(2, body)
    assert backup.push() == 2
    assert bucket.objects == {old: b"sealed 1", new: body}  # the fake checked length and hashes
    bucket.calls.clear()
    assert backup.push() == 0
    assert bucket.calls == [("HEAD", new), ("HEAD", old)]


def test_another_size_in_the_bucket_is_uploaded_again(bucket):
    name = snap(1)
    bucket.objects[name] = b"half"
    assert backup.push() == 1 and bucket.objects[name] == b"sealed 1"


def test_three_a_run_newest_first(bucket):
    names = [snap(hour) for hour in range(1, 6)]
    assert backup.push() == 3 and puts(bucket) == names[:1:-1]
    assert backup.push() == 2 and puts(bucket) == names[:1:-1] + names[1::-1]
    assert backup.push() == 0


def test_a_plain_snapshot_never_leaves_the_volume(bucket):
    snap(1, suffix=".db")
    snap(2, suffix=".db.zst.age.tmp")
    assert backup.push() == 0 and bucket.calls == []


def test_a_snapshot_pruned_after_it_was_listed_is_passed_over(bucket, monkeypatch):
    kept, gone = snap(1), snap(2)
    listed = backup.sealed()
    (backup.backups_dir() / gone).unlink()
    monkeypatch.setattr(backup, "sealed", lambda: listed)
    assert backup.push() == 1 and list(bucket.objects) == [kept]


SECRETS = ("backups.example", "backup-key-id", "backup-shh", "provider-detail", "AWS4", "https://", "age1example")


@pytest.mark.parametrize("how", ["HEAD", "PUT", "down", "bad answer"])
def test_a_store_failure_is_logged_without_secrets_and_tried_again(bucket, monkeypatch, caplog, how):
    name = snap(1)
    with monkeypatch.context() as broken, caplog.at_level(logging.DEBUG):
        if how == "down":
            broken.setattr(bucket, "down", True)
        elif how == "bad answer":  # not a StoreError: its text names the address
            broken.setattr(objectstore, "head", lambda key, cfg: int(cfg["endpoint"] + cfg["secret"]))
        else:
            broken.setattr(bucket, "fail", {how})
        assert backup.push() == 0
    assert "tried again next run" in caplog.text and bucket.objects == {}
    with caplog.at_level(logging.DEBUG):  # the store is back
        assert backup.push() == 1 and list(bucket.objects) == [name]
    assert not any(secret in caplog.text for secret in SECRETS)


def test_the_maintenance_loop_pushes_after_a_failed_snapshot_and_survives_a_failed_push(bucket, monkeypatch):
    from backend import main

    name, passes = snap(1), []
    bucket.fail.add("PUT")
    monkeypatch.setattr(main.settings, "snapshot_interval", lambda: 0.01)
    monkeypatch.setattr(main.backup, "_snapshot", lambda: 1 / 0)  # this hour's snapshot fails
    monkeypatch.setattr(main, "_sweep_files", lambda: passes.append(1))

    async def run_for(seconds):
        task = asyncio.create_task(main._maintain())
        await asyncio.sleep(seconds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_for(0.3))
    assert len(passes) > 1 and puts(bucket).count(name) > 1 and bucket.objects == {}  # failed, and went on
    bucket.fail.clear()
    asyncio.run(run_for(0.3))
    assert bucket.objects == {name: b"sealed 1"}


def test_snapshots_taken_outside_the_app_do_not_push(bucket, monkeypatch):
    monkeypatch.setattr(backup, "_seal", lambda plain, sealed, recipient: sealed.write_bytes(b"sealed"))
    assert backup.snapshot() is not None and backup.sealed() and bucket.calls == []


def test_the_files_store_is_signed_as_before(store, bucket, monkeypatch):  # noqa: F811
    """With both stores set, a Files call still goes to the Files bucket with its key
    (FakeStore asserts both), and an unset Files store is still refused."""
    monkeypatch.setattr(objectstore.httpx, "request", store.request)
    store.objects["staging/x"] = b"abc"
    assert objectstore.head("staging/x") == 3 and objectstore.head("staging/y") is None
    objectstore.copy("staging/x", "kept")
    objectstore.delete("staging/x")
    assert store.objects == {"kept": b"abc"}
    monkeypatch.delenv("FILES_S3_BUCKET")
    with pytest.raises(objectstore.StoreError, match="Files are off"):
        objectstore.head("kept")


def test_stats_says_whether_the_newest_encrypted_snapshot_is_in_the_bucket(bucket, monkeypatch, run):  # noqa: F811
    def said():
        code, out = run("stats", "--json")
        assert code == 0
        return json.loads(out)["snapshots"]["newest_encrypted_in_bucket"]

    assert said() == "no encrypted snapshot yet"
    snap(1)
    snap(2, suffix=".db")  # newer, but plain: not the one asked about
    assert said() == "not there" and bucket.calls == [("HEAD", "todo-20261004T010000Z.db.zst.age")]
    bucket.fail.add("HEAD")
    assert said() == "could not check"
    bucket.fail.clear()
    assert backup.push() == 1 and said() == "yes"
    assert "Newest encrypted snapshot in the backup bucket: yes" in run("stats")[1]
    monkeypatch.delenv("BACKUP_S3_ENDPOINT")
    assert said() == "not set up"


def test_stats_lists_the_biggest_tables_or_leaves_them_out(todo_db, run, monkeypatch):  # noqa: F811
    from scripts import admin

    tables = json.loads(run("stats", "--json")[1])["biggest_tables"]
    assert len(tables) == 5 and all(t["bytes"] > 0 for t in tables)
    assert tables == sorted(tables, key=lambda t: -t["bytes"])
    assert "Biggest tables: " in run("stats")[1]

    class NoDbstat:
        def execute(self, sql):
            raise admin.sqlite3.OperationalError("no such table: dbstat")

    assert admin._biggest_tables(NoDbstat()) is None
