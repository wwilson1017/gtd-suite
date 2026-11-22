"""Plan cases moved from test_sites.py."""

import json
import pytest
from backend import common, db, sites
from backend.common import ValidationError
from backend.tests.conftest import confirm_list as confirm_list, turn_on as turn_on
from backend.tests.test_mcp import (
    MCP_HEADERS as MCP_HEADERS,
    anyio_backend as anyio_backend,
    app as app,
    call as call,
    connect as connect,
    http as http,
)
from backend.tests.test_sites import SITES as SITES, acct as acct, page as page, served as served


@pytest.mark.anyio
async def test_max_holds_a_ten_megabyte_page_by_command_and_from_the_browser(http, acct, served, new_list):
    confirm_list(acct["id"])  # This test needs multiple pages.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '9999-12-31T00:00:00.000Z', comp_plan = 'max' WHERE id = ?",
            (acct["id"],),
        )
    assert sites.caps(acct["id"])["page_bytes"] == common.SITE_BIG_PAGE_BYTES == 10_000_000
    page(acct["id"], "x" * common.SITE_BIG_PAGE_BYTES)
    with pytest.raises(ValidationError, match="at most 10 MB"):
        page(acct["id"], "x" * (common.SITE_BIG_PAGE_BYTES + 1))
    slide = "<section><p>Slide</p></section>\n"
    deck = slide * (9_900_000 // len(slide))  # a 9.9 MB deck
    res = await http.post(f"{acct['path']}?cmd=PUBLISH", json={"content": deck, "format": "html"})
    assert res.status_code == 200 and res.json()["page"]["bytes"] > 9_800_000, res.text[:200]
    guide = (await http.get(acct["path"])).json()
    assert '"page_bytes": 10000000' in json.dumps(guide)
    # The free plan keeps 2 MB, from the browser too.
    made = new_list()
    confirm_list(made["list_id"])
    res = made["client"].post("/api/app/sites", json={"content": "x" * 3_000_000})
    assert res.status_code == 400 and "at most 2 MB" in res.text


def test_a_plan_that_ends_mid_publish_is_checked_again_in_the_write(acct, monkeypatch):
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '9999-12-31T00:00:00.000Z', comp_plan = 'max' WHERE id = ?",
            (acct["id"],),
        )
    title = sites._title

    def grant_ends(*a, **kw):  # between the first check and the write
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET pro_comp_until = NULL WHERE id = ?", (acct["id"],))
        return title(*a, **kw)

    monkeypatch.setattr(sites, "_title", grant_ends)
    with pytest.raises(ValidationError, match="at most 2 MB"):
        page(acct["id"], "x" * 3_000_000)
    assert sites.list_sites(acct["id"]) == []


@pytest.mark.anyio
async def test_short_names_through_mcp_commands_and_browser(connect, http, acct, new_list):
    lid = acct["id"]
    confirm_list(lid)
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET pro_comp_until = '9999-12-31T00:00:00.000Z' WHERE id = ?", (lid,))
    async with connect(f"http://testserver{acct['path']}") as c:
        made = (await call(c, "link_create", url="https://example.com", short_name="terminal"))["link"]
    assert made["short_name"] == "terminal" and made["address"] == f"{SITES}/terminal"
    response = await http.post(
        f"{acct['path']}?cmd=SHORTEN", json={"url": "https://example.com", "short_name": "command"}
    )
    assert response.status_code == 200 and response.json()["link"]["short_name"] == "command"
    guide = (await http.get(acct["path"])).json()
    assert guide["limits"]["short_names"] == 10
    assert guide["limits"]["site_bytes"] == 250_000_000
    browser = new_list()
    confirm_list(browser["list_id"])
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET pro_comp_until = '9999-12-31T00:00:00.000Z' WHERE id = ?", (browser["list_id"],))
    response = browser["client"].post(
        "/api/app/sites/links", json={"url": "https://example.com", "short_name": "browser"}
    )
    assert response.status_code == 200 and response.json()["address"] == f"{SITES}/browser"
