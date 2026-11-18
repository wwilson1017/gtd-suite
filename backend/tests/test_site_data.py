"""Page data over the visitor, browser and agent surfaces, with real SQLite storage."""

import json
import sqlite3
from urllib.parse import urlsplit

import pytest
from fastmcp.exceptions import ToolError

from backend import backup, common, db, lists, logscrub, ratelimit, sites, sites_agent
from backend.common import NotFoundError, ValidationError
from backend.tests.conftest import confirm_list
from backend.tests import test_mcp, test_sites

# Other modules' fixtures, bound here so pytest finds them in this module.
anyio_backend, app, http = test_mcp.anyio_backend, test_mcp.app, test_mcp.http
call, connect = test_mcp.call, test_mcp.connect
acct, served = test_sites.acct, test_sites.served


@pytest.fixture()
def data_page(acct):
    confirm_list(acct["id"])
    return sites.publish(acct["id"], "# App", name="app", data="shared")


def path(page):
    return urlsplit(page["address"]).path + "/data"


def owner(acct, page, data):
    return sites.add_record(page["id"], "owner", data, list_id=acct["id"])


def visitor(page, data):
    return sites.add_record(path(page).split("/")[1], "visitor", data)


def cors(res):
    assert res.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in res.headers
    assert "set-cookie" not in res.headers
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "www-authenticate" not in res.headers


@pytest.mark.anyio
@pytest.mark.parametrize("host", ["sites.example", "ss.example"])
async def test_send_read_filters_and_heartbeat(http, acct, data_page, monkeypatch, host):
    monkeypatch.setenv("SITES_SHORT_URL", "https://ss.example")
    headers = {"Host": host, "Origin": "null", "Sec-Fetch-Site": "cross-site", "Cookie": "session=ignored"}
    records = [
        {"page": "ap", "final": True, "no": False, "version": 2, "name": None, "by": "owner"},
        {"page": "ap", "final": True, "no": False, "version": 2, "name": None},
        {"page": "other", "final": False},
    ]
    ids = []
    used = lists.get_list(acct["id"])["last_used_at"]
    for record in records:
        res = await http.post(path(data_page), headers=headers, content=json.dumps(record))
        assert res.status_code == 200
        cors(res)
        ids.append(res.json()["id"])
    res = await http.get(path(data_page) + "?last=20&page=ap&final=true&no=false&version=2&name=null", headers=headers)
    cors(res)
    answer = res.json()
    assert [r["id"] for r in answer["records"]] == ids[:2]
    assert all(r["by"] == "visitor" for r in answer["records"])
    assert answer["owner_seen"] is None and not answer["more"]
    assert lists.get_list(acct["id"])["last_used_at"] == used
    newest = (await http.get(path(data_page), headers=headers)).json()
    assert newest["records"][0]["id"] == ids[-1] and not newest["more"]
    assert (await http.get(path(data_page) + "?by=owner", headers=headers)).json()["records"] == []
    ack = owner(acct, data_page, {"ack": ids[-1]})
    assert (await http.get(path(data_page) + "?by=owner", headers=headers)).json()["records"][0]["id"] == ack["id"]
    await http.get(f"{acct['path']}?cmd=SITE_DATA&id={data_page['id']}")
    assert (await http.get(path(data_page), headers=headers)).json()["owner_seen"] is not None
    preflight = await http.options(
        path(data_page), headers={**headers, "Access-Control-Request-Headers": "Content-Type"}
    )
    assert preflight.status_code == 204 and preflight.content == b""
    cors(preflight)
    assert preflight.headers["access-control-allow-methods"] == "GET, POST"
    assert preflight.headers["access-control-allow-headers"] == "Content-Type"
    if host == "ss.example":
        res = await http.get(path(data_page).replace("/data", "/other"), headers=headers)
        assert res.status_code == 302 and res.headers["location"].startswith("https://sites.example/")


