"""Path-based apps share a browser session and a single unprefixed agent link."""

import logging
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from backend import apps, lists, logscrub, settings, sites
from backend.tests import test_pages
from backend.tests.test_mcp import MCP_HEADERS

built = test_pages.built


@pytest.fixture()
def single(client, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    for key, app in apps.APPS.items():
        monkeypatch.delenv(app.base_env, raising=False)
    return client


@pytest.mark.parametrize("key", list(apps.APPS))
def test_pages_config_session_and_manifests(single, built, key):
    base = "" if key == "todo" else f"/{key}"
    for path in (base or "/", base + "/"):
        page = single.get(path)
        assert page.status_code == 200
        if base:
            assert f'<meta name="gtd-app" content="{key}">' in page.text
            assert f'<meta name="gtd-base" content="{base}">' in page.text
    config = single.get(base + "/api/config").json()
    assert config["app"] == key
    assert set(config["apps"]) == set(apps.APPS)
    assert config["apps"][key]["url"] == "http://testserver" + base
    redirect = single.get(base + "/app", follow_redirects=False)
    assert redirect.headers["location"] == base + "/"
    made = single.post(base + "/api/lists").json()
    assert made["agent_url"].startswith("http://testserver/link/")
    session = single.get(base + "/api/app/session")
    assert session.headers["cache-control"] == "no-store"
    assert set(session.json()["apps"]) == set(apps.APPS)
    for app in apps.APPS:
        prefix = "" if app == "todo" else "/" + app
        assert single.get(prefix + "/api/app/session").json()["list_id"] == session.json()["list_id"]
    manifest = single.get(base + "/app/manifest.webmanifest").json()
    assert manifest["start_url"] == manifest["scope"] == manifest["id"] == base + "/app"
    page = single.get(base + "/app")
    assert f'href="{base}/app/manifest.webmanifest"' in page.text
    assert single.get(base + "/", follow_redirects=False).headers["location"] == base + "/app"
    capture = lists.get_list(session.json()["list_id"])["capture_token"]
    assert single.get(f"{base}/c/{capture}/manifest.webmanifest").json()["start_url"] == f"{base}/c/{capture}"
    assert f"{base}/c/{capture}/manifest.webmanifest" in single.get(f"{base}/c/{capture}").text


def test_one_agent_link_has_all_tools_and_rejects_prefixed_tokens(single, monkeypatch):
    made = single.post("/notes/api/lists").json()
    token = made["agent_token"]
    tools = single.post(
        f"/link/{token}", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    ).json()
    names = {t["name"] for t in tools["result"]["tools"]}
    assert {"todo_create", "note_create", "board_create", "site_publish", "brain_export_link"} <= names

    def fail(*args, **kwargs):
        pytest.fail("prefixed agent route resolved a token")

    monkeypatch.setattr(lists, "resolve_agent", fail)
    for path in (f"link/{token}", f"mcp/{token}", f"{token}/mcp", "mcp"):
        for method in ("GET", "POST"):
            response = single.request(method, "/notes/" + path)
            assert response.status_code == 404
            assert "www-authenticate" not in response.headers
        assert token not in logscrub.scrub("GET /notes/" + path)


def test_same_origin_create_redeem_and_mail(single, monkeypatch):
    single.headers.pop("Sec-Fetch-Site")
    assert single.post("/notes/api/lists", headers={"Origin": "http://elsewhere"}).status_code == 403
    assert single.post("/notes/api/lists", headers={"Origin": "http://testserver"}).status_code == 200
    lid = single.get("/notes/api/app/session").json()["list_id"]
    single.headers.update({"X-List": str(lid), "Origin": "http://testserver"})
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "signin@example.com")
    sent = []
    from backend import signin

    monkeypatch.setattr(signin, "_send", lambda to, subject, text: sent.append((subject, text)))
    assert single.put("/notes/api/app/email", json={"email": "reader@example.com"}).status_code == 200
    assert "Notes GTD" in sent[0][0] and "http://testserver/notes/signin/" in sent[0][1]
    url = single.post("/notes/api/app/signin-link?app=projects").json()["url"]
    single.cookies.clear()
    assert single.post("/projects/api/signin/" + url.rsplit("/", 1)[1]).status_code == 200
    assert single.get("/brain/api/app/session").json()["list_id"] == lid


