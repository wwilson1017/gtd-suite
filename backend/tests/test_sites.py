"""Simple Sites (sites.py, sites_agent.py, site_routes.py, pages.py's Sites branch):
pages and short links at short addresses, against the real app and a real SQLite file."""

import datetime
import json
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from backend import apps, cleanup, common, db, lists, logscrub, ratelimit, settings, sites
from backend.common import NotFoundError, ValidationError
from backend.tests.conftest import confirm_list, turn_on
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    MCP_HEADERS,
    anyio_backend,
    app,
    call,
    connect,
    http,
)

SITES = "https://sites.example"
ON_SITES = {"Host": "sites.example"}


@pytest.fixture()
def served(monkeypatch):
    """A server that serves Simple Sites at its own address."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    monkeypatch.setenv("SITES_BASE_URL", SITES)


@pytest.fixture()
def acct(served, todo_db):
    """A list with Sites turned on; its id, agent link path and the made dict."""
    made = lists.create_list("UTC")
    turn_on(made["list_id"], "sites")
    return {**made, "id": made["list_id"], "path": f"/link/{made['agent_token']}"}


def page(list_id, content="# Hello\n\nWorld", fmt="markdown", **kw) -> dict:
    return sites.publish(list_id, content, fmt, **kw)


def path_of(site: dict) -> str:
    return site["address"].removeprefix(SITES)


# ── Publishing ────────────────────────────────────────────────────────────────


def test_a_page_gets_a_short_address_and_keeps_it_through_updates(acct):
    confirm_list(acct["id"])  # This test needs multiple pages.
    lid = acct["id"]
    made = page(lid, name="menu")
    assert made["address"] == f"{SITES}/menu-{made['code']}"
    assert sites.ADDRESS_RE.fullmatch(made["code"]) and len(made["code"]) == 10
    assert (made["title"], made["format"], made["status"]) == ("Hello", "markdown", "published")
    again = sites.publish(lid, "# Better", site_id=made["id"])
    assert (again["address"], again["title"]) == (made["address"], "Hello")  # title kept
    assert sites.get_site(lid, made["id"])["content"] == "# Better"
    # The name is fixed: the same one is fine, another is refused and changes nothing.
    sites.publish(lid, "# Same name", site_id=made["id"], name="menu")
    with pytest.raises(ValidationError, match="name is fixed"):
        sites.publish(lid, "# Moved", site_id=made["id"], name="lunch")
    assert sites.get_site(lid, made["id"])["content"] == "# Same name"
    plain = page(lid)
    assert plain["address"] == f"{SITES}/{plain['code']}" and plain["name"] == ""


def test_the_title_defaults_to_the_heading_or_the_html_title(acct):
    confirm_list(acct["id"])  # This test needs multiple pages.
    assert page(acct["id"], "intro\n\n#  Big Day  #\n")["title"] == "Big Day"
    assert page(acct["id"], "# C#\n")["title"] == "C#"
    assert page(acct["id"], "<TITLE lang=en>Q3 &amp; more</TITLE><p>x", "html")["title"] == "Q3 & more"
    assert page(acct["id"], "İİ<title>İstanbul</title>", "html")["title"] == "İstanbul"
    assert page(acct["id"], "no heading", title="  Given ")["title"] == "Given"


def test_finding_a_title_in_a_hostile_page_takes_no_time(acct):
    confirm_list(acct["id"])  # This test needs multiple pages.
    # Shapes that make a backtracking pattern quadratic; this runs under the write lock.
    import time

    start = time.monotonic()
    page(acct["id"], "# a" + " " * 1_000_000 + "b")
    page(acct["id"], "# " + "#" * 1_000_000 + "x")
    page(acct["id"], "<title>" * 200_000, "html")
    assert time.monotonic() - start < 2


def test_an_insert_for_a_list_that_is_gone_fails_instead_of_retrying(acct):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        page(acct["id"] + 999)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"content": ""}, "content is required"),
        ({"content": "  \n"}, "content is required"),
        ({"fmt": "pdf"}, "format must be"),
        ({"name": "Menu"}, "name is up to 20"),
        ({"name": "a" * 21}, "name is up to 20"),
        ({"name": "a_b"}, "name is up to 20"),
    ],
)
def test_bad_input_is_refused_and_makes_nothing(acct, kwargs, message):
    with pytest.raises(ValidationError, match=message):
        sites.publish(acct["id"], kwargs.get("content", "x"), kwargs.get("fmt", "markdown"), name=kwargs.get("name"))
    assert sites.list_sites(acct["id"]) == []


def test_a_page_is_at_most_two_megabytes_of_utf8(acct):
    page(acct["id"], "x" * common.SITE_MAX_BYTES)
    with pytest.raises(ValidationError, match="at most 2 MB"):
        page(acct["id"], "x" * (common.SITE_MAX_BYTES + 1))
    # Counted in bytes, not characters: é is two.
    with pytest.raises(ValidationError, match="at most 2 MB"):
        page(acct["id"], "é" * (common.SITE_MAX_BYTES // 2 + 1))


# ── Short links ───────────────────────────────────────────────────────────────


def test_a_short_link_needs_a_confirmed_email_and_a_real_outside_address(acct):
    lid = acct["id"]
    with pytest.raises(
        ValidationError, match=r"need a confirmed email\. Confirm one in Settings \(Connect, in Common Brain\)\."
    ):
        sites.shorten(lid, "https://example.com")
    confirm_list(lid)
    link = sites.shorten(lid, "https://example.com/a?b=c", name="docs", title="Docs")
    assert (link["kind"], link["target"], link["title"]) == ("link", "https://example.com/a?b=c", "Docs")
    assert link["address"] == f"{SITES}/docs-{link['code']}" and "format" not in link
    for bad in (
        "example.com",
        "ftp://example.com",
        "javascript:alert(1)",
        f"{SITES}/x",
        "https://sites.example:443/x",
        "https://SITES.example./x",
        "https://sites.example@evil.com/",
        "https://user:pw@example.com/",
        "https://%73ites.example/x",
        "https://ｓｉｔｅｓ.example/x",
        "https://sites.example\u3002/x",
        "https://sites.example\uff0e/x",
        "https://sites.example\uff61/x",
        "https://example.com:99999/",
        "https://" + "a" * 2_000 + ".com",
    ):
        with pytest.raises(ValidationError):
            sites.shorten(lid, bad)
    assert sites.shorten(lid, "HTTPS://Example.com/x")["target"] == "HTTPS://Example.com/x"


# ── Caps ──────────────────────────────────────────────────────────────────────


def test_one_page_before_an_email_is_confirmed_and_five_hundred_after(acct):
    lid = acct["id"]
    made = [page(lid)]
    with pytest.raises(
        ValidationError, match=r"holds 1 page until an email is confirmed in Settings \(Connect, in Common Brain\)\."
    ):
        page(lid)
    # Updating and republishing are never capped; unpublished pages still count.
    sites.publish(lid, "# New", site_id=made[0]["id"])
    sites.update(lid, made[0]["id"], status="unpublished")
    sites.update(lid, made[0]["id"], status="published")
    sites.update(lid, made[0]["id"], status="unpublished")
    with pytest.raises(ValidationError):
        page(lid)
    # Deleting frees a place.
    sites.delete_site(lid, made[0]["id"])
    page(lid)
    confirm_list(lid)
    for _ in range(499):
        page(lid)
    with pytest.raises(ValidationError, match="holds 500 pages, the limit"):
        page(lid)
    for _ in range(500):
        sites.shorten(lid, "https://example.com")
    with pytest.raises(ValidationError, match="holds 500 links"):
        sites.shorten(lid, "https://example.com")


def test_a_one_list_self_host_keeps_the_big_caps(served, monkeypatch):
    assert common.site_caps_for(False, False) == common.SITE_SELF_HOST_CAPS
    assert common.site_caps_for(True, True) == (500, 500)
    assert common.site_caps_for(False, True) == (1, 0)


# ── One write path: all or nothing ────────────────────────────────────────────


def test_an_update_keeps_the_pages_format_unless_given(acct):
    doc = page(acct["id"], "<!doctype html><html><body>v1</body></html>", "html")
    assert sites.publish(acct["id"], "<!doctype html><html>v2</html>", site_id=doc["id"])["format"] == "html"
    assert sites.publish(acct["id"], "# now md", "markdown", site_id=doc["id"])["format"] == "markdown"


def test_update_changes_only_what_is_given_and_all_or_nothing(acct):
    lid = acct["id"]
    confirm_list(lid)
    p, link = page(lid, "# A"), sites.shorten(lid, "https://example.com")
    assert sites.update(lid, p["id"], fmt="html")["format"] == "html"
    assert sites.get_site(lid, p["id"])["content"] == "# A"  # format alone keeps the content
    assert sites.update(lid, link["id"], title="Renamed")["title"] == "Renamed"
    assert sites.update(lid, p["id"], title="Page")["title"] == "Page"
    for bad in ({"content": "x"}, {"fmt": "html"}):
        with pytest.raises(ValidationError, match="has no content or format"):
            sites.update(lid, link["id"], **bad)
    before = sites.get_site(lid, p["id"])
    with pytest.raises(ValidationError, match="cannot be empty"):
        sites.update(lid, p["id"], status="unpublished", content="")
    with pytest.raises(ValidationError, match="status must be"):
        sites.update(lid, p["id"], title="Never", status="gone")
    assert sites.get_site(lid, p["id"]) == before


def test_another_lists_id_or_the_wrong_kind_is_not_found_and_changes_nothing(acct):
    mine, theirs = acct["id"], lists.create_list("UTC")["list_id"]
    confirm_list(mine)
    other = page(theirs, "# Secret")
    link = sites.shorten(mine, "https://example.com")
    for attempt in (
        lambda: sites.get_site(mine, other["id"]),
        lambda: sites.update(mine, other["id"], status="unpublished"),
        lambda: sites.publish(mine, "# Mine now", site_id=other["id"]),
        lambda: sites.delete_site(mine, other["id"]),
        lambda: sites.publish(mine, "# On a link", site_id=link["id"]),
    ):
        with pytest.raises(NotFoundError):
            attempt()
    assert sites.get_site(theirs, other["id"])["content"] == "# Secret"
    assert sites.get_site(theirs, other["id"])["status"] == "published"


# ── Serving on the Sites host ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_a_page_is_served_sandboxed_with_no_referrer_or_indexing(http, acct):
    p = page(acct["id"], "# Hi <script>x()</script>\n\n| a | b |\n|---|---|\n| 1 | 2 |", name="menu")
    res = await http.get(path_of(p), headers=ON_SITES)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/html")
    assert res.headers["content-security-policy"] == sites.SANDBOX
    assert "allow-same-origin" not in sites.SANDBOX
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-robots-tag"] == "noindex, nofollow"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "<h1>Hi <script>x()</script></h1>" in res.text and "<table>" in res.text
    assert "<title>Hi &lt;script&gt;x()&lt;/script&gt;</title>" in res.text
    head = await http.head(path_of(p), headers=ON_SITES)  # link checkers ask first
    assert head.status_code == 200 and head.headers["content-security-policy"] == sites.SANDBOX


@pytest.mark.anyio
async def test_html_is_wrapped_unless_it_is_a_whole_document(http, acct):
    confirm_list(acct["id"])  # This test needs multiple pages.
    fragment = page(acct["id"], "<p>Just this</p>", "html", title="Frag")
    whole = page(acct["id"], "<!DOCTYPE html><html><body>Mine</body></html>", "html")
    res = await http.get(path_of(fragment), headers=ON_SITES)
    assert "<main>\n<p>Just this</p>\n</main>" in res.text and "<title>Frag</title>" in res.text
    res = await http.get(path_of(whole), headers=ON_SITES)
    assert res.text == "<!DOCTYPE html><html><body>Mine</body></html>"
    assert res.headers["content-security-policy"] == sites.SANDBOX


@pytest.mark.anyio
async def test_a_short_link_redirects_without_a_referrer(http, acct):
    confirm_list(acct["id"])
    link = sites.shorten(acct["id"], "https://example.com/far", name="go")
    res = await http.get(path_of(link), headers=ON_SITES)
    assert res.status_code == 302 and res.headers["location"] == "https://example.com/far"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_misses_are_404_and_count_as_wrong_links(http, acct, monkeypatch):
    confirm_list(acct["id"])  # This test needs multiple pages.
    lid = acct["id"]
    named, plain = page(lid, name="menu"), page(lid)
    down = page(lid)
    sites.update(lid, down["id"], status="unpublished")
    misses = [
        f"/menu-{plain['code']}",
        f"/{named['code']}",
        f"/lunch-{named['code']}",
        path_of(down),
        "/ZZZZZZZZZZ",
        f"/{plain['code'].swapcase()}",
    ]
    for miss in misses:
        res = await http.get(miss, headers=ON_SITES)
        assert res.status_code == 404, miss
        assert "Nothing here" in res.text and res.headers["cache-control"] == "no-store"
    # Each miss spent one of the address's wrong-link budget; then 429.
    monkeypatch.setattr(ratelimit.bad_token_limiter, "allow", lambda key: False)
    res = await http.get("/ZZZZZZZZZZ", headers=ON_SITES)
    assert res.status_code == 429 and res.headers["retry-after"] == "600"
    # A real address is served whatever the budget says.
    assert (await http.get(path_of(plain), headers=ON_SITES)).status_code == 200


@pytest.mark.anyio
async def test_only_a_miss_spends_the_wrong_link_budget(http, acct, monkeypatch):
    p, spent = page(acct["id"]), []
    real = ratelimit.bad_token_limiter.allow
    monkeypatch.setattr(ratelimit.bad_token_limiter, "allow", lambda key: spent.append(key) or real(key))
    await http.get(path_of(p), headers=ON_SITES)
    assert spent == []
    await http.get("/ZZZZZZZZZZ", headers=ON_SITES)
    assert len(spent) == 1


@pytest.mark.anyio
async def test_a_disabled_or_removed_list_takes_its_pages_down(http, acct):
    p = page(acct["id"])
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), acct["id"]))
    assert (await http.get(path_of(p), headers=ON_SITES)).status_code == 404
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = NULL WHERE id = ?", (acct["id"],))
    assert (await http.get(path_of(p), headers=ON_SITES)).status_code == 200


@pytest.mark.anyio
async def test_a_put_away_list_keeps_its_pages_until_it_is_removed(http, acct, monkeypatch):
    # The idle lifecycle runs with open signup and mail (lifecycle.enabled).
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Todo GTD <signin@todo.example>")
    p = page(acct["id"])

    def idle(days):
        then = common.to_iso(common.utcnow() - datetime.timedelta(days=days))
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET created_at = ?, last_used_at = ? WHERE id = ?", (then, then, acct["id"]))

    idle(100)  # archived: its links still answer, and so do its pages
    assert (await http.get(path_of(p), headers=ON_SITES)).status_code == 200
    idle(181)  # removed: every link answers as unknown, pages too
    assert (await http.get(path_of(p), headers=ON_SITES)).status_code == 404
    confirm_list(acct["id"])  # a confirmed email keeps the list for good
    assert (await http.get(path_of(p), headers=ON_SITES)).status_code == 200


@pytest.mark.anyio
async def test_pages_answer_only_on_the_sites_host(http, acct):
    p = page(acct["id"], "# Only on Sites")
    res = await http.get(path_of(p))  # todo's host: the landing shell, not the page
    assert "Only on Sites" not in res.text and "content-security-policy" not in res.headers


# ── The short host (SITES_SHORT_URL) ──────────────────────────────────────────

SHORT = "https://ss.example"
ON_SHORT = {"Host": "ss.example"}


@pytest.fixture()
def short(acct, monkeypatch):
    """acct, on a server that hands addresses out on a short host."""
    monkeypatch.setenv("SITES_SHORT_URL", SHORT)
    return acct


def test_addresses_are_handed_out_on_the_short_host(short, monkeypatch):
    lid = short["id"]
    made = page(lid, name="menu")
    assert made["address"] == f"{SHORT}/menu-{made['code']}"
    assert sites.list_sites(lid)[0]["address"] == made["address"]
    confirm_list(lid)
    for own in (f"{SHORT}/x", "https://SS.example./x", f"{SITES}/x"):
        with pytest.raises(ValidationError, match="another short address"):
            sites.shorten(lid, own)
    monkeypatch.delenv("SITES_BASE_URL")  # no Sites, no short host either
    assert settings.sites_short_url() == ""


@pytest.mark.anyio
async def test_the_home_page_is_told_the_short_host(http, served, monkeypatch):
    assert (await http.get("/api/config", headers=ON_SITES)).json()["sites_short_host"] == ""
    monkeypatch.setenv("SITES_SHORT_URL", SHORT)
    assert (await http.get("/api/config", headers=ON_SITES)).json()["sites_short_host"] == "ss.example"


@pytest.mark.anyio
async def test_the_short_host_serves_pages_and_links_and_nothing_else(http, short):
    lid = short["id"]
    p = page(lid, "# Short and sweet", name="menu")
    path = p["address"].removeprefix(SHORT)
    res = await http.get(path, headers=ON_SHORT)
    assert res.status_code == 200 and "Short and sweet" in res.text
    assert res.headers["content-security-policy"] == sites.SANDBOX
    assert (await http.head(path, headers=ON_SHORT)).status_code == 200
    assert (await http.get(path, headers=ON_SITES)).status_code == 200  # the long address too
    confirm_list(lid)
    link = sites.shorten(lid, "https://example.com/far")
    res = await http.get(link["address"].removeprefix(SHORT), headers=ON_SHORT)
    assert res.status_code == 302 and res.headers["location"] == "https://example.com/far"
    miss = await http.get("/ZZZZZZZZZZ", headers=ON_SHORT)
    assert miss.status_code == 404 and "Nothing here" in miss.text
    # Any other GET goes to the same place on Sites' own address...
    for other in (
        "/",
        "/app",
        "/api/app/session",
        f"/link/{short['agent_token']}",
        "/signin/abc",
        f"{path}/more",
        "/icon.svg?v=1",
    ):
        res = await http.get(other, headers=ON_SHORT)
        assert res.status_code == 302 and res.headers["location"] == SITES + other, other
        assert "set-cookie" not in res.headers
    # ...and nothing else is answered: no account, no sign-in, no agent call, no cookie.
    before = db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0]
    for method, other in (
        ("POST", "/api/lists"),
        ("POST", path),
        ("DELETE", path),
        ("PUT", "/api/app/apps/sites"),
        ("POST", "/signin/abc"),
        ("POST", f"/link/{short['agent_token']}?cmd=PUBLISH"),
        ("POST", f"/mcp/{short['agent_token']}"),
    ):
        res = await http.request(method, other, headers=ON_SHORT, json={"content": "# x"})
        assert res.status_code == 404 and "set-cookie" not in res.headers, other
    assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == before
    assert len(sites.list_sites(lid)) == 2


@pytest.mark.anyio
async def test_a_locked_page_form_posts_to_the_short_host_itself(http, short):
    p = page(short["id"])
    unlock = p["address"].removeprefix(SHORT) + "/unlock"
    # Same origin by Origin alone (no Sec-Fetch-Site): the short host's own. A page
    # with no password is then a miss, so getting past the check means a 404.
    ok = await http.post(unlock, headers={**ON_SHORT, "Origin": SHORT}, data={"password": "x"})
    assert ok.status_code == 404
    for origin in (SITES, "https://evil.example"):
        res = await http.post(unlock, headers={**ON_SHORT, "Origin": origin}, data={"password": "x"})
        assert res.status_code == 403, origin


def test_page_addresses_never_reach_a_log():
    assert logscrub.scrub('GET "/menu-k7Qm2xPa9R" 200') == 'GET "/***" 200'
    assert logscrub.scrub("/k7Qm2xPa9R?x=1") == "/***?x=1"
    assert logscrub.scrub('"GET /menu-k7Qm2xPa9R/ HTTP/1.1" 307') == '"GET /***/ HTTP/1.1" 307'
    assert logscrub.scrub("see https://simplesites.app/menu-k7Qm2xPa9R") == "see https://simplesites.app/***"
    assert logscrub.scrub("/api/app/sites/1234567890") == "/api/app/sites/1234567890"


# ── The agent link ────────────────────────────────────────────────────────────

SITE_TOOLS = {
    "site_deck_guide",
    "site_sync",
    "site_publish",
    "link_create",
    "site_unpublish",
    "site_republish",
    "site_list",
    "site_get",
}


@pytest.mark.anyio
async def test_the_tools_and_commands_answer_only_while_sites_is_on(connect, http, served, todo_db):
    made = lists.create_list("UTC")
    url = f"http://testserver/link/{made['agent_token']}"
    async with connect(url) as c:
        assert not {t.name for t in await c.list_tools()} & SITE_TOOLS
        with pytest.raises(ToolError, match="Simple Sites is off"):
            await c.call_tool("site_list", {})
        with pytest.raises(ToolError, match="Simple Sites is off"):
            await c.call_tool("site_deck_guide", {})
    guide = (await http.get(f"/link/{made['agent_token']}")).json()
    assert "DECK_GUIDE" not in guide["commands"] and "deck" not in guide["howto"]
    res = await http.get(f"/link/{made['agent_token']}?cmd=DECK_GUIDE")
    assert res.status_code == 400 and res.json()["error"] == apps.off_message("sites")
    res = await http.post(f"/link/{made['agent_token']}?cmd=PUBLISH", json={"content": "# x"})
    assert res.status_code == 400 and "Simple Sites is off" in res.json()["error"]
    turn_on(made["list_id"], "sites")
    async with connect(url) as c:
        tools = {t.name: t for t in await c.list_tools()}
    assert SITE_TOOLS <= set(tools)
    for name in SITE_TOOLS:  # nothing an agent reaches deletes
        assert tools[name].annotations.destructive_hint is False, name
    guide = (await http.get(f"/link/{made['agent_token']}")).json()
    assert {"DECK_GUIDE", "SITES", "SITE", "PUBLISH", "SHORTEN", "UNPUBLISH", "REPUBLISH"} <= set(guide["commands"])
    assert guide["howto"]["deck"].startswith("DECK_GUIDE:")
    assert not [n for n in guide["commands"] if "DELETE" in n]
    assert guide["limits"]["pages_per_list"] == 1 and guide["reads"]["sites"].endswith("?cmd=SITES")


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_the_deck_guide_returns_both_files_with_read_only_hints(connect, http, acct, mode):
    directory = Path(__file__).resolve().parents[1] / "deck_guide"
    expected = {
        "guide": (directory / "guide.md").read_text(encoding="utf-8"),
        "template": (directory / "deck.html").read_text(encoding="utf-8"),
    }
    async with connect(f"http://testserver{acct['path']}", mode=mode) as c:
        tools = {t.name: t for t in await c.list_tools()}
        tool = tools["site_deck_guide"]
        assert tool.title
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is False
        assert tool.input_schema["properties"] == {}
        assert await call(c, "site_deck_guide") == expected
        prompt = "Making a presentation? Call site_deck_guide first."
        assert tools["site_publish"].description.startswith(prompt)
        assert prompt in c.instructions
    res = await http.get(f"{acct['path']}?cmd=DECK_GUIDE")
    assert res.status_code == 200 and res.json() == {"ok": True, **expected}
    assert res.headers["cache-control"] == "no-store"
    res = await http.post(f"{acct['path']}?cmd=DECK_GUIDE", json={})
    assert res.status_code == 405 and res.headers["allow"] == "GET, HEAD"
    assert "send it as GET" in res.json()["error"]
    assert sites.list_sites(acct["id"]) == []


def test_the_deck_assets_are_small_and_neutral():
    directory = Path(__file__).resolve().parents[1] / "deck_guide"
    assets = [(directory / name).read_bytes() for name in ("guide.md", "deck.html")]
    assert sum(map(len, assets)) <= 16_000
    for content in assets:
        text = content.decode("utf-8").lower()
        for forbidden in ("data:", "tncheesecake", "will", "/home/", "@font-face"):
            assert forbidden not in text
    assert assets[1].count(b"<section") == 6


@pytest.mark.anyio
async def test_an_agent_publishes_updates_and_takes_down_a_page_over_mcp(connect, http, acct):
    url = f"http://testserver{acct['path']}"
    async with connect(url) as c:
        made = (await call(c, "site_publish", content="# Report", name="q3"))["page"]
        assert made["address"].startswith(f"{SITES}/q3-") and made["source"] == "agent"
        again = (await call(c, "site_publish", content="# Report v2", id=made["id"]))["page"]
        assert again["address"] == made["address"]
        assert (await call(c, "site_get", id=made["id"]))["site"]["content"] == "# Report v2"
        assert (await call(c, "site_unpublish", id=made["id"]))["site"]["status"] == "unpublished"
        assert (await http.get(path_of(made), headers=ON_SITES)).status_code == 404
        assert (await call(c, "site_republish", id=made["id"]))["site"]["status"] == "published"
        assert [s["id"] for s in (await call(c, "site_list"))["sites"]] == [made["id"]]
        with pytest.raises(ToolError, match="need a confirmed email"):
            await c.call_tool("link_create", {"url": "https://example.com"})
    res = await http.get(path_of(made), headers=ON_SITES)
    assert res.status_code == 200 and "Report v2" in res.text


@pytest.mark.anyio
async def test_the_commands_publish_shorten_and_take_down(http, acct):
    base, lid = acct["path"], acct["id"]
    confirm_list(lid)
    made = (
        await http.post(f"{base}?cmd=PUBLISH", json={"content": "<p>Hi</p>", "format": "html", "title": "Hi"})
    ).json()["page"]
    res = await http.post(f"{base}?cmd=PUBLISH&id={made['id']}", json={"content": "<p>Bye</p>", "format": "html"})
    assert res.json()["page"]["address"] == made["address"]
    assert (await http.get(f"{base}?cmd=PUBLISH")).status_code == 405  # a write is POST only
    link = (await http.post(f"{base}?cmd=SHORTEN", json={"url": "https://example.com"})).json()["link"]
    assert link["kind"] == "link"
    assert (await http.post(f"{base}?cmd=UNPUBLISH&id={link['id']}")).json()["site"]["status"] == "unpublished"
    assert (await http.post(f"{base}?cmd=REPUBLISH&id={link['id']}")).json()["site"]["status"] == "published"
    listed = (await http.get(f"{base}?cmd=SITES&kind=page")).json()["sites"]
    assert [s["id"] for s in listed] == [made["id"]]
    assert (await http.get(f"{base}?cmd=SITE&id={made['id']}")).json()["site"]["content"] == "<p>Bye</p>"
    # An unpaired surrogate is valid JSON but not text: a 400, not a crash.
    for cmd, body in (
        ("PUBLISH", '{"content": "a\\ud800"}'),
        ("PUBLISH", '{"content": "# x", "title": "\\udfff"}'),
        ("SHORTEN", '{"url": "https://example.com/\\ud800"}'),
    ):
        res = await http.post(f"{base}?cmd={cmd}", content=body)
        assert res.status_code == 400 and "not valid text" in res.json()["error"], (cmd, body)
    res = await http.post(f"{base}?cmd=PUBLISH", json={"content": "x", "colour": "red"})
    assert res.status_code == 400 and "Unknown fields: colour" in res.json()["error"]
    assert (await http.get(f"{base}?cmd=SITE&id=999")).status_code == 404


@pytest.mark.anyio
async def test_one_list_cannot_reach_anothers_pages_through_any_surface(connect, http, acct, new_list):
    theirs = new_list()
    turn_on(theirs["list_id"], "sites")
    other = page(theirs["list_id"], "# Theirs")
    async with connect(f"http://testserver{acct['path']}") as c:
        for tool, args in (("site_get", {}), ("site_unpublish", {}), ("site_publish", {"content": "# Mine"})):
            with pytest.raises(ToolError, match="not found"):
                await c.call_tool(tool, {"id": other["id"], **args})
    for cmd, method in (("SITE", "GET"), ("UNPUBLISH", "POST"), ("PUBLISH", "POST")):
        res = await http.request(
            method,
            f"{acct['path']}?cmd={cmd}&id={other['id']}",
            json={"content": "# Mine"} if cmd == "PUBLISH" else None,
        )
        assert res.status_code == 404 and "Theirs" not in res.text, cmd
    after = sites.get_site(theirs["list_id"], other["id"])
    assert (after["content"], after["status"]) == ("# Theirs", "published")


@pytest.mark.anyio
async def test_a_whole_page_fits_through_both_transports_and_oversize_is_413(connect, http, acct):
    confirm_list(acct["id"])
    line = "<p>Lunch: soup, salad &amp; bread. “Quotes” and é.</p>\n"
    real = line * (1_950_000 // len(line.encode()))  # just under 2 MB of UTF-8
    res = await http.post(f"{acct['path']}?cmd=PUBLISH", json={"content": real, "format": "html"})
    assert res.status_code == 200, res.text[:200]
    async with connect(f"http://testserver{acct['path']}") as c:
        assert (await call(c, "site_publish", content=real, format="html"))["page"]["bytes"] > 1_900_000
    # A declared 4.5 MB command reaches the command (and its content rule), not the outer 413.
    big = json.dumps({"content": "y" * 4_500_000})
    res = await http.post(f"{acct['path']}?cmd=PUBLISH", content=big)
    assert res.status_code == 400 and "at most 2 MB" in res.json()["error"]
    # Escape-heavy content can pass 2 MB of content yet exceed the wire limits.
    escaped = json.dumps({"content": "\x01" * 5_000_000})  # 6 bytes on the wire each: 30 MB
    assert (await http.post(f"{acct['path']}?cmd=PUBLISH", content=escaped)).status_code == 413
    res = await http.post(
        acct["path"],
        content=escaped.replace('"content"', '"x"'),
        headers={**MCP_HEADERS, "Content-Type": "application/json"},
    )
    assert res.status_code == 413


# ── The browser API ───────────────────────────────────────────────────────────


def test_the_browser_api_round_trip_and_the_one_delete(served, new_list):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    confirm_list(lid)
    assert c.get("/api/app/sites").json() == {
        "sites": [],
        "caps": {
            "pages": 500,
            "links": 500,
            "page_bytes": 2_000_000,
            "site_bytes": 25_000_000,
            "storage": 500_000_000,
            "storage_used": 0,
            "files_per_site": 1000,
            "short_names": 0,
        },
        "folders": [],
    }
    p = c.post("/api/app/sites", json={"content": "# Hi", "name": "hi"}).json()
    assert p["address"].startswith(f"{SITES}/hi-") and p["source"] == "ui"
    link = c.post("/api/app/sites/links", json={"url": "https://example.com"}).json()
    assert [s["id"] for s in c.get("/api/app/sites").json()["sites"]] == [link["id"], p["id"]]
    assert c.get(f"/api/app/sites/{p['id']}").json()["content"] == "# Hi"
    res = c.put(f"/api/app/sites/{p['id']}", json={"status": "unpublished", "content": ""})
    assert res.status_code == 400 and c.get(f"/api/app/sites/{p['id']}").json()["status"] == "published"
    assert c.put(f"/api/app/sites/{link['id']}", json={"content": "x"}).status_code == 400
    assert c.put(f"/api/app/sites/{p['id']}", json={"status": "unpublished"}).json()["status"] == "unpublished"
    assert c.delete(f"/api/app/sites/{p['id']}").json() == {"ok": True}
    assert c.get(f"/api/app/sites/{p['id']}").status_code == 404
    assert c.delete(f"/api/app/sites/{p['id']}").status_code == 404
    # A body is refused by its declared size before it is read.
    res = c.post(
        "/api/app/sites",
        content=b"x" * 10,
        headers={"Content-Length": str(25 * 1024 * 1024), "Content-Type": "application/json"},
    )
    assert res.status_code == 413

    # And by what arrives, for a body sent without a declared length.
    def chunks():
        for _ in range(25 * 16):  # 25 MB in 64 KB pieces
            yield b"x" * 65536

    res = c.post("/api/app/sites", content=chunks(), headers={"Content-Type": "application/json"})
    assert "content-length" not in res.request.headers and res.status_code == 413


def test_every_write_refuses_a_page_in_another_origin(served, new_list):
    made = new_list()
    c, lid = made["client"], made["list_id"]
    confirm_list(lid)
    p = sites.publish(lid, "# Keep", "markdown")
    for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
        assert c.post("/api/app/sites", json={"content": "x"}, headers=headers).status_code == 403
        assert c.post("/api/app/sites/links", json={"url": "https://e.com"}, headers=headers).status_code == 403
        assert c.put(f"/api/app/sites/{p['id']}", json={"status": "unpublished"}, headers=headers).status_code == 403
        assert c.delete(f"/api/app/sites/{p['id']}", headers=headers).status_code == 403
        assert c.put("/api/app/apps/sites", json={"on": False}, headers=headers).status_code == 403
    # A sandboxed page sends Origin: null and no Sec-Fetch-Site from an old browser.
    c.headers.pop("Sec-Fetch-Site")
    assert c.post("/api/app/sites", json={"content": "x"}, headers={"Origin": "null"}).status_code == 403
    assert c.delete(f"/api/app/sites/{p['id']}", headers={"Origin": "null"}).status_code == 403
    assert sites.list_sites(lid)[0]["status"] == "published" and len(sites.list_sites(lid)) == 1


# ── Lifecycle: backup, restore, admin delete, cleanup ─────────────────────────


def test_restore_brings_pages_back_and_admin_delete_removes_them(acct, capsys):
    from backend import backup
    from scripts import admin, restore_list

    lid = acct["id"]
    kept = page(lid, "# In the snapshot")
    snapshot = backup.snapshot()
    sites.delete_site(lid, kept["id"])
    page(lid, "# Made later")
    restore_list.restore(snapshot, lid, db.db_path())
    assert [s["title"] for s in sites.list_sites(lid)] == ["In the snapshot"]
    assert sites.get_site(lid, kept["id"])["content"] == "# In the snapshot"
    assert admin.main(["delete", str(lid), f"--yes-delete-list-{lid}", "--no-snapshot"]) == 0
    assert db.get_db().execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 0


def test_cleanup_keeps_a_list_whose_only_content_is_a_page(acct):
    other = lists.create_list("UTC")["list_id"]
    page(acct["id"])
    old = common.to_iso(common.utcnow() - datetime.timedelta(days=40))
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = ?", (old,))
    assert cleanup.delete_unused_lists() == 1
    assert lists.get_list(acct["id"]) is not None and lists.get_list(other) is None
