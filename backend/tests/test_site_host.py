"""Isolated body pages, rollout gates and all the old serving paths."""

import asyncio
import re
import sqlite3
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from backend import common, db, lists, logscrub, ratelimit, sessions, settings, site_host, sites
from backend.common import ValidationError
from backend.tests.conftest import turn_on


@pytest.fixture()
def hosted(L, monkeypatch, confirm):
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_SHORT_URL", "https://ss.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    monkeypatch.delenv("SITES_CONTENT_LISTS", raising=False)
    confirm(L)
    turn_on(L, "sites")
    ratelimit.clear_all()
    sites.flush_views()
    return L


@pytest.fixture()
def browser(hosted):
    from backend.main import app

    with TestClient(app, follow_redirects=False) as client:
        yield client


def row(site):
    return db.get_db().execute("SELECT * FROM sites WHERE id = ?", (site["id"],)).fetchone()


def old_url(site, base="https://ss.example"):
    path = f"{site['name']}-{site['code']}" if site["name"] else site["code"]
    return f"{base}/{path}"


def test_body_headers_etags_views_and_old_redirects(hosted, browser):
    page = sites.publish(hosted, "<!doctype html><title>Deck</title><p>Hello</p>", "html", name="deck")
    url = page["address"]
    response = browser.get(url)
    assert response.status_code == 200 and response.text == sites.render(row(page))
    assert "content-security-policy" not in response.headers
    for name, expected in {
        "origin-agent-cluster": "?1",
        "x-content-type-options": "nosniff",
        "x-robots-tag": "noindex, nofollow",
        "referrer-policy": "strict-origin-when-cross-origin",
        "cache-control": "no-cache",
    }.items():
        assert response.headers[name] == expected
    etag = response.headers["etag"]
    assert browser.head(url, headers={"sec-fetch-dest": "document"}).content == b""
    assert sites.flush_views() == 0
    cached = browser.get(url, headers={"if-none-match": etag, "sec-fetch-dest": "document"})
    assert cached.status_code == 304 and cached.content == b""
    assert cached.headers["origin-agent-cluster"] == "?1"
    assert sites.flush_views() == 1
    assert browser.get(url, headers={"sec-fetch-dest": "document"}).status_code == 200
    assert sites.flush_views() == 1
    for base in ("https://ss.example", "https://sites.example"):
        redirect = browser.get(old_url(page, base))
        assert redirect.status_code == 302 and redirect.headers["location"] == url
    sites.publish(hosted, "Changed", site_id=page["id"])
    assert browser.get(url, headers={"if-none-match": etag}).status_code == 200
    link = sites.shorten(hosted, "https://outside.example", name="go")
    assert row(link)["host"] is None and link["address"] == old_url(link)
    assert browser.get(link["address"]).headers["location"] == "https://outside.example"


def test_hosts_normalize_and_session_resolution_never_runs(hosted, browser, monkeypatch):
    page = sites.publish(hosted, "Hello")
    host = urlsplit(page["address"]).netloc
    assert browser.get("/", headers={"host": host.upper() + ".:8443"}).status_code == 200
    calls = []

    def probe(cookie):
        calls.append(cookie)
        return None

    monkeypatch.setattr(sessions, "resolve", probe)
    for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        for path in ("/api/app/session", "/mcp", "/signin", "/link/anything", "/assets/app.js"):
            assert browser.request(method, page["address"] + path[1:]).status_code == 404
    assert calls == []
    for host in ("nested." + host, "unknown.content.example", "content.example"):
        browser.get("/api/app/session", headers={"host": host})
    assert calls == []
    # These are outside the content domain; the normal app still owns them.
    for host in ("notcontent.example", "x.content.example.evil", "content.example.evil"):
        assert browser.get("/api/app/session", headers={"host": host}).status_code == 401
    assert len(calls) == 3
    info = browser.get("https://content.example/")
    assert info.status_code == 200 and f"abuse@{settings.sites_content_domain()}" in info.text
    missing = browser.get("https://unknown.content.example/")
    assert missing.status_code == 404 and f"abuse@{settings.sites_content_domain()}" in missing.text


