"""Deferring: a todo with a future revisit date is hidden from the working lists
until that day in the list's own time zone, then shows as usual. Record views,
search, EXPORT and the weekly review's `upcoming` still return it."""

import pytest

from backend import service
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    anyio_backend,
    app,
    browser,
    call,
    connect,
    http,
    link,
    made,
)


def _titles(todos):
    return [t["title"] for t in todos]


@pytest.fixture()
def deferred(L, freeze):
    """Chicago's Aug 8, with one todo deferred to the 9th beside one that is not."""
    freeze("2026-08-08T18:00:00")
    project = service.create_project(L, "Lease")
    later = service.create_todo(
        L,
        "ask about the lease",
        status="next_action",
        revisit_on="2026-08-09",
        project_id=project["id"],
        star=True,
        due_date="2026-08-01",
    )
    service.create_todo(L, "plain", status="next_action")
    return later


def test_a_deferred_todo_is_off_the_working_lists_until_its_day(L, deferred, freeze):
    assert _titles(service.list_todos(L)) == ["plain"]
    assert _titles(service.list_todos(L, status="next_action")) == ["plain"]
    assert _titles(service.list_todos(L, starred=True)) == []
    # Starred and overdue, and still not on Today: "bring it back on X" means not before X.
    assert service.today_view(L) == []
    assert _titles(service.tickle_candidates(L)) == ["plain"]
    assert service.get_filters(L)["status_counts"]["next_action"] == 1

    freeze("2026-08-09T04:59:00")  # 23:59 on the 8th in Chicago
    assert _titles(service.list_todos(L)) == ["plain"]
    freeze("2026-08-09T05:00:00")  # midnight: its day
    assert _titles(service.list_todos(L)) == ["ask about the lease", "plain"]
    assert _titles(service.today_view(L)) == ["ask about the lease"]
    assert _titles(service.tickle_candidates(L)) == ["ask about the lease", "plain"]
    assert service.get_filters(L)["status_counts"]["next_action"] == 2


def test_search_and_record_views_still_reach_it(L, deferred):
    assert _titles(service.list_todos(L, search="lease")) == ["ask about the lease"]
    assert _titles(service.list_todos(L, include_deferred=True)) == ["ask about the lease", "plain"]
    assert service.get_todo(L, deferred["id"])["revisit_on"] == "2026-08-09"
    # It still covers its project: the open count and "no next action" both see it.
    assert service.list_projects(L)[0]["open_count"] == 1
    assert service.review_data(L)["projects_without_next_action"] == []


def test_the_weekly_review_lists_it_as_upcoming_and_nowhere_to_act_on(L, freeze):
    freeze("2026-07-01T18:00:00")
    for title, extra in (("put away", {"revisit_on": "2026-08-15"}), ("live", {})):
        service.create_todo(L, f"{title}, waiting", status="waiting_for", due_date="2026-07-02", **extra)
        service.create_todo(L, f"{title}, inbox", **extra)

    def review():
        data = service.review_data(L)
        return {
            name: (_titles(data[name]["todos"]), data[name]["count"])
            for name in ("inbox", "dated_today_or_overdue", "waiting_for", "stale", "upcoming")
        }

    freeze("2026-08-08T18:00:00")  # weeks untouched and overdue, but not back until the 15th
    assert review() == {
        "inbox": (["live, inbox"], 1),
        "dated_today_or_overdue": (["live, waiting"], 1),
        "waiting_for": (["live, waiting"], 1),
        "stale": (["live, waiting"], 1),
        "upcoming": (["put away, waiting", "put away, inbox"], 2),
    }
    freeze("2026-08-15T05:00:00")  # its day in Chicago
    both = ["put away, waiting", "live, waiting"]
    assert review() == {
        "inbox": (["put away, inbox", "live, inbox"], 2),
        "dated_today_or_overdue": (["put away, waiting", "put away, inbox", "live, waiting"], 3),
        "waiting_for": (both, 2),
        "stale": (both, 2),
        "upcoming": ([], 0),
    }


def test_finished_todos_and_cleared_dates_are_not_hidden(L, deferred):
    service.create_todo(L, "done", status="done", revisit_on="2026-09-01")
    service.create_todo(L, "archived", status="dropped", revisit_on="2026-09-01")
    assert _titles(service.list_todos(L, status="done")) == ["done"]
    assert _titles(service.list_todos(L, status="dropped")) == ["archived"]
    counts = service.get_filters(L)["status_counts"]
    assert (counts["done"], counts["dropped"]) == (1, 1)
    service.update_todo(L, deferred["id"], {"revisit_on": ""})
    assert _titles(service.list_todos(L, status="next_action")) == ["ask about the lease", "plain"]


def test_the_web_api_hides_it_unless_asked(new_list, freeze):
    freeze("2026-08-08T18:00:00")
    made = new_list()
    c, api = made["client"], made["api"]
    c.post(f"{api}/todos", json={"title": "later", "status": "someday_maybe", "revisit_on": "2026-08-09"})
    c.post(f"{api}/todos", json={"title": "now", "status": "someday_maybe"})

    def listed(**params):
        return _titles(c.get(f"{api}/todos", params=params).json()["todos"])

    assert listed(status="someday_maybe") == ["now"]
    assert listed(status="someday_maybe", include_deferred="true") == ["later", "now"]
    assert listed(search="later") == ["later"]
    assert c.get(f"{api}/filters").json()["status_counts"]["someday_maybe"] == 1
    assert c.get(f"{api}/today").json()["todos"] == []


@pytest.mark.anyio
async def test_agents_list_without_it_and_export_with_it(http, connect, made, freeze):
    freeze("2026-08-08T18:00:00")
    lid = made["list_id"]
    service.create_todo(lid, "later", status="next_action", revisit_on="2026-08-09")
    service.create_todo(lid, "now", status="next_action")
    path = f"/mcp/{made['agent_token']}"

    async def cmd(query):
        return _titles((await http.get(f"{path}?cmd={query}")).json()["todos"])

    assert await cmd("LIST") == ["now"]
    assert await cmd("LIST&search=later") == ["later"]
    assert await cmd("EXPORT") == ["later", "now"]  # a full copy never loses a row
    async with connect(link(made)) as c:
        assert _titles((await call(c, "todo_list"))["todos"]) == ["now"]
        assert _titles((await call(c, "todo_list", search="later"))["todos"]) == ["later"]
        assert [t["title"] for t in (await call(c, "todo_brain_tickle"))["candidates"]] == ["now"]