@pytest.mark.anyio
async def test_modes_and_omission(http, acct, data_page):
    lid, sid = acct["id"], data_page["id"]
    sites.update(lid, sid, data="collect")
    sent = visitor(data_page, {"answer": "private"})
    ack = owner(acct, data_page, {"ack": True})
    headers = {"Host": "sites.example"}
    for query in ("", "?by=visitor", "?by=owner"):
        answer = (await http.get(path(data_page) + query, headers=headers)).json()
        assert [r["id"] for r in answer["records"]] == [ack["id"]]
    assert sites.publish(lid, "# v2", site_id=sid)["data"] == "collect"
    assert sites.update(lid, sid, title="Changed")["data"] == "collect"
    sites.update(lid, sid, data="shared")
    answer = (await http.get(path(data_page) + "?last=20", headers=headers)).json()
    assert [r["id"] for r in answer["records"]] == [sent["id"], ack["id"]]
    for fields in ({"data": "off"}, {"status": "unpublished"}):
        sites.update(lid, sid, **fields)
        res = await http.get(path(data_page), headers=headers)
        assert res.status_code == 404
        cors(res)
        assert len(sites.read_data(lid, sid)["records"]) == 2
        owner(acct, data_page, {})
        sites.clear_data(lid, sid)
        visitor_count = sites.get_site(lid, sid)["records"]
        assert visitor_count == 0
        # The next case starts with two records, still accessible with data off.
        owner(acct, data_page, {})
        owner(acct, data_page, {})


def test_eligibility_and_locking(acct, monkeypatch):
    lid = acct["id"]
    with pytest.raises(ValidationError, match="confirmed email"):
        sites.publish(lid, "# App", data="shared")
    assert sites.list_sites(lid) == []
    p = sites.publish(lid, "# App")
    with pytest.raises(ValidationError):
        sites.update(lid, p["id"], data="collect")
    for value in ("", "yes", 1):
        with pytest.raises(ValidationError):
            sites.publish(lid, "# App", data=value)
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    assert sites.update(lid, p["id"], data="collect")["data"] == "collect"
    with pytest.raises(ValidationError, match="turn data off first"):
        sites.update(lid, p["id"], password="secret")
    sites.update(lid, p["id"], data="off")
    with pytest.raises(ValidationError, match="locked page"):  # both in one call
        sites.update(lid, p["id"], password="secret", data="shared")
    assert not sites.get_site(lid, p["id"])["locked"]
    sites.update(lid, p["id"], password="secret")
    with pytest.raises(ValidationError, match="locked page"):
        sites.update(lid, p["id"], data="shared")
    unlocked = sites.update(lid, p["id"], password="", data="shared")  # one all-or-nothing update
    assert not unlocked["locked"] and unlocked["data"] == "shared"
    relocked = sites.update(lid, p["id"], data="off", password="again")  # and back, in one update
    assert relocked["locked"] and relocked["data"] == "off"
    link = sites.shorten(lid, "https://example.com")
    for mode in ("off", "collect", "shared"):
        with pytest.raises(ValidationError, match="Only a page"):
            sites.update(lid, link["id"], data=mode)


@pytest.mark.anyio
async def test_quotas_charge_minimum_and_downgrade(http, acct, data_page, monkeypatch):
    monkeypatch.setattr(common, "site_data_caps_for", lambda *a: (2_000, 100))
    visitor(data_page, {})
    owner(acct, data_page, {})
    row = db.get_db().execute("SELECT * FROM sites WHERE id = ?", (data_page["id"],)).fetchone()
    assert (row["data_bytes"], row["data_records"]) == (2_000, 2)
    assert db.get_db().execute("SELECT bytes FROM site_data LIMIT 1").fetchone()[0] == 2
    res = await http.post(path(data_page), headers={"Host": "sites.example"}, json={})
    assert res.status_code == 409 and res.json() == {"ok": False, "error": "full"}
    cors(res)
    with pytest.raises(ValidationError, match="Clear all"):
        owner(acct, data_page, {})
    # Account-wide quota, even when the second page is empty.
    other = sites.publish(acct["id"], "# Other", data="shared")
    with pytest.raises(sites.DataFull):
        visitor(other, {})
    monkeypatch.setattr(common, "site_data_caps_for", lambda *a: (0, 0))
    assert len(sites.read_data(acct["id"], data_page["id"])["records"]) == 2
    assert (await http.get(path(data_page), headers={"Host": "sites.example"})).status_code == 200
    sites.clear_data(acct["id"], data_page["id"])
    assert sites.get_site(acct["id"], data_page["id"])["records"] == 0
    monkeypatch.setattr(common, "site_data_caps_for", lambda *a: (100_000, 1))
    visitor(data_page, {})
    with pytest.raises(sites.DataFull):
        visitor(data_page, {})


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        b'{"x":1e400}',
        b'{"x":{"y":NaN}}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":"\xff"}',
        b'{"x":"\\ud800"}',
        b"[]",
        b"null",
        b"3",
        b'{"x":' + b"[" * 10_000 + b"0" + b"]" * 10_000 + b"}",
    ],
    ids=[
        "overflow",
        "nested-nan",
        "infinity",
        "negative-infinity",
        "utf8",
        "surrogate",
        "array",
        "null",
        "number",
        "deep",
    ],
)
async def test_strict_json(http, data_page, body):
    res = await http.post(path(data_page), headers={"Host": "sites.example"}, content=body)
    assert res.status_code == 400
    cors(res)
    assert db.get_db().execute("SELECT COUNT(*) FROM site_data").fetchone()[0] == 0