@pytest.mark.parametrize(
    "headers",
    [[], [(b"host", b"one.content.example"), (b"host", b"two.content.example")]]
    + [
        [(b"host", value)]
        for value in (
            b"",
            b"x.content.example:bad",
            b"x.content.example:65536",
            b"x.content.example:",
            b"x.content.example..",
            b"x..content.example",
            b"-x.content.example",
            b"x_.content.example",
            b"x.content.example/",
            b"x.content.example@evil",
            b"x.content.example,evil",
            b"x.content.example\t",
            b"https://x.content.example",
            b"[::1]evil",
        )
    ],
)
def test_invalid_host_never_reaches_inner_app(hosted, headers):
    calls, messages = [], []

    async def inner(scope, receive, send):
        calls.append(scope)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    asyncio.run(
        site_host.SiteHost(inner)({"type": "http", "method": "GET", "path": "/", "headers": headers}, receive, send)
    )
    assert not calls
    assert messages[0]["status"] == 400


def test_locked_pass_before_304_password_rotation_and_unlock_limits(hosted, browser, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")  # self-hosters may lock pages
    page = sites.publish(hosted, "Secret")
    url = page["address"]
    etag = browser.get(url).headers["etag"]
    sites.update(hosted, page["id"], password="first")
    for path in ("", "missing", "api/app/session"):
        response = browser.get(url + path, headers={"if-none-match": etag})
        assert response.status_code == 403 and "Secret" not in response.text
        assert 'action="/__simplesites/unlock"' in response.text
        assert response.headers["cache-control"] == "no-store"
    unlock = url + "__simplesites/unlock"
    for origin in (None, "https://sites.example", "https://sibling.content.example", "https://content.example"):
        response = browser.post(unlock, data={"password": "first"}, headers={"origin": origin} if origin else {})
        assert response.status_code == 403 and "set-cookie" not in response.headers
    own = {"origin": url.rstrip("/")}
    assert browser.post(unlock, data={"password": "wrong"}, headers=own).status_code == 403
    assert browser.post(unlock, content=b"x" * 3000, headers=own).status_code == 413
    response = browser.post(unlock, data={"password": "first"}, headers=own)
    assert response.status_code == 303 and response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    for part in ("__Host-ss-pass=", "Secure", "HttpOnly", "Path=/", "SameSite=lax"):
        assert part in cookie
    assert "Domain=" not in cookie
    saved = browser.cookies.get("__Host-ss-pass")
    assert browser.get(url, headers={"if-none-match": etag}).status_code == 304
    assert browser.get(url).status_code == 200
    sites.update(hosted, page["id"], password="second")
    assert browser.get(url, headers={"if-none-match": etag}).status_code == 403
    assert not sites.unlocked(row(page), saved)

    def busy(*args):
        raise sites.Busy()

    monkeypatch.setattr(sites, "check_password", busy)
    response = browser.post(unlock, data={"password": "second"}, headers=own)
    assert response.status_code == 429 and response.headers["retry-after"] == "5"
    monkeypatch.setattr(ratelimit.password_limiter, "allow", lambda key: False)
    response = browser.post(unlock, data={"password": "second"}, headers=own)
    assert response.status_code == 429 and response.headers["retry-after"] == "600"


def test_service_workers_refused_and_valid_hosts_survive_wrong_link_limit(hosted, browser, monkeypatch):
    page = sites.publish(hosted, "Hello")
    for url in (
        page["address"],
        page["address"] + "sw.js",
        "https://content.example/sw.js",
        "https://nested.x.content.example/sw.js",
    ):
        assert browser.get(url, headers={"Service-Worker": "script"}).status_code == 403
    monkeypatch.setattr(ratelimit.bad_token_limiter, "allow", lambda key: False)
    assert browser.get("https://unknown.content.example/").status_code == 429
    assert browser.get(page["address"]).status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("suspended_at", "2026-01-01T00:00:00.000Z"),
        ("expires_at", "2026-11-15T12:00:00.000Z"),
        ("status", "unpublished"),
    ],
)
def test_unservable_on_every_public_route(hosted, browser, freeze, field, value):
    freeze("2026-11-15T12:00:00")
    page = sites.publish(hosted, "Hello", data="shared")
    sites.add_record(page["id"], "owner", {"x": 1}, list_id=hosted)
    with db.transaction() as conn:
        conn.execute(f"UPDATE sites SET {field} = ? WHERE id = ?", (value, page["id"]))
    host_response = browser.get(page["address"])
    assert host_response.status_code == 404
    if field != "expires_at":
        assert host_response.headers["clear-site-data"] == '"cache", "storage"'
    for base in ("https://ss.example", "https://sites.example"):
        old = old_url(page, base)
        assert browser.get(old).status_code == 404
        assert (
            browser.post(old + "/unlock", data={"password": "x"}, headers={"sec-fetch-site": "same-origin"}).status_code
            == 404
        )
        for method in ("GET", "POST", "OPTIONS"):
            response = browser.request(method, old + "/data", json={"x": 1})
            assert response.status_code == 404
            assert response.headers["access-control-allow-origin"] == "*"
    if field == "suspended_at":
        sites.publish(hosted, "Replacement", site_id=page["id"])
        sites.update(hosted, page["id"], status="published")
        assert row(page)["suspended_at"] == value
        assert browser.get(page["address"]).status_code == 404


