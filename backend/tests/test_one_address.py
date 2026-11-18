"""Path-based apps share a browser session and a single unprefixed agent link."""

import logging
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from backend import apps, lists, logscrub, settings, sites
from backend.tests import test_pages
from backend.tests.conftest import only
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


# ── The hosted service: Notes and Projects at the main address, their hosts old addresses ──

MAIN, NOTES, PROJECTS = "http://todo.example", "http://notes.example", "http://projects.example"


@pytest.fixture()
def hosted(client, monkeypatch):
    """Open signup, a main address, and a host for every other app, as the hosted
    service has. Requests name their host in the URL, so each host keeps its own cookie."""
    monkeypatch.setenv("PUBLIC_BASE_URL", MAIN)
    monkeypatch.setenv("NOTES_BASE_URL", NOTES)
    monkeypatch.setenv("PROJECTS_BASE_URL", PROJECTS)
    monkeypatch.setenv("SITES_BASE_URL", "http://sites.example")
    monkeypatch.setenv("BRAIN_BASE_URL", "http://brain.example")
    return client


def test_hosted_family_apps_live_at_the_main_address(hosted, built):
    config = hosted.get(MAIN + "/api/config").json()
    assert config["moved"] == "" and {key: app["url"] for key, app in config["apps"].items()} == {
        "todo": MAIN,
        "notes": MAIN + "/notes",
        "projects": MAIN + "/projects",
        "sites": "http://sites.example",
        "brain": "http://brain.example",
    }
    for key in ("notes", "projects"):
        page = hosted.get(f"{MAIN}/{key}")
        assert page.status_code == 200
        assert f'<meta name="gtd-app" content="{key}">' in page.text
        assert f'<meta name="gtd-base" content="/{key}">' in page.text
        at_path = hosted.get(f"{MAIN}/{key}/api/config").json()
        assert at_path["app"] == key and at_path["moved"] == "" and at_path["apps"] == config["apps"]
    # Sites and Brain keep their hosts, so they have no path; an old host serves no paths either.
    for path in (MAIN + "/sites/api/config", MAIN + "/brain/api/config", NOTES + "/projects/api/config"):
        assert hosted.get(path).status_code == 404


def test_an_old_host_sends_a_signed_out_visitor_to_the_new_address(hosted, built):
    for path in ("/", "/app", "/app/archive", "/anything"):
        res = hosted.get(NOTES + path, follow_redirects=False)
        assert (res.status_code, res.headers["location"]) == (303, MAIN + "/notes"), path
        assert res.headers["cache-control"] == "no-store"
    assert hosted.get(PROJECTS + "/", follow_redirects=False).headers["location"] == MAIN + "/projects"
    # A sign-in link mailed to the old host is still redeemed there, and the API still answers.
    assert hosted.get(NOTES + "/signin/x", follow_redirects=False).status_code == 200
    assert hosted.get(NOTES + "/api/config").json()["moved"] == MAIN + "/notes"
    assert hosted.get(NOTES + "/icon.svg", follow_redirects=False).status_code == 200  # a real file


def test_an_old_host_keeps_working_signed_in_and_offers_the_way_over(hosted, built):
    made = hosted.post(NOTES + "/api/lists").json()
    assert made["agent_url"].startswith(NOTES + "/link/")
    lid = hosted.get(NOTES + "/api/app/session").json()["list_id"]
    hosted.headers["X-List"] = str(lid)
    assert hosted.get(NOTES + "/", follow_redirects=False).headers["location"] == "/app"
    assert hosted.get(NOTES + "/app", follow_redirects=False).status_code == 200
    # Every link made here still starts with this host: nothing an AI holds changes.
    assert hosted.get(NOTES + "/api/app/agent-link").json()["url"] == made["agent_url"]
    assert hosted.get(NOTES + "/api/app/capture-link").json()["url"].startswith(NOTES + "/c/")
    config = hosted.get(NOTES + "/api/config").json()
    assert config["signed_in"] is True and config["moved"] == MAIN + "/notes"
    # The way over: cookies are per host, so the main address knows nothing of this browser
    # until a sign-in link for the app's new address is redeemed there.
    assert hosted.get(MAIN + "/notes/api/app/session").status_code == 401
    url = hosted.post(NOTES + "/api/app/signin-link?app=notes").json()["url"]
    assert url.startswith(MAIN + "/notes/signin/")
    assert hosted.post(f"{MAIN}/notes/api/signin/{url.rsplit('/', 1)[1]}").status_code == 200
    for prefix in ("/notes", "/projects", ""):
        assert hosted.get(MAIN + prefix + "/api/app/session").json()["list_id"] == lid
    assert hosted.get(MAIN + "/notes/api/app/agent-link").json()["url"].startswith(MAIN + "/link/")