@pytest.mark.parametrize("data", [{"x": float("inf")}, {"x": {"y": float("nan")}}, {"x": "\ud800"}, [], None])
def test_agents_use_the_same_validation(acct, data_page, data):
    with pytest.raises(ValidationError):
        owner(acct, data_page, data)


@pytest.mark.anyio
async def test_size_limit_and_rate_limits(http, acct, data_page, monkeypatch):
    headers = {"Host": "sites.example"}

    async def chunks():
        for _ in range(5):
            yield b"x" * 65_536

    res = await http.post(path(data_page), headers=headers, content=chunks())
    assert res.status_code == 413
    cors(res)
    with pytest.raises(ValidationError, match="300,000"):
        owner(acct, data_page, {"x": "x" * 300_000})
    for method, limiter in (("GET", ratelimit.data_read_limiter), ("POST", ratelimit.data_write_limiter)):
        monkeypatch.setattr(limiter, "allow", lambda key: False)
        res = await http.request(method, path(data_page), headers=headers, json={})
        assert res.status_code == 429 and res.headers["retry-after"] == "60"
        cors(res)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query",
    [
        "last=0",
        "last=21",
        "last=no",
        "by=admin",
        "bad-key=x",
        "1key=x",
        "a=" + "x" * 201,
        "a=1&b=1&c=1&d=1&e=1&f=1",
        "a=1&a=2",
    ],
)
async def test_bad_filters(http, data_page, query):
    res = await http.get(path(data_page) + "?" + query, headers={"Host": "sites.example"})
    assert res.status_code == 400
    cors(res)


@pytest.mark.anyio
async def test_misses_are_charged_but_a_valid_address_is_served(http, data_page, monkeypatch):
    charged = []
    monkeypatch.setattr(ratelimit.bad_token_limiter, "allow", lambda key: charged.append(key) or False)
    headers = {"Host": "sites.example"}
    assert (await http.get(path(data_page), headers=headers)).status_code == 200
    assert not charged
    for name in ("ZZZZZZZZZZ", "wrong-" + data_page["code"], "bad"):
        res = await http.post(f"/{name}/data", headers=headers, json={})
        assert res.status_code == 429 and res.headers["retry-after"] == "600"
        cors(res)
    assert len(charged) == 3
    # A data path on another app's host is never served.
    assert (await http.get(path(data_page))).status_code == 429


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["unpublish", "off", "lock", "delete", "disable"])
async def test_insert_rechecks_after_lookup(http, acct, data_page, monkeypatch, change):
    original = sites.add_record

    def changed(*args, **kwargs):
        with db.transaction() as conn:
            if change == "disable":
                conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), acct["id"]))
            elif change != "delete":
                field, value = {
                    "unpublish": ("status", "unpublished"),
                    "off": ("data", ""),
                    "lock": ("password_hash", "locked"),
                }[change]
                conn.execute(f"UPDATE sites SET {field} = ? WHERE id = ?", (value, data_page["id"]))
        if change == "delete":
            sites.delete_site(acct["id"], data_page["id"])
        return original(*args, **kwargs)

    monkeypatch.setattr(sites, "add_record", changed)
    res = await http.post(path(data_page), headers={"Host": "sites.example"}, json={})
    assert res.status_code == 404
    cors(res)
    assert db.get_db().execute("SELECT COUNT(*) FROM site_data").fetchone()[0] == 0