def test_disabled_and_removed_accounts_have_no_host(hosted, browser, monkeypatch, freeze):
    page = sites.publish(hosted, "Hello")
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), hosted))
    assert browser.get(page["address"]).status_code == 404
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET disabled_at = NULL, email_verified_at = NULL, created_at = ?, last_used_at = NULL WHERE id = ?",
            ("2020-01-01T00:00:00.000Z", hosted),
        )
    monkeypatch.setenv("RESEND_API_KEY", "test")
    monkeypatch.setenv("MAIL_FROM", "test@example.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    freeze("2026-11-15T12:00:00")
    assert browser.get(page["address"]).status_code == 404


def test_data_addresses_never_move_when_toggled(hosted, browser):
    for legacy in (False, True):
        page = sites.publish(hosted, "Hello", data="shared")
        if legacy:
            with db.transaction() as conn:
                conn.execute("UPDATE sites SET legacy_path = 1 WHERE id = ?", (page["id"],))
        expected = old_url(page) if legacy else page["address"]
        for mode in ("off", "collect", "shared", "off"):
            changed = sites.update(hosted, page["id"], data=mode)
            assert changed["address"] == expected
            assert sites.get_site(hosted, page["id"])["address"] == expected
            assert sites.get_site(hosted, page["id"])["data_url"] == old_url(page) + "/data"
            response = browser.get(old_url(page))
            assert response.status_code == (200 if legacy else 302)
            if legacy:
                assert response.headers["content-security-policy"] == sites.SANDBOX
                assert sites.lookup_host(row(page)["host"]) is None
        if legacy:
            changed = sites.publish(hosted, "Replacement", site_id=page["id"])
            assert changed["address"] == page["address"]
            assert row(page)["legacy_path"] == 0
            assert browser.get(old_url(page)).status_code == 302


def test_new_data_page_uses_absolute_cross_origin_data_url(hosted, browser):
    from backend import sites_agent

    page = sites.publish(hosted, "Hello", data="shared")
    assert page["data_url"] == old_url(page) + "/data"
    assert "data_url" in sites_agent._DATA_SNIPPET
    assert "location.pathname" not in sites_agent._DATA_SNIPPET
    response = browser.post(page["data_url"], json={"hello": "world"}, headers={"Origin": page["address"].rstrip("/")})
    assert response.status_code == 200
    response = browser.get(page["data_url"])
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == "*"
    assert response.json()["records"][0]["data"] == {"hello": "world"}
    assert browser.get(page["address"] + "data").status_code == 404


def test_rollout_gate_covers_all_addresses_and_lookups(hosted, browser, monkeypatch, confirm):
    other = lists.create_list("UTC")["list_id"]
    confirm(other)
    pages = [sites.publish(lid, "Hello") for lid in (hosted, other)]
    monkeypatch.setenv("SITES_CONTENT_LISTS", f" {hosted}, 999999 ")
    for lid, page, allowed in zip((hosted, other), pages, (True, False)):
        expected = page["address"] if allowed else old_url(page)
        assert sites.get_site(lid, page["id"])["address"] == expected
        assert sites.list_sites(lid)[0]["address"] == expected
        assert bool(sites.lookup_host(row(page)["host"])) is allowed
        assert browser.get(page["address"]).status_code == (200 if allowed else 404)
        assert browser.get(old_url(page)).status_code == (302 if allowed else 200)
    monkeypatch.setenv("SITES_CONTENT_LISTS", "")
    assert not sites.hosted(row(pages[0]))
    monkeypatch.delenv("SITES_CONTENT_LISTS")
    assert sites.hosted(row(pages[1]))
    monkeypatch.delenv("SITES_CONTENT_DOMAIN")
    assert sites.get_site(hosted, pages[0]["id"])["address"] == old_url(pages[0])
    response = browser.get(old_url(pages[0]))
    assert response.status_code == 200 and response.headers["content-security-policy"] == sites.SANDBOX


def test_domain_requires_sites_and_rejects_schemes(hosted, monkeypatch):
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "CoNtEnT.Example.")
    assert settings.sites_content_domain() == "content.example"
    monkeypatch.delenv("SITES_BASE_URL")
    assert settings.sites_content_domain() == ""
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "https://content.example")
    with pytest.raises(ValueError):
        settings.sites_content_domain()