def test_sites_visitors_top_level_and_secure_unlock(single, monkeypatch, built):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://testserver")
    with TestClient(single.app, base_url="https://testserver", headers={"Origin": "https://testserver"}) as c:
        c.post("/sites/api/lists")
        lid = c.get("/sites/api/app/session").json()["list_id"]
        c.headers["X-List"] = str(lid)
        page = c.post("/sites/api/app/sites", json={"content": "# Hello"}).json()
        path = urlsplit(page["address"]).path
        assert page["address"].startswith("https://testserver/") and not path.startswith("/sites/")
        response = c.get(path)
        assert response.status_code == 200 and response.headers["content-security-policy"] == sites.SANDBOX
        assert c.put(f"/sites/api/app/sites/{page['id']}", json={"password": "long-password"}).status_code == 200
        assert c.get(path).status_code == 403
        unlock = c.post(path + "/unlock", data={"password": "long-password"}, follow_redirects=False)
        assert unlock.status_code == 303 and "; Secure" in unlock.headers["set-cookie"]
        assert c.get(path).status_code == 200
        data = c.post("/sites/api/app/sites", json={"content": "# Data"}).json()
        assert c.put(f"/sites/api/app/sites/{data['id']}", json={"data": "shared"}).status_code == 200
        data_path = urlsplit(data["address"]).path
        assert c.post(data_path + "/data", json={"hello": "world"}).status_code == 200
        assert c.get(data_path + "/data").headers["access-control-allow-origin"] == "*"
        short = c.post("/sites/api/app/sites/links", json={"url": "https://example.org", "short_name": "hello"}).json()
        assert c.get(short["address"], follow_redirects=False).headers["location"] == "https://example.org"
        for route, method in (
            (path, "GET"),
            (path + "/unlock", "POST"),
            (data_path + "/data", "GET"),
            (data_path + "/data", "POST"),
            ("/hello", "GET"),
        ):
            assert c.request(method, "/sites" + route).status_code == 404
        tries = (path, path + "/unlock", data_path + "/data?secret=private")
        for route in (*tries, *("/sites" + route for route in tries), "/notes" + path):
            record = logging.LogRecord("test", logging.INFO, "", 0, "GET %s", (route,), None)
            logscrub.ScrubTokens().filter(record)
            assert (
                path not in record.getMessage()
                and data_path not in record.getMessage()
                and "private" not in record.getMessage()
            )


def test_configured_hosts_are_unchanged(single, built, monkeypatch):
    before = single.get("/unknown")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    for key, app in apps.APPS.items():
        if key != "todo":
            monkeypatch.setenv(app.base_env, f"https://{key}.example")
    after = single.get("/notes")
    assert (after.status_code, after.headers, after.content) == (before.status_code, before.headers, before.content)
    for key in ("notes", "projects", "sites", "brain"):
        res = single.get("/api/config", headers={"Host": key + ".example"})
        assert res.json()["app"] == key
        assert "gtd-base" not in single.get("/", headers={"Host": key + ".example"}).text
    for key in ("notes", "projects", "brain"):
        monkeypatch.delenv(apps.APPS[key].base_env)
        assert single.get(f"/{key}/api/config").json()["app"] == key
        assert single.get(f"/{key}/api/config", headers={"Host": "sites.example"}).status_code == 404
        assert 'content="sites"' in single.get(f"/{key}", headers={"Host": "sites.example"}).text
        # A host nobody configured is the anchor's, as before: a proxy may have rewritten it.
        assert single.get(f"/{key}/api/config", headers={"Host": "other.example"}).json()["app"] == key


def test_apps_are_reserved_short_names():
    assert set(apps.APPS) <= sites._RESERVED_SHORT


def test_origin_is_reset_after_request(single):
    single.get("/notes/api/config")
    assert settings._origin.get() == ""


def test_unconfigured_links_from_browser_agent_commands_mcp_and_rest(single, built):
    from backend import brain, keys

    made = single.post("/brain/api/lists").json()
    lid = single.get("/brain/api/app/session").json()["list_id"]
    single.headers["X-List"] = str(lid)
    page = single.post("/sites/api/app/sites", json={"content": "# Browser"}).json()
    assert page["address"].startswith("http://testserver/")
    assert single.get(page["address"]).status_code == 200
    link = f"/link/{made['agent_token']}"

    def call(tool, arguments):
        result = single.post(
            link,
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
        ).json()["result"]
        assert not result.get("isError"), result
        return result["structuredContent"]

    agent_page = call("site_publish", {"content": "# Agent"})["page"]
    assert agent_page["address"].startswith("http://testserver/")
    assert single.get(agent_page["address"]).status_code == 200
    export = call("brain_export_link", {})["link"]
    assert export.startswith("http://testserver/brain/app/connect")
    assert single.get(export).status_code == 200
    memory = brain.remember(brain.first_brain(lid), ["Remember this"])["added"][0]
    forget = call("brain_forget_link", {"kind": "memory", "id": memory["id"]})["link"]
    assert forget.startswith("http://testserver/brain/app/")
    assert single.get(forget).status_code == 200
    command = single.get(link, params={"cmd": "SITES"}).json()
    assert "http://testserver/" in str(command) and "/sites/" not in str(command)
    key = keys.create(lid, "script", "all", "write")["key"]
    rest = single.post("/api/v1/tools/brain_export_link", headers={"Authorization": f"Bearer {key}"}, json={})
    assert rest.status_code == 200 and "http://testserver/brain/app/connect" in rest.text
    assert settings._origin.get() == ""