def test_owner_paging_counters_and_query_plan(acct, data_page, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    ids = [owner(acct, data_page, {"n": n})["id"] for n in range(2_005)]
    cursor, seen = 0, []
    while True:
        answer = sites.read_data(acct["id"], data_page["id"], cursor, 200)
        assert "untrusted" in answer["warning"]
        seen.extend(r["id"] for r in answer["records"])
        cursor = answer["next"]
        if not answer["more"]:
            break
    assert seen == ids
    conn = db.get_db()
    traced = []
    conn.set_trace_callback(traced.append)
    try:
        owner(acct, data_page, {})
        answer = sites.page_data(path(data_page).split("/")[1], [("n", "missing")])
    finally:
        conn.set_trace_callback(None)
    assert answer["records"] == []
    # Quota work scans only the page counters, independent of the number of records.
    assert any("SUM(data_bytes)" in sql and "FROM sites" in sql for sql in traced)
    assert not any("SUM(" in sql and "FROM site_data " in sql for sql in traced)
    query = next(sql for sql in traced if "id IN (SELECT record_id" in sql)
    plan = " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + query))
    assert "COVERING INDEX idx_site_data_fields" in plan
    sites.clear_data(acct["id"], data_page["id"])
    new = owner(acct, data_page, {})
    assert new["id"] > cursor
    assert sites.read_data(acct["id"], data_page["id"], cursor)["records"][0]["id"] == new["id"]


@pytest.mark.anyio
async def test_answer_byte_stops(http, acct, data_page):
    for n in range(16):
        owner(acct, data_page, {"n": n, "text": "é" * 140_000})
    res = await http.get(path(data_page) + "?last=20", headers={"Host": "sites.example"})
    assert len(res.content) <= 1_000_000
    assert len(res.json()["records"]) == 3 and res.json()["more"]
    assert [r["data"]["n"] for r in res.json()["records"]] == [13, 14, 15]
    answer = sites.read_data(acct["id"], data_page["id"], limit=200)
    assert len(json.dumps(answer, ensure_ascii=False).encode()) <= 4_000_000
    assert len(answer["records"]) == 14 and answer["more"]
    rest = sites.read_data(acct["id"], data_page["id"], answer["next"])
    assert len(rest["records"]) == 2 and not rest["more"]


def test_only_matchable_scalar_fields_are_indexed(acct, data_page):
    visitor(
        data_page, {"object": {}, "array": [], "long": "x" * 201, "bad-key": "x", **{f"f{n}": n for n in range(25)}}
    )
    rows = db.get_db().execute("SELECT key FROM site_data_fields").fetchall()
    assert len(rows) == 20 and {r[0] for r in rows} == {f"f{n}" for n in range(20)}


def test_owner_seen_is_throttled_and_browser_reads_do_not_stamp(acct, data_page, freeze):
    def stamp():
        return db.get_db().execute("SELECT data_read_at FROM sites WHERE id = ?", (data_page["id"],)).fetchone()[0]

    freeze("2026-11-10T12:00:00")
    sites.read_data(acct["id"], data_page["id"], browser=True)
    assert stamp() is None
    sites.read_data(acct["id"], data_page["id"])
    first = stamp()
    freeze("2026-11-10T12:00:29")
    sites.read_data(acct["id"], data_page["id"])
    assert stamp() == first
    freeze("2026-11-10T12:00:30")
    sites.read_data(acct["id"], data_page["id"])
    assert stamp() != first


@pytest.mark.anyio
async def test_agent_tools_and_commands(connect, http, acct, data_page):
    sid = data_page["id"]
    async with connect(f"http://testserver{acct['path']}") as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert tools["site_data"].annotations.read_only_hint is True
        assert tools["site_data_add"].annotations.read_only_hint is False
        assert not any("delete" in name or "clear" in name for name in tools if name.startswith("site_"))
        made = (await call(c, "site_publish", content="# New", data="shared"))["page"]
        assert made["data"] == "shared"
        await call(c, "site_edit", id=made["id"], data="collect")
        for n in range(3):
            await call(c, "site_data_add", id=sid, data={"n": n})
        first = await call(c, "site_data", id=sid, limit=2)
        assert first["more"] and all(r["by"] == "owner" for r in first["records"])
        assert len((await call(c, "site_data", id=sid, since=first["next"]))["records"]) == 1
        for tool in ("site_data", "site_data_add"):
            with pytest.raises(ToolError, match="not found"):
                await c.call_tool(tool, {"id": sid + 999, **({"data": {}} if tool.endswith("add") else {})})
    base = acct["path"]
    assert (await http.get(f"{base}?cmd=SITE_DATA_ADD&id={sid}")).status_code == 405
    res = await http.post(f"{base}?cmd=SITE_DATA_ADD&id={sid}", json={"data": {"ack": True}})
    assert res.status_code == 200
    assert (await http.get(f"{base}?cmd=SITE_DATA&id={sid}&since={first['next']}")).json()["records"][-1]["data"] == {
        "ack": True
    }
    guide = (await http.get(base)).json()
    assert 'const DATA = "<data_url from site_publish or site_get>"' in guide["howto"]["page_data"]
    assert "including visitor records sent while collect" in sites_agent._DATA_GUIDE
    assert not any("DELETE" in cmd or "CLEAR" in cmd for cmd in guide["commands"])
    with db.transaction() as conn:
        lists.set_app_in(conn, acct["id"], "sites", False)
    async with connect(f"http://testserver{base}") as c:
        assert not {"site_data", "site_data_add"} & {t.name for t in await c.list_tools()}
        with pytest.raises(ToolError, match="Simple Sites is off"):
            await c.call_tool("site_data", {"id": sid})


def test_browser_view_clear_and_isolation(served, new_list):
    a, b = new_list(), new_list()
    lid, c = a["list_id"], a["client"]
    confirm_list(lid)
    p = sites.publish(lid, "# App")
    url = f"/api/app/sites/{p['id']}/data"
    assert c.put(f"/api/app/sites/{p['id']}", json={"data": "collect"}).json()["data"] == "collect"
    link = sites.shorten(lid, "https://example.com")
    assert c.put(f"/api/app/sites/{link['id']}", json={"data": "off"}).status_code == 400
    # A real signed-in browser's cookie grants no extra authority at the visitor address.
    res = c.post(
        path(p),
        headers={"Host": "sites.example", "Origin": "null", "Sec-Fetch-Site": "cross-site"},
        json={"by": "owner"},
    )
    assert res.status_code == 200
    cors(res)
    assert sites.read_data(lid, p["id"])["records"][0]["by"] == "visitor"
    sites.clear_data(lid, p["id"])
    ids = [sites.add_record(p["id"], "owner", {"n": n}, list_id=lid)["id"] for n in range(3)]
    res = c.get(url + "?limit=2")
    assert res.headers["cache-control"] == "no-store"
    assert [r["id"] for r in res.json()["records"]] == ids[:0:-1]
    next_page = c.get(url + f"?before={res.json()['next']}").json()
    assert [r["id"] for r in next_page["records"]] == ids[:1] and not next_page["more"]
    for method in ("get", "delete"):
        assert getattr(b["client"], method)(url).status_code == 404
        assert getattr(c, method)(url, headers={"X-List": str(b["list_id"])}).status_code == 409
    assert c.delete(url, headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.delete(url).json() == {"ok": True}
    assert c.get(url).json()["records"] == []
    assert db.get_db().execute("SELECT COUNT(*) FROM site_data_fields").fetchone()[0] == 0
    with pytest.raises(NotFoundError):
        sites.read_data(b["list_id"], p["id"])
    with pytest.raises(NotFoundError):
        sites.add_record(p["id"], "owner", {}, list_id=b["list_id"])


def test_restore_and_delete_carry_records_and_original_ids(acct, data_page, capsys):
    from scripts import admin, restore_list

    rid = visitor(data_page, {"answer": "kept"})["id"]
    snapshot = backup.snapshot()
    sites.delete_site(acct["id"], data_page["id"])
    assert db.get_db().execute("SELECT COUNT(*) FROM site_data").fetchone()[0] == 0
    assert db.get_db().execute("SELECT COUNT(*) FROM site_data_fields").fetchone()[0] == 0
    restore_list.restore(snapshot, acct["id"], db.db_path())
    assert sites.read_data(acct["id"], data_page["id"])["records"][0]["id"] == rid
    assert sites.read_data(acct["id"], data_page["id"], rid)["records"] == []
    row = db.get_db().execute("SELECT data_bytes, data_records FROM sites").fetchone()
    assert tuple(row) == (1_000, 1)
    assert sites.page_data(path(data_page).split("/")[1], [("answer", "kept")])["records"]
    assert admin.main(["delete", str(acct["id"]), f"--yes-delete-list-{acct['id']}", "--no-snapshot"]) == 0
    for table in ("sites", "site_data", "site_data_fields"):
        assert db.get_db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_migration_is_idempotent_and_old_snapshot_restores(acct, data_page):
    from scripts import restore_list

    snapshot = backup.snapshot()
    with sqlite3.connect(snapshot) as conn:
        conn.execute("DROP TABLE site_data_fields")
        conn.execute("DROP TABLE site_data")
        # Rebuild the old definition: SQLite DROP COLUMN can swallow the closing
        # parenthesis into the preceding column's line comment.
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'sites'").fetchone()[0]
        sql = (
            sql[: sql.index("    data ")].replace(
                "DEFAULT '',    -- step 18: the folder", "DEFAULT ''     -- step 18: the folder"
            )
            + ")"
        )
        columns = ", ".join(
            r[1]
            for r in conn.execute("PRAGMA table_info(sites)")
            if r[1]
            not in (
                "data",
                "data_read_at",
                "data_bytes",
                "data_records",
                "host",
                "suspended_at",
                "expires_at",
                "legacy_path",
                "layout",
                "size",
                "client_ref",
                "short_name",
                "short_grace_until",
            )
        )
        conn.execute(sql.replace("sites (", "old_sites (", 1))
        conn.execute(f"INSERT INTO old_sites ({columns}) SELECT {columns} FROM sites")
        conn.execute("DROP TABLE sites")
        conn.execute("ALTER TABLE old_sites RENAME TO sites")
    visitor(data_page, {})
    restore_list.restore(snapshot, acct["id"], db.db_path())
    assert sites.get_site(acct["id"], data_page["id"])["data"] == "off"
    with sqlite3.connect(snapshot, isolation_level=None) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(db._SCHEMA)
        db._migrate(conn)
        db._migrate(conn)
        row = conn.execute("SELECT data, data_read_at, data_bytes, data_records FROM sites").fetchone()
        assert tuple(row) == ("", None, 0, 0)


@pytest.mark.parametrize("prefix", ["", "https://simplesites.app", "https://ss.page"])
def test_data_address_and_whole_query_are_scrubbed(prefix):
    assert logscrub.scrub(f"{prefix}/app-k7Qm2xPa9R/data?name=Personal&email=a%40b.test") == f"{prefix}/***/data?***"
    assert logscrub.scrub(f'GET "{prefix}/app-k7Qm2xPa9R/data?name=Personal" 200') == f'GET "{prefix}/***/data?***" 200'


@pytest.mark.anyio
async def test_program_key_fetch_stamps_owner_seen(http, acct, data_page):
    from backend import keys

    key = keys.create(acct["id"], "Data watcher", app="all", access="read")
    headers = {"Authorization": f"Bearer {key['key']}"}
    res = await http.post("/api/v1/tools/site_data", headers=headers, json={"id": data_page["id"]})
    assert res.status_code == 200 and res.json()["records"] == []
    page = await http.get(path(data_page), headers={"Host": "sites.example"})
    assert page.json()["owner_seen"] is not None
    res = await http.post("/api/v1/tools/site_data_add", headers=headers, json={"id": data_page["id"], "data": {}})
    assert res.status_code == 403


def test_a_page_switched_to_collect_mid_read_shows_no_visitor_record(acct, data_page, monkeypatch):
    stale = sites._data_page(path(data_page).split("/")[1])  # looked up while shared
    sites.update(acct["id"], data_page["id"], data="collect")
    sent = visitor(data_page, {"answer": "private"})
    monkeypatch.setattr(sites, "_data_page", lambda *a, **k: stale)
    answer = sites.page_data(path(data_page).split("/")[1], [("last", "20")])
    assert sent["id"] not in [r["id"] for r in answer["records"]]


@pytest.mark.parametrize("change", [{"data": "off"}, {"status": "unpublished"}])
def test_a_page_closed_mid_read_shows_nothing(acct, data_page, monkeypatch, change):
    owner(acct, data_page, {"ack": 1})
    visitor(data_page, {"answer": "x"})
    stale = sites._data_page(path(data_page).split("/")[1])  # looked up while open
    sites.update(acct["id"], data_page["id"], **change)
    monkeypatch.setattr(sites, "_data_page", lambda *a, **k: stale)
    assert sites.page_data(path(data_page).split("/")[1], [("last", "20")])["records"] == []