@pytest.mark.parametrize("name,prefix", [("-demo", "demo"), ("---", ""), ("a--b", "a-b"), ("a" * 20, "a" * 20)])
def test_host_labels_and_twenty_character_names(hosted, name, prefix):
    page = sites.publish(hosted, "Hello", name=name)
    assert sites._host_label(name) == prefix
    assert re.fullmatch((prefix + "-" if prefix else "") + "[a-z0-9]{12}", row(page)["host"])
    assert page["name"] == name
    assert sites.lookup(urlsplit(old_url(page)).path[1:])["id"] == page["id"]
    with pytest.raises(ValidationError, match="up to 20"):
        sites.publish(hosted, "Hello", name="a" * 21)


def test_migration_backfills_hosts_and_legacy_paths_once(hosted, monkeypatch):
    pages = [
        sites.publish(hosted, "Hello", name=name, data=data)
        for name, data in (
            ("-demo", "collect"),
            ("---", "shared"),
            ("a--b", "off"),
        )
    ]
    link = sites.shorten(hosted, "https://outside.example")
    # Data off at migration time, but its HTML still uses the old path-built snippet.
    old_js = sites.publish(hosted, '<script>fetch(location.pathname + "/data")</script>', data="off")
    with db.transaction() as conn:
        conn.execute("DROP INDEX idx_sites_host")
        for column in ("host", "suspended_at", "expires_at", "legacy_path"):
            conn.execute(f"ALTER TABLE sites DROP COLUMN {column}")
    db.init_db()
    hosts = []
    for page, prefix, legacy in zip(pages, ("demo-", "", "a-b-"), (1, 1, 0)):
        current = row(page)
        assert re.fullmatch(prefix + "[a-z0-9]{12}", current["host"])
        hosts.append(current["host"])
        assert current["legacy_path"] == legacy
        assert current["suspended_at"] is None and current["expires_at"] is None
    assert row(link)["host"] is None
    assert row(old_js)["legacy_path"] == 1
    sites.publish(hosted, "New content", site_id=pages[0]["id"])
    db.init_db()
    assert [row(page)["host"] for page in pages] == hosts
    assert row(pages[0])["legacy_path"] == 0
    assert row(pages[1])["legacy_path"] == 1
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as conn:
        conn.execute("UPDATE sites SET host = ? WHERE id = ?", (hosts[0], pages[1]["id"]))
    # Collision handling on insert and on a partially migrated database.
    codes = iter((hosts[0][-12:], "z" * 12))
    monkeypatch.setattr(sites, "_host_code", lambda: next(codes))
    newer = sites.publish(hosted, "Hello", name="demo")
    assert row(newer)["host"] == "demo-" + "z" * 12
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET host = NULL WHERE id = ?", (newer["id"],))
    codes = iter((hosts[0][-12:], "y" * 12))
    db.init_db()
    assert row(newer)["host"] == "demo-" + "y" * 12


def test_logscrub_masks_host_codes_and_twenty_character_paths(hosted):
    label = "a" * 20 + "-abc123def456"
    for text in (
        f"https://{label}.content.example/",
        f"Host: {label}.content.example:8443",
        f"'{label.upper()}.CONTENT.EXAMPLE.'",
        f"Host: {label}.content.example@evil",
        f"(b'host', b'{label}.content.example\\x00junk')",
    ):
        clean = logscrub.scrub(text)
        assert "abc123def456" not in clean.lower() and "***.content.example" in clean
    address = "a" * 20 + "-Ab123Cd456"
    for text in (
        f"https://ss.example/{address}",
        f"GET /{address} HTTP/1.1",
        f"GET /{address}/data?secret=hidden HTTP/1.1",
    ):
        clean = logscrub.scrub(text)
        assert address not in clean and "hidden" not in clean


