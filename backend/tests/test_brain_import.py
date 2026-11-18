"""Zip imports, their write transactions, and browser/key authority. All data is invented."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import stat
import logging
import threading
import zipfile

import httpx2 as httpx
import pytest

from backend import brain, brain_import as imp, db, files, keys, logscrub
from backend.common import ConflictError, NotFoundError, ValidationError
from backend.tests.conftest import confirm_list, turn_on
from backend.tests.test_files import store, upload  # noqa: F401, F811 (fixture)


@pytest.fixture()
def zipped(tmp_path):
    def make(entries, name="notes.zip"):
        path = tmp_path / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, body in entries:
                z.writestr(name, body)
        return path

    return make


def test_report_mapping_memories_blanking_and_idempotence(L, zipped):
    path = zipped(
        [
            ("People/Maya.markdown", "# Maya\nA made-up password: example-only123"),
            ("archive/Old.htm", "---\narchived: true\n---\n<p>Old</p>"),
            ("archive/current.md", "Still current"),
            ("MEMORY.md", "# Locked\n- Likes tea\n# Other\n- Has a bike 🔒\n- " + "a" * 501),
            ("raw.txt", "raw text"),
            ("big.md", "b" * 200_001),
        ]
    )
    preview = imp.plan(brain.first_brain(L), path, brain.YOU)
    assert preview["counts"] == {"pages": 4, "memories": 2, "files": 2}
    assert preview["path_changes"][0] == {"from": "People/Maya.markdown", "to": "people/maya"}
    assert preview["removed"] == [{"path": "People/Maya.markdown", "counts": [{"kind": "password", "count": 1}]}]
    assert preview["oversized"] == ["big.md"]
    assert not brain.pages(brain.first_brain(L)) and not brain.memories(brain.first_brain(L))
    first = imp.run(brain.first_brain(L), path, "Moving day", brain.YOU)
    assert first["complete"] and first["processed"] == 8 and first["written"] == 6
    assert [e["result"] for e in first["entries"] if e["kind"] == "file"] == ["files are off"] * 2
    assert all(m["locked"] for m in brain.memories(brain.first_brain(L)))
    assert brain.get_page(brain.first_brain(L), path="archive/old")["status"] == "archived"
    assert brain.get_page(brain.first_brain(L), path="archive/current")["status"] == "active"
    assert brain.get_page(brain.first_brain(L), path="inbox/long-memories")["body"] == "- " + "a" * 501
    count = len(brain.changes(brain.first_brain(L)))
    again = imp.run(brain.first_brain(L), path, "Moving day", brain.YOU)
    assert again["complete"] and again["written"] == 0 and again["skipped"] == 8
    assert len(brain.changes(brain.first_brain(L))) == count
    assert {v["pass"] for v in brain.changes(brain.first_brain(L))} == {"Moving day"}
    assert {v["reason"] for v in brain.changes(brain.first_brain(L))} == {"Import Markdown"}
    assert all(m["locked"] for m in brain.memories(brain.first_brain(L)))


def test_changed_body_gets_one_new_version(L, zipped):
    path = zipped([("x.md", "before")])
    imp.run(brain.first_brain(L), path, "one", brain.YOU)
    path = zipped([("x.md", "after")])
    assert imp.run(brain.first_brain(L), path, "two", brain.YOU)["written"] == 1
    assert brain.get_page(brain.first_brain(L), path="x")["version"] == 2


def test_key_cannot_lock_unlock_or_archive_locked_memory(L, zipped):
    confirm_list(L)
    path = zipped([("MEMORY.md", "# Locked\n- Likes tea\n- Likes coffee 🔒")])
    first = imp.run(brain.first_brain(L), path, "key pass", "Importer")
    assert first["complete"] and len(first["warnings"]) == 2
    assert not any(m["locked"] for m in brain.memories(brain.first_brain(L)))
    assert imp.run(brain.first_brain(L), path, "person pass", brain.YOU)["written"] == 2
    path = zipped([("MEMORY.md", "- likes tea")])
    report = imp.run(brain.first_brain(L), path, "key pass", "Importer", archive_missing=True)
    assert report["complete"] and report["archived"] == 0
    assert len(brain.memories(brain.first_brain(L))) == 2 and all(
        m["locked"] for m in brain.memories(brain.first_brain(L))
    )
    assert imp.run(brain.first_brain(L), path, "person pass", brain.YOU, archive_missing=True)["archived"] == 1


def test_cap_failure_commits_progress_does_not_archive_and_resumes(L, zipped, monkeypatch):
    old = brain.write_page(brain.first_brain(L), "old", "keep until complete")
    path = zipped([(f"page-{i}.md", f"Page {i}") for i in range(12)])
    assert imp.plan(brain.first_brain(L), path, brain.YOU)["over_cap"] == ["pages"]
    report = imp.run(brain.first_brain(L), path, "bulk", brain.YOU, archive_missing=True)
    assert not report["complete"] and report["processed"] == report["written"] == 9
    assert report["error"] and report["archived"] == 0
    assert brain.get_page(brain.first_brain(L), page_id=old["id"])["status"] == "active"
    confirm_list(L)
    again = imp.run(brain.first_brain(L), path, "bulk", brain.YOU, archive_missing=True)
    assert again["complete"] and again["processed"] == 12 and again["skipped"] == 9
    assert again["written"] == 3 and again["archived"] == 1
    assert brain.get_page(brain.first_brain(L), page_id=old["id"])["status"] == "archived"


def test_chunks_share_a_pass_and_keep_caps_inside_transaction(L, zipped, monkeypatch):
    confirm_list(L)
    path = zipped([(f"page-{i}.md", f"Page {i}") for i in range(501)])
    counts = []
    original = brain.write_page_in

    def write(conn, *args, **kwargs):
        assert conn.in_transaction and db.write_lock().locked()
        counts[-1] += 1
        return original(conn, *args, **kwargs)

    transaction = db.transaction

    @contextmanager
    def tracked():
        counts.append(0)
        with transaction() as conn:
            yield conn

    monkeypatch.setattr(db, "transaction", tracked)
    monkeypatch.setattr(brain, "write_page_in", write)
    assert imp.run(brain.first_brain(L), path, "bulk", brain.YOU)["written"] == 501
    assert counts == [500, 1]
    assert {tuple(r) for r in db.get_db().execute("SELECT DISTINCT pass, reason FROM brain_versions")} == {
        ("bulk", "Import Markdown")
    }


def test_failure_rolls_back_only_failed_entry_and_never_archives(L, zipped, monkeypatch):
    brain.write_page(brain.first_brain(L), "keep", "keep")
    path = zipped([("a.md", "a"), ("b.md", "b")])
    original = imp._write_in

    def fail(conn, list_id, entry, *args):
        result = original(conn, list_id, entry, *args)
        if entry["path"] == "b":
            raise RuntimeError("private exception")
        return result

    monkeypatch.setattr(imp, "_write_in", fail)
    report = imp.run(brain.first_brain(L), path, "pass", brain.YOU, True)
    assert report["processed"] == 1 and report["written"] == 1 and not report["complete"]
    assert report["error"] == "Import stopped. Try again."
    assert {p["path"] for p in brain.pages(brain.first_brain(L))} == {"a", "keep"}


@pytest.mark.parametrize("name", ["/root.md", "../bad.md", "a/../bad.md", "C:/bad.md", "a\\bad.md", "a//bad.md"])
def test_unsafe_paths_rejected_before_writes(L, zipped, name):
    path = zipped([("good.md", "Good"), (name, "Bad")])
    with pytest.raises(ValidationError):
        imp.run(brain.first_brain(L), path, "pass", brain.YOU)
    assert not brain.pages(brain.first_brain(L))


def test_symlink_duplicate_and_malformed(L, zipped, tmp_path):
    info = zipfile.ZipInfo("symlink.md")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    for entries in ([(info, "target")], [("A B.md", "a"), ("a-b.markdown", "b")], [("file.md", "a"), ("file", "b")]):
        with pytest.raises(ValidationError):
            imp.plan(brain.first_brain(L), zipped(entries), brain.YOU)
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ValidationError, match="Malformed"):
        imp.run(brain.first_brain(L), bad, "pass", brain.YOU)
    assert not brain.pages(brain.first_brain(L))


@pytest.mark.parametrize("limit,value", [("MAX_ENTRIES", 1), ("MAX_BYTES", 100), ("MAX_FILE", 100)])
def test_bounded_actual_bytes_and_entry_limit(L, zipped, monkeypatch, limit, value):
    path = zipped([("a.md", "a" * 1000), ("b.md", "b")])
    monkeypatch.setattr(imp, limit, value)
    with pytest.raises(ValidationError):
        imp.run(brain.first_brain(L), path, "pass", brain.YOU)
    assert not brain.pages(brain.first_brain(L))


def test_non_utf8_reported(L, zipped):
    path = zipped([("bad.md", b"hello\xff")])
    report = imp.run(brain.first_brain(L), path, "pass", brain.YOU)
    assert report["complete"] and report["decoded"] == ["bad.md"]
    assert brain.get_page(brain.first_brain(L), path="bad")["body"] == "hello\ufffd"


def test_one_import_per_account(L, zipped):
    path = zipped([("a.md", "a")])
    with imp._account(brain.first_brain(L)):
        with pytest.raises(ConflictError, match="already running"):
            imp.run(brain.first_brain(L), path, "pass", brain.YOU)
        with pytest.raises(ConflictError):
            imp.plan(brain.first_brain(L), path, brain.YOU)
    assert imp.run(brain.first_brain(L), path, "pass", brain.YOU)["complete"]


@pytest.fixture()
def uploading(store, monkeypatch):  # noqa: F811 (fixture)
    def put(url, *, content, headers, timeout):
        assert not db.write_lock().locked()
        return httpx.Response(
            store.put({"url": url, "headers": headers}, content.read()), request=httpx.Request("PUT", url)
        )

    monkeypatch.setattr(imp.httpx, "put", put)
    return store


def test_files_upload_hash_skip_and_only_source_files_archived(L, zipped, uploading):
    confirm_list(L)
    raw = upload(uploading, L, "raw/manual.txt", b"keep")
    path = zipped([("big.md", "b" * 200_001), ("notes.txt", "notes"), ("keep.png", b"image")])
    report = imp.run(brain.first_brain(L), path, "pass", brain.YOU)
    assert report["complete"] and report["written"] == 3
    assert imp.run(brain.first_brain(L), path, "pass", brain.YOU)["skipped"] == 3
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_files").fetchone()[0] == 4
    path = zipped([("keep.png", b"image")])
    report = imp.run(brain.first_brain(L), path, "pass", brain.YOU, True)
    assert report["archived"] == 2
    assert {f["path"] for f in files.listing(brain.first_brain(L))} == {"keep.png", raw["path"]}
    assert {
        r[0]
        for r in db.get_db().execute("SELECT DISTINCT import_source FROM brain_files WHERE import_source IS NOT NULL")
    } == {"notes.zip"}


def test_upload_failure_does_not_archive_or_expose_url(L, zipped, uploading, monkeypatch):
    confirm_list(L)
    brain.write_page(brain.first_brain(L), "keep", "keep")

    def fail(*args, **kwargs):
        raise httpx.ConnectError("sensitive signed URL")

    monkeypatch.setattr(imp.httpx, "put", fail)
    report = imp.run(brain.first_brain(L), zipped([("file.txt", "text")]), "pass", brain.YOU, True)
    assert not report["complete"] and report["processed"] == 0 and report["archived"] == 0
    assert "signed" not in report["error"]
    assert brain.get_page(brain.first_brain(L), path="keep")["status"] == "active"


def test_joining_helpers_checks_and_history(L):
    with db.transaction() as conn:
        memory = brain.remember_in(conn, brain.first_brain(L), ["Likes tea"])["added"][0]
        brain.update_memory_in(conn, brain.first_brain(L), memory["id"], locked=True)
        with pytest.raises(ValidationError, match="locked"):
            brain.update_memory_in(conn, brain.first_brain(L), memory["id"], text="Likes coffee", by="Importer")
        page = brain.write_page_in(
            conn, brain.first_brain(L), "x", "---\nconfidential: true\n---\ntext", status="archived"
        )
        assert page["status"] == "archived"
        brain.append_page_in(conn, brain.first_brain(L), "x", "more")
        with pytest.raises(NotFoundError):
            brain.append_page_in(conn, brain.first_brain(L), "x", "not allowed", restricted=True)
    assert len(brain.history(brain.first_brain(L), "page", page["id"])) == 2


def test_stale_path_create_only_and_identity(L):
    old = brain.write_page(brain.first_brain(L), "x", "old")
    brain.write_page(brain.first_brain(L), "x", move_to="y", expected_id=old["id"])
    with pytest.raises(ConflictError, match="moved or was archived"):
        brain.write_page(brain.first_brain(L), "x", "stale", version=1)
    new = brain.write_page(brain.first_brain(L), "x", "new", new=True)
    for changes in ({"body": "wrong"}, {"move_to": "z"}):
        with pytest.raises(ConflictError):
            brain.write_page(brain.first_brain(L), "x", expected_id=old["id"], **changes)
    with pytest.raises(ValidationError, match="already"):
        brain.write_page(brain.first_brain(L), "x", "clobber", new=True)
    brain.update_page(brain.first_brain(L), old["id"], {"body": "edited"})
    assert brain.get_page(brain.first_brain(L), path="x")["id"] == new["id"]
    assert brain.get_page(brain.first_brain(L), path="y")["body"] == "edited"


def test_concurrent_appends_to_new_page_keep_every_line(L):
    barrier = threading.Barrier(8)

    def append(i):
        barrier.wait(timeout=10)
        brain.append_page(brain.first_brain(L), "new", f"- line {i}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(8)))
    assert set(brain.get_page(brain.first_brain(L), path="new")["body"].splitlines()) == {
        f"- line {i}" for i in range(8)
    }


def test_migration_is_idempotent(L):
    brain.write_page(brain.first_brain(L), "old", "old")
    with db.transaction() as conn:
        conn.execute("ALTER TABLE brain_versions DROP COLUMN pass")
        conn.execute("ALTER TABLE brain_versions DROP COLUMN reason")
    db._migrate(db.get_db())
    db._migrate(db.get_db())
    assert brain.changes(brain.first_brain(L))[0]["pass"] == brain.changes(brain.first_brain(L))[0]["reason"] == ""


def test_browser_and_rest_authority_spooling_and_refusals(new_list, monkeypatch, zipped, tmp_path):
    monkeypatch.setenv("BRAIN_BASE_URL", "https://brain.example")
    made = new_list()
    client, list_id = made["client"], made["list_id"]
    turn_on(list_id, "brain")
    confirm_list(list_id)
    body = zipped([("MEMORY.md", "# Locked\n- Likes tea"), ("page.md", "page")]).read_bytes()
    route = "/api/app/brain/import"
    assert client.post(route, content=body, headers={"X-List": "0"}).status_code == 409
    assert client.post(route, content=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    seen = []
    original_plan = imp.plan
    caller = threading.get_ident()

    def planned(list_id, path, by):
        assert threading.get_ident() != caller and path.exists()
        seen.append(path)
        return original_plan(list_id, path, by)

    monkeypatch.setattr(imp, "plan", planned)
    preview = client.post(route + "?dry_run=1", content=body, headers={"X-Import-Name": "original.zip"})
    assert seen[0].name == "original.zip" and not seen[0].exists()
    assert preview.status_code == 200 and preview.json()["complete"]
    assert preview.headers["cache-control"] == "no-store" and not brain.pages(brain.first_brain(list_id))
    for access, folders in (("read", []), ("write", ["inbox"])):
        key = keys.create(list_id, access + str(len(folders)), access=access, folders=folders)["key"]
        denied = client.post("/api/v1/import", content=body, headers={"Authorization": "Bearer " + key})
        assert denied.status_code == 403 and denied.headers["cache-control"] == "no-store"
    assert client.post("/api/v1/import", content=body).status_code == 403
    key = keys.create(list_id, "Importer", access="write")["key"]
    response = client.post("/api/v1/import?label=pass", content=body, headers={"Authorization": "Bearer " + key})
    assert response.status_code == 200 and response.json()["complete"]
    assert not brain.memories(brain.first_brain(list_id))[0]["locked"]
    assert client.post(route, content=body).json()["complete"]
    assert brain.memories(brain.first_brain(list_id))[0]["locked"]
    with imp._account(brain.first_brain(list_id)):
        assert client.post(route, content=body).status_code == 409
    auth = {"Authorization": "Bearer " + key}
    tool = "/api/v1/tools/brain_page_write"
    created = client.post(tool, json={"path": "identity", "body": "first", "create_only": True}, headers=auth)
    assert created.status_code == 200
    page_id = created.json()["page"]["id"]
    assert (
        client.post(tool, json={"path": "identity", "body": "second", "create_only": True}, headers=auth).status_code
        == 400
    )
    assert (
        client.post(
            tool, json={"path": "identity", "body": "second", "expected_id": page_id + 1}, headers=auth
        ).status_code
        == 400
    )
    for endpoint, headers in ((route, {}), ("/api/v1/import", {"Authorization": "Bearer " + key})):
        malformed = client.post(endpoint, content=b"not a zip", headers=headers)
        assert malformed.status_code == 400 and malformed.headers["cache-control"] == "no-store"
    monkeypatch.setattr(imp, "MAX_UPLOAD", 10)
    assert client.post(route, content=body).status_code == 413


def test_long_memory_page_uses_the_oversized_file_rule(L, zipped):
    path = zipped([("MEMORY.md", "- " + "m" * 200_001)])
    report = imp.run(brain.first_brain(L), path, "pass", brain.YOU)
    assert report["complete"] and report["oversized"] == ["inbox/long-memories.md"]
    assert report["counts"] == {"pages": 0, "memories": 0, "files": 1}
    assert report["entries"][0]["result"] == "files are off"


def test_windows_newlines_survive_and_rerun_is_unchanged(L, zipped):
    body = "# Title\r\n\r\nA paragraph.\r\n"
    path = zipped([("page.md", body)])
    assert imp.run(brain.first_brain(L), path, "pass", brain.YOU)["written"] == 1
    assert brain.get_page(brain.first_brain(L), path="page")["body"] == body
    assert imp.run(brain.first_brain(L), path, "pass", brain.YOU)["written"] == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://store.example/bucket/staging/object?X-Amz-Algorithm=example&X-Amz-Signature=made-up",
        "/bucket/staging/object?other=first&X-Amz-Signature=made-up&last=1",
    ],
)
def test_signed_upload_urls_are_scrubbed_from_httpx_logs(url):
    record = logging.LogRecord(
        "httpx2",
        logging.INFO,
        "",
        0,
        'HTTP Request: %s %s "%s %d %s"',
        ("PUT", httpx.URL(url), "HTTP/1.1", 200, "OK"),
        None,
    )
    logscrub.ScrubTokens().filter(record)
    assert record.getMessage() == 'HTTP Request: PUT [signed file URL] "HTTP/1.1 200 OK"'
    assert logscrub.scrub(f"Upload failed: {url}") == "Upload failed: [signed file URL]"


def test_hidden_entries_star_bullets_and_text_attachments(L, zipped):
    path = zipped(
        [
            (".obsidian/workspace.json", "{}"),
            ("__MACOSX/._a.md", "x"),
            ("notes/.hidden.md", "x"),
            ("MEMORY.md", "* Drinks oat milk\n+ Rides a bike"),
            ("acme/settings.yaml", "user: maya\npassword: example-only123\n"),
        ]
    )
    report = imp.plan(brain.first_brain(L), path, brain.YOU)
    assert report["counts"] == {"pages": 0, "memories": 2, "files": 1}
    assert {"path": "", "reason": "3 hidden files (like .obsidian/) not imported"} in report["warnings"]
    assert report["removed"] == [{"path": "acme/settings.yaml", "counts": [{"kind": "password", "count": 1}]}]


def test_a_bad_byte_does_not_shield_a_text_attachments_secrets(L, zipped):
    report = imp.plan(brain.first_brain(L), zipped([("notes.txt", b"\xff password: example-only123\n")]), brain.YOU)
    assert report["removed"] == [{"path": "notes.txt", "counts": [{"kind": "password", "count": 1}]}]
    assert report["decoded"] == ["notes.txt"]


def test_memory_lines_count_toward_the_entry_limit(L, zipped, monkeypatch):
    monkeypatch.setattr(imp, "MAX_ENTRIES", 3)
    with pytest.raises(ValidationError, match="memory lines included"):
        imp.plan(brain.first_brain(L), zipped([("MEMORY.md", "- x\n" * 4)]), brain.YOU)


def test_files_off_leaves_the_run_incomplete_and_archives_nothing(L, zipped):
    brain.write_page(brain.first_brain(L), "x", "the page")
    report = imp.run(brain.first_brain(L), zipped([("x.md", "b" * 200_001)]), "pass", brain.YOU, True)
    assert not report["complete"] and report["archived"] == 0 and "Files are off" in report["error"]
    assert brain.get_page(brain.first_brain(L), path="x")["status"] == "active"


def test_a_path_is_normalised_once_for_every_step(L, zipped):
    with pytest.raises(ValidationError, match="collide"):
        imp.plan(brain.first_brain(L), zipped([("x.md.md.md", "one"), ("x.md", "two")]), brain.YOU)
    report = imp.run(brain.first_brain(L), zipped([("x.md.md.md", "one")]), "pass", brain.YOU, True)
    assert report["complete"] and report["archived"] == 0
    assert brain.get_page(brain.first_brain(L), path="x")["status"] == "active"


def test_a_memory_is_matched_as_it_is_stored(L, zipped):
    path = zipped([("MEMORY.md", "- Card: 4242  4242 4242 4242")])
    first = imp.run(brain.first_brain(L), path, "pass", brain.YOU, True)
    assert first["removed"] == [{"path": "MEMORY.md", "counts": [{"kind": "card number", "count": 1}]}]
    again = imp.run(brain.first_brain(L), path, "pass", brain.YOU, True)
    assert again["archived"] == 0 and again["written"] == 0
    assert [m["text"] for m in brain.memories(brain.first_brain(L))] == ["Card: [removed: card number]"]


def test_a_retry_reuses_its_unfinished_reservation(L, zipped, uploading, monkeypatch):
    confirm_list(L)
    path = zipped([("file.txt", "text")])

    def fail(*args, **kwargs):
        raise httpx.ConnectError("down")

    with monkeypatch.context() as m:
        m.setattr(imp.httpx, "put", fail)
        assert not imp.run(brain.first_brain(L), path, "pass", brain.YOU)["complete"]
    assert imp.run(brain.first_brain(L), path, "pass", brain.YOU)["complete"]
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_files").fetchone()[0] == 1


def test_a_bad_utf8_name_is_a_malformed_zip(L, tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("é.md", "x")
    path.write_bytes(path.read_bytes().replace("é.md".encode(), b"\xff\xa9.md"))
    with pytest.raises(ValidationError, match="Malformed"):
        imp.plan(brain.first_brain(L), path, brain.YOU)