def test_prefixes_do_not_rewrite_short_or_content_hosts(single, monkeypatch):
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_SHORT_URL", "https://short.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    response = single.get("/notes", headers={"Host": "short.example"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://sites.example/notes"
    for path in ("/notes", "/notes/api/config", "/sites/app"):
        assert single.get(path, headers={"Host": "absent.content.example"}).status_code == 404
    assert single.post("/notes/api/lists", headers={"Host": "short.example"}).status_code == 404


def test_origin_is_local_to_concurrent_requests_and_resets_on_error(single):
    import asyncio
    from backend.main import _AppPrefix

    async def exercise():
        arrived = 0
        ready = asyncio.Event()
        seen = {}

        async def endpoint(scope, receive, send):
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                ready.set()
            await ready.wait()
            seen[scope["server"][0]] = await asyncio.to_thread(settings.app_url, "brain")
            raise ValueError("endpoint failed")

        middleware = _AppPrefix(endpoint)

        async def request(host):
            scope = {
                "type": "http",
                "method": "GET",
                "scheme": "http",
                "server": (host, 80),
                "path": "/notes/api/config",
                "root_path": "",
                "query_string": b"",
                "headers": [(b"host", host.encode())],
            }
            with pytest.raises(ValueError, match="endpoint failed"):
                await middleware(scope, None, None)
            assert settings._origin.get() == ""

        await asyncio.gather(request("first.example"), request("second.example"))
        assert seen == {"first.example": "http://first.example/brain", "second.example": "http://second.example/brain"}

    asyncio.run(exercise())


def test_a_trailing_slash_redirect_keeps_the_prefix(single):
    res = single.get("/notes/api/config/", follow_redirects=False)
    assert res.status_code == 307 and urlsplit(res.headers["location"]).path == "/notes/api/config"
    assert single.get("/notes/api/config/").json()["app"] == "notes"
    res = single.get("/api/config/", follow_redirects=False)
    assert urlsplit(res.headers["location"]).path == "/api/config"


def test_a_short_link_cannot_point_at_a_short_address_on_the_main_host(single, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    with TestClient(single.app, headers={"Origin": "http://testserver"}) as c:
        c.post("/sites/api/lists")
        c.headers["X-List"] = str(c.get("/sites/api/app/session").json()["list_id"])
        for url in (
            "http://testserver/loop",
            "http://testserver/other-name/",
            "http://testserver/AbCdEf1234",
            "http://testserver/%6Coop",  # the server decodes it to /loop
            "http://testserver/x/../loop",  # and a browser resolves this one
        ):
            res = c.post("/sites/api/app/sites/links", json={"url": url, "short_name": "loop"})
            assert res.status_code == 400, url
        # The apps' own paths, and anything deeper, are ordinary targets.
        for url in ("http://testserver/notes", "http://testserver/brain/app/connect"):
            assert c.post("/sites/api/app/sites/links", json={"url": url}).status_code == 200, url


def test_another_apps_host_never_stands_in_for_the_main_address(single, monkeypatch):
    # Sites has its own domain and no main address is configured: on the Sites host the
    # other apps have no address to offer, since their paths are served on the main host only.
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    on_sites = single.get("/api/config", headers={"Host": "sites.example"}).json()
    assert on_sites["app"] == "sites" and on_sites["apps"] == {
        "sites": {"title": "Simple Sites", "url": "https://sites.example"}
    }
    assert single.get("/notes/api/config", headers={"Host": "sites.example"}).status_code == 404
    on_main = single.get("/api/config").json()["apps"]
    assert on_main["notes"]["url"] == "http://testserver/notes" and on_main["sites"]["url"] == "https://sites.example"