def test_unlock_treats_explicit_https_port_as_same_origin(hosted, browser, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    page = sites.publish(hosted, "Secret")
    sites.update(hosted, page["id"], password="pass")
    host = urlsplit(page["address"]).netloc
    response = browser.post(
        page["address"] + "__simplesites/unlock",
        headers={"Host": host + ":443", "Origin": f"https://{host}"},
        data={"password": "pass"},
    )
    assert response.status_code == 303
    response = browser.post(
        page["address"] + "__simplesites/unlock",
        headers={"Host": host + ":8443", "Origin": f"https://{host}"},
        data={"password": "pass"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("field", ["suspended_at", "expires_at"])
def test_data_query_rechecks_eligibility_after_lookup(hosted, monkeypatch, freeze, field):
    freeze("2026-11-15T12:00:00")
    page = sites.publish(hosted, "Hello", data="shared")
    path = urlsplit(old_url(page)).path[1:]
    sites.add_record(page["id"], "owner", {"private": "record"}, list_id=hosted)
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET expires_at = ? WHERE id = ?", ("2026-11-16T12:00:00.000Z", page["id"]))
    assert sites.lookup_host(row(page)["host"]) is not None
    original = sites._data_page

    def take_down(*args, **kwargs):
        found = original(*args, **kwargs)
        with db.transaction() as conn:
            conn.execute(f"UPDATE sites SET {field} = ? WHERE id = ?", (common.now_iso(), page["id"]))
        return found

    monkeypatch.setattr(sites, "_data_page", take_down)
    assert sites.page_data(path, [])["records"] == []


def test_republishing_the_old_data_snippet_keeps_a_legacy_page_on_its_path(hosted, browser):
    page = sites.publish(hosted, '<script>const DATA = location.pathname + "/data";</script>', data="shared")
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET legacy_path = 1 WHERE id = ?", (page["id"],))
    edited = '<p>Edited</p><script>const DATA = location.pathname + "/data";</script>'
    assert sites.publish(hosted, edited, site_id=page["id"])["address"] == old_url(page)
    assert row(page)["legacy_path"] == 1
    assert browser.get(old_url(page)).status_code == 200


def test_hostless_page_keeps_its_path_address(hosted):
    page = sites.publish(hosted, "Hello")
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET host = NULL WHERE id = ?", (page["id"],))
    assert sites.get_site(hosted, page["id"])["address"] == old_url(page)


def test_restore_keeps_live_host_and_takedown_and_fixes_old_snapshots(hosted):
    from backend import backup
    from scripts import restore_list

    data_page = sites.publish(hosted, '<script>location.pathname + "/data"</script>', data="shared")
    plain = sites.publish(hosted, "Plain")
    gone = sites.publish(hosted, "Deleted later")
    snapshot = backup.snapshot()
    assert snapshot is not None
    # An old snapshot: taken before this PR's columns existed.
    old = sqlite3.connect(snapshot)
    old.execute("DROP INDEX IF EXISTS idx_sites_host")
    for column in ("legacy_path", "host", "suspended_at"):
        old.execute(f"ALTER TABLE sites DROP COLUMN {column}")
    old.commit()
    old.close()
    live_host = row(plain)["host"]
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET suspended_at = ? WHERE id = ?", (common.now_iso(), plain["id"]))
    sites.delete_site(hosted, gone["id"])
    restore_list.restore(snapshot, hosted, db.db_path())
    assert row(plain)["host"] == live_host and row(plain)["suspended_at"] is not None
    assert row(gone)["host"] and sites.hosted(row(gone))
    assert row(data_page)["legacy_path"] == 1


def test_old_address_redirect_keeps_the_query(hosted, browser):
    page = sites.publish(hosted, "Hello")
    response = browser.get(old_url(page) + "?lang=fr&who=ann")
    assert response.status_code == 302 and response.headers["location"] == page["address"] + "?lang=fr&who=ann"