def test_an_agent_link_on_an_old_host_answers_as_before(hosted):
    token = hosted.post(NOTES + "/api/lists").json()["agent_token"]
    guide = hosted.get(f"{NOTES}/link/{token}", headers={"Accept": "application/json"}).json()
    assert guide["mcp"]["url"] == f"{NOTES}/link/{token}"
    listed = hosted.post(
        f"{NOTES}/link/{token}", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    ).json()
    assert {"todo_create", "note_create", "board_create"} <= {t["name"] for t in listed["result"]["tools"]}
    assert hosted.get(f"{NOTES}/link/{token}", params={"cmd": "NOTES"}).json()["ok"] is True
    # The same link at the main address; never under a path.
    assert hosted.get(f"{MAIN}/link/{token}", params={"cmd": "NOTES"}).json()["ok"] is True
    for path in (f"/notes/link/{token}", f"/notes/mcp/{token}"):
        res = hosted.get(MAIN + path)
        assert res.status_code == 404 and "www-authenticate" not in res.headers


def test_same_origin_on_an_old_host_is_that_host(hosted):
    hosted.headers.pop("Sec-Fetch-Site")
    assert hosted.post(NOTES + "/api/lists", headers={"Origin": MAIN}).status_code == 403
    assert hosted.post(NOTES + "/api/lists", headers={"Origin": NOTES}).status_code == 200
    hosted.cookies.clear()
    assert hosted.post(MAIN + "/notes/api/lists", headers={"Origin": NOTES}).status_code == 403
    assert hosted.post(MAIN + "/notes/api/lists", headers={"Origin": MAIN}).status_code == 200


def test_hosted_starting_apps_and_existing_accounts(hosted, built):
    def made(address: str) -> list[str]:
        hosted.cookies.clear()
        return lists.apps_on(lists.resolve_agent(hosted.post(address + "/api/lists").json()["agent_token"]))

    family = [key for key in apps.APPS if key in apps.FAMILY]
    for address in (MAIN, MAIN + "/notes", MAIN + "/projects", NOTES, PROJECTS):
        assert made(address) == family, address
    assert made("http://sites.example") == ["sites"]
    assert made("http://brain.example") == list(apps.APPS)
    # An account from before, with Todo alone: opening Notes turns nothing on.
    hosted.cookies.clear()
    hosted.post(MAIN + "/api/lists")
    lid = hosted.get(MAIN + "/api/app/session").json()["list_id"]
    only(lid, "todo")
    assert hosted.get(MAIN + "/notes/app").status_code == 200
    assert hosted.get(MAIN + "/notes/api/app/session").json()["apps"] == ["todo"]


def test_a_self_hosted_install_with_its_own_hosts_has_no_old_address(single, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", MAIN)
    monkeypatch.setenv("NOTES_BASE_URL", NOTES)
    config = single.get(NOTES + "/api/config").json()
    assert config["moved"] == "" and config["apps"]["notes"]["url"] == NOTES
    assert single.get(NOTES + "/", follow_redirects=False).status_code in (200, 503)  # 503: no built bundle
    assert single.get(MAIN + "/notes/api/config").status_code == 404
    assert set(lists.apps_on(lists.create_list("UTC")["list_id"])) == set(apps.APPS)


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
