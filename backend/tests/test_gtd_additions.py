"""The GTD additions against a real SQLite file: people, the someday revisit
date, areas of focus, richer projects and the brain tickle — service layer
first, then the same fields through HTTP."""

import pytest

from backend import common, lists, service
from backend.common import ValidationError


def _titles(todos):
    return [t["title"] for t in todos]


@pytest.fixture()
def other(todo_db) -> int:
    """A second list, for the isolation tests."""
    return lists.create_list("America/Chicago")["list_id"]


# ── People ────────────────────────────────────────────────────────────────────


class TestPeople:
    def test_validated_and_capped_like_tags(self, L):
        assert service.create_todo(L, "x")["people"] == []
        assert service.create_todo(L, "x", people=["  Ana ", "", "Bo"])["people"] == ["Ana", "Bo"]
        with pytest.raises(ValidationError, match="people must be a list of strings"):
            service.create_todo(L, "x", people="Ana")
        with pytest.raises(ValidationError, match="too many people"):
            service.create_todo(L, "x", people=[str(i) for i in range(51)])
        with pytest.raises(ValidationError, match="person too long"):
            service.create_todo(L, "x", people=["x" * 501])
        assert service.list_todos(L, status="inbox")[-1]["title"] == "x"
        assert len(service.list_todos(L)) == 2  # the refused ones left nothing behind

    def test_update_and_bulk_accept_people(self, L):
        a = service.create_todo(L, "a", people=["Ana"])
        b = service.create_todo(L, "b")
        assert service.update_todo(L, a["id"], {"people": ["Bo", "Cy"]})["people"] == ["Bo", "Cy"]
        service.bulk_update(L, [a["id"], b["id"]], {"people": ["Dee"]})
        assert [t["people"] for t in service.list_todos(L)] == [["Dee"], ["Dee"]]
        assert service.update_todo(L, a["id"], {"people": None})["people"] == []
        with pytest.raises(ValidationError, match="list of strings"):
            service.bulk_update(L, [a["id"]], {"people": "Dee"})

    def test_filter_by_person_is_an_exact_match(self, L):
        service.create_todo(L, "with ana", people=["Ana", "Bo"])
        service.create_todo(L, "with anabel", people=["Anabel"])
        service.create_todo(L, "tagged ana", tags=["Ana"])
        assert _titles(service.list_todos(L, person="Ana")) == ["with ana"]
        assert _titles(service.list_todos(L, person="Bo")) == ["with ana"]
        assert service.list_todos(L, person="ana") == []
        assert service.list_todos(L, person="Nobody") == []

    def test_search_matches_people(self, L):
        service.create_todo(L, "agenda", people=["Zoë Quinn"])
        service.create_todo(L, "other")
        assert _titles(service.list_todos(L, search="zoë q")) == ["agenda"]

    def test_filters_list_distinct_people_for_this_list_only(self, L, other):
        service.create_todo(L, "a", people=["bo", "Ana"])
        service.create_todo(L, "b", people=["Ana"], status="done")
        service.create_todo(other, "c", people=["Zed"])
        assert service.get_filters(L)["people"] == ["Ana", "bo"]
        assert service.get_filters(other)["people"] == ["Zed"]

    def test_a_repeat_carries_its_people(self, L):
        a = service.create_todo(L, "1:1", status="next_action", repeat="weekly", people=["Ana"])
        service.update_todo(L, a["id"], {"status": "done"})
        assert service.list_todos(L, status="next_action")[0]["people"] == ["Ana"]


# ── Someday revisit date ──────────────────────────────────────────────────────


class TestRevisit:
    def test_validated_like_a_due_date(self, L):
        assert service.create_todo(L, "x")["revisit_on"] is None
        a = service.create_todo(L, "x", revisit_on="2026-09-01")
        assert a["revisit_on"] == "2026-09-01"
        with pytest.raises(ValidationError, match="revisit_on must be YYYY-MM-DD"):
            service.create_todo(L, "x", revisit_on="next month")
        with pytest.raises(ValidationError, match="revisit_on is not a real calendar date"):
            service.update_todo(L, a["id"], {"revisit_on": "2026-02-30"})
        assert service.update_todo(L, a["id"], {"revisit_on": ""})["revisit_on"] is None
        service.bulk_update(L, [a["id"]], {"revisit_on": "2026-10-01"})
        assert service.get_todo(L, a["id"])["revisit_on"] == "2026-10-01"

    def test_surfaces_on_today_across_the_lists_timezone_boundary(self, todo_db, freeze):
        freeze("2026-08-08T01:00:00")  # Aug 7 8pm in Chicago, Aug 8 1pm in Auckland
        chicago = lists.create_list("America/Chicago")["list_id"]
        auckland = lists.create_list("Pacific/Auckland")["list_id"]
        for lst in (chicago, auckland):
            service.create_todo(lst, "back the 7th", status="someday_maybe", revisit_on="2026-08-07")
            service.create_todo(lst, "back the 8th", status="someday_maybe", revisit_on="2026-08-08")
            service.create_todo(lst, "back later", status="someday_maybe", revisit_on="2026-09-01")
            service.create_todo(lst, "no date", status="someday_maybe")
            service.create_todo(lst, "done", status="done", revisit_on="2026-08-01")
            service.create_todo(lst, "archived", status="dropped", revisit_on="2026-08-01")
        assert _titles(service.today_view(chicago)) == ["back the 7th"]
        assert _titles(service.today_view(auckland)) == ["back the 7th", "back the 8th"]
        # Chicago catches up when its own date turns.
        freeze("2026-08-08T05:00:00")
        assert _titles(service.today_view(chicago)) == ["back the 7th", "back the 8th"]

    def test_surfacing_changes_nothing(self, L, freeze):
        freeze("2026-08-08T18:00:00")
        a = service.create_todo(L, "learn the cello", status="someday_maybe", revisit_on="2026-08-01")
        assert _titles(service.today_view(L)) == ["learn the cello"]
        assert service.get_todo(L, a["id"]) == a  # still someday, same date, untouched
        assert _titles(service.list_todos(L, status="someday_maybe")) == ["learn the cello"]

    def test_a_repeat_does_not_carry_the_revisit_date(self, L):
        a = service.create_todo(L, "x", status="next_action", repeat="daily", revisit_on="2026-08-01")
        service.update_todo(L, a["id"], {"status": "done"})
        assert service.list_todos(L, status="next_action")[0]["revisit_on"] is None


# ── Areas of focus ────────────────────────────────────────────────────────────


class TestAreas:
    def test_create_list_update_archive(self, L):
        health = service.create_area(L, "  Health ", notes="body and mind")
        assert (health["name"], health["notes"], health["status"]) == ("Health", "body and mind", "active")
        assert health["created_at"].endswith("Z")
        service.create_area(L, "family")
        assert [a["name"] for a in service.list_areas(L)] == ["family", "Health"]

        renamed = service.update_area(L, health["id"], {"name": "Fitness", "notes": ""})
        assert (renamed["name"], renamed["notes"]) == ("Fitness", "")
        archived = service.update_area(L, health["id"], {"status": "dropped"})
        assert archived["status"] == "dropped"
        assert [a["name"] for a in service.list_areas(L, status="active")] == ["family"]
        assert [a["name"] for a in service.list_areas(L, status="dropped")] == ["Fitness"]
        assert len(service.list_areas(L)) == 2  # archived, not gone
        assert service.update_area(L, health["id"], {"status": "active"})["status"] == "active"

    def test_odd_id_terms_filter_to_nothing(self, L):
        # "²" is isdigit() but not an int; 30 nines overflow SQLite. Both were a 500.
        for term in ("²", "9" * 30):
            assert service.list_todos(L, area=term) == []
            assert service.list_projects(L, area=term) == []
            assert service.list_todos(L, project=term) == []

    def test_validation(self, L):
        a = service.create_area(L, "Work")
        b = service.create_area(L, "Home")
        with pytest.raises(ValidationError, match="name is required"):
            service.create_area(L, "   ")
        with pytest.raises(ValidationError, match='Area "work" already exists'):
            service.create_area(L, "work")
        with pytest.raises(ValidationError, match="already exists"):
            service.update_area(L, b["id"], {"name": "WORK"})
        assert service.update_area(L, a["id"], {"name": "work"})["name"] == "work"  # its own name
        with pytest.raises(ValidationError, match="name cannot be empty"):
            service.update_area(L, a["id"], {"name": " "})
        with pytest.raises(ValidationError, match="Invalid area status"):
            service.update_area(L, a["id"], {"status": "completed"})
        with pytest.raises(ValidationError, match="Invalid area status"):
            service.list_areas(L, status="completed")
        with pytest.raises(ValidationError, match="Unknown fields: list_id"):
            service.update_area(L, a["id"], {"list_id": 2})
        with pytest.raises(ValidationError, match="No fields"):
            service.update_area(L, a["id"], {})
        assert service.update_area(L, 9999, {"name": "x"}) is None

    def test_the_same_name_is_free_in_another_list(self, L, other):
        service.create_area(L, "Work")
        assert service.create_area(other, "Work")["name"] == "Work"

    def test_another_lists_area_cannot_be_attached(self, L, other):
        theirs = service.create_area(other, "Theirs")["id"]
        todo = service.create_todo(L, "mine")
        project = service.create_project(L, "P")
        with pytest.raises(ValidationError, match="Area id not found"):
            service.create_todo(L, "x", area_id=theirs)
        with pytest.raises(ValidationError, match="Area id not found"):
            service.update_todo(L, todo["id"], {"area_id": theirs})
        with pytest.raises(ValidationError, match="Area id not found"):
            service.bulk_update(L, [todo["id"]], {"area_id": theirs})
        with pytest.raises(ValidationError, match="Area id not found"):
            service.create_project(L, "Q", area_id=theirs)
        with pytest.raises(ValidationError, match="Area id not found"):
            service.update_project(L, project["id"], {"area_id": theirs})
        with pytest.raises(ValidationError, match="area_id must be an integer"):
            service.bulk_update(L, [todo["id"]], {"area_id": "work"})
        assert service.get_todo(L, todo["id"])["area_id"] is None
        assert service.get_project(L, project["id"])["area_id"] is None
        assert _titles(service.list_todos(L)) == ["mine"]
        assert [p["name"] for p in service.list_projects(L)] == ["P"]

    def test_one_list_cannot_see_or_change_anothers_areas(self, L, other):
        mine = service.create_area(L, "Mine")
        service.create_todo(L, "in mine", area_id=mine["id"])
        assert service.list_areas(other) == []
        assert service.get_area(other, mine["id"]) is None
        assert service.update_area(other, mine["id"], {"name": "Stolen"}) is None
        assert service.list_todos(other, area=mine["id"]) == []
        assert service.list_todos(other, area="Mine") == []
        assert service.list_projects(other, area=mine["id"]) == []
        assert service.get_filters(other)["areas"] == []
        assert service.get_area(L, mine["id"]) == mine

    def test_a_todo_shows_its_projects_area_unless_it_has_its_own(self, L):
        work = service.create_area(L, "Work")
        home = service.create_area(L, "Home")
        project = service.create_project(L, "Launch", area_id=work["id"])
        assert (project["area_id"], project["area_name"]) == (work["id"], "Work")

        inherited = service.create_todo(L, "inherits", project_id=project["id"])
        assert inherited["area_id"] is None  # its own area is still unset
        assert (inherited["effective_area_id"], inherited["area_name"]) == (work["id"], "Work")

        own = service.create_todo(L, "has its own", project_id=project["id"], area_id=home["id"])
        assert (own["area_id"], own["effective_area_id"], own["area_name"]) == (home["id"], home["id"], "Home")

        loose = service.create_todo(L, "loose", area_id=home["id"])
        none = service.create_todo(L, "none")
        assert (none["area_id"], none["effective_area_id"], none["area_name"]) == (None, None, None)

        assert _titles(service.list_todos(L, area=work["id"])) == ["inherits"]
        assert _titles(service.list_todos(L, area="home")) == ["has its own", "loose"]
        assert service.list_todos(L, area="No such area") == []

        # Moving the project moves what inherits from it, and nothing else.
        service.update_project(L, project["id"], {"area_id": home["id"]})
        assert service.get_todo(L, inherited["id"])["area_name"] == "Home"
        service.update_project(L, project["id"], {"area_id": None})
        assert service.get_todo(L, inherited["id"])["effective_area_id"] is None
        assert service.get_todo(L, own["id"])["area_name"] == "Home"
        # Clearing a todo's own area falls back to the project's.
        service.update_project(L, project["id"], {"area_id": work["id"]})
        assert service.update_todo(L, own["id"], {"area_id": None})["area_name"] == "Work"
        assert service.get_todo(L, loose["id"])["area_name"] == "Home"

    def test_projects_filter_by_area(self, L):
        work = service.create_area(L, "Work")
        service.create_project(L, "A", area_id=work["id"])
        service.create_project(L, "B", area_id=work["id"], status="someday")
        service.create_project(L, "C")
        assert [p["name"] for p in service.list_projects(L, area=work["id"])] == ["A", "B"]
        assert [p["name"] for p in service.list_projects(L, status="active", area="work")] == ["A"]
        assert service.list_projects(L, area="nope") == []

    def test_an_archived_area_keeps_its_items_but_leaves_the_pickers(self, L):
        work = service.create_area(L, "Work")
        todo = service.create_todo(L, "x", area_id=work["id"])
        assert service.get_filters(L)["areas"] == [{"id": work["id"], "name": "Work"}]
        service.update_area(L, work["id"], {"status": "dropped"})
        assert service.get_filters(L)["areas"] == []
        assert service.get_todo(L, todo["id"])["area_name"] == "Work"

    def test_a_repeat_carries_its_own_area(self, L):
        work = service.create_area(L, "Work")
        a = service.create_todo(L, "x", status="next_action", repeat="daily", area_id=work["id"])
        service.update_todo(L, a["id"], {"status": "done"})
        assert service.list_todos(L, status="next_action")[0]["area_id"] == work["id"]

    def test_cap_counts_archived_areas_and_is_per_list(self, L, other, monkeypatch):
        monkeypatch.setattr(common, "ANON_CAPS", (200, 20, 2))
        a = service.create_area(L, "a")
        service.create_area(L, "b")
        service.update_area(L, a["id"], {"status": "dropped"})  # archived still counts
        with pytest.raises(ValidationError, match="holds 2 areas"):
            service.create_area(L, "c")
        assert len(service.list_areas(L)) == 2
        assert service.update_area(L, a["id"], {"name": "still editable"})["name"] == "still editable"
        assert service.create_area(other, "c")["name"] == "c"


# ── Richer projects ───────────────────────────────────────────────────────────


class TestProjectPurposeAndOutcome:
    def test_create_and_update(self, L):
        plain = service.create_project(L, "Plain")
        assert (plain["purpose"], plain["outcome"]) == ("", "")
        p = service.create_project(L, "Launch", purpose="grow revenue", outcome="live by Q4")
        assert (p["purpose"], p["outcome"]) == ("grow revenue", "live by Q4")
        after = service.update_project(L, p["id"], {"outcome": "live by Q3"})
        assert (after["purpose"], after["outcome"]) == ("grow revenue", "live by Q3")
        assert service.update_project(L, p["id"], {"purpose": None})["purpose"] == ""

    def test_capped_like_notes(self, L):
        p = service.create_project(L, "P")
        with pytest.raises(ValidationError, match="purpose too long"):
            service.create_project(L, "Q", purpose="x" * 20_001)
        with pytest.raises(ValidationError, match="outcome too long"):
            service.update_project(L, p["id"], {"outcome": "x" * 20_001})
        assert [x["name"] for x in service.list_projects(L)] == ["P"]


# ── Brain tickle ──────────────────────────────────────────────────────────────


class TestBrainTickle:
    def test_constants(self):
        assert (common.TICKLE_REST_DAYS, common.TICKLE_STALE_COUNT) == (5, 3)

    def test_candidates_are_open_next_actions(self, L):
        for status in common.TODO_STATUSES:
            service.create_todo(L, status, status=status)
        candidates = service.tickle_candidates(L)
        assert _titles(candidates) == ["next_action"]
        assert candidates[0]["stale"] is False
        assert (candidates[0]["tickle_count"], candidates[0]["last_tickled_at"]) == (0, None)

    def test_candidates_carry_what_the_tickle_needs(self, L):
        work = service.create_area(L, "Work")
        service.create_todo(
            L,
            "call",
            status="next_action",
            context="@calls",
            people=["Ana"],
            project="Launch",
            area_id=work["id"],
            due_date="2026-09-01",
            star=True,
        )
        c = service.tickle_candidates(L)[0]
        assert (c["context"], c["people"], c["project_name"], c["area_name"], c["due_date"], c["star"]) == (
            "@calls",
            ["Ana"],
            "Launch",
            "Work",
            "2026-09-01",
            True,
        )
        assert c["created_at"].endswith("Z")

    def test_starred_then_soonest_due_then_oldest(self, L):
        service.create_todo(L, "old", status="next_action")
        service.create_todo(L, "due later", status="next_action", due_date="2026-09-09")
        service.create_todo(L, "due sooner", status="next_action", due_date="2026-09-01")
        service.create_todo(L, "starred", status="next_action", star=True)
        assert _titles(service.tickle_candidates(L)) == ["starred", "due sooner", "due later", "old"]
        assert _titles(service.tickle_candidates(L, limit=2)) == ["starred", "due sooner"]

    def test_record_stamps_and_counts_without_editing(self, L, freeze):
        freeze("2026-08-01T12:00:00")
        a = service.create_todo(L, "a", status="next_action")
        freeze("2026-08-02T15:30:00")
        after = service.record_tickle(L, a["id"])
        assert after["last_tickled_at"] == "2026-08-02T15:30:00.000Z"
        assert after["tickle_count"] == 1
        assert after["updated_at"] == a["updated_at"]  # a tickle is not an edit
        assert after["status"] == "next_action"
        assert service.record_tickle(L, a["id"])["tickle_count"] == 2
        assert service.record_tickle(L, 9999) is None

    def test_a_tickled_todo_rests_five_of_the_lists_days(self, L, freeze):
        a = service.create_todo(L, "a", status="next_action")
        service.create_todo(L, "b", status="next_action")
        # Aug 1, 10pm in Chicago — already Aug 2 in UTC.
        freeze("2026-08-02T03:00:00")
        service.record_tickle(L, a["id"])
        assert _titles(service.tickle_candidates(L)) == ["b"]
        # Aug 5, 11:59pm in Chicago: the fifth local day, still resting.
        freeze("2026-08-06T04:59:00")
        assert _titles(service.tickle_candidates(L)) == ["b"]
        # Aug 6, midnight in Chicago: back. (Counting UTC days would say Aug 7.)
        freeze("2026-08-06T05:00:00")
        assert _titles(service.tickle_candidates(L)) == ["a", "b"]

    def test_the_rest_follows_each_lists_own_zone(self, todo_db, freeze):
        chicago = lists.create_list("America/Chicago")["list_id"]
        auckland = lists.create_list("Pacific/Auckland")["list_id"]
        freeze("2026-08-02T03:00:00")  # Aug 1 in Chicago, Aug 2 in Auckland
        for lst in (chicago, auckland):
            service.record_tickle(lst, service.create_todo(lst, "a", status="next_action")["id"])
        freeze("2026-08-06T13:00:00")  # Aug 6 in Chicago (back), Aug 7 1am in Auckland (back)
        assert _titles(service.tickle_candidates(chicago)) == ["a"]
        assert _titles(service.tickle_candidates(auckland)) == ["a"]
        freeze("2026-08-06T11:00:00")  # Aug 6 6am in Chicago (back), Aug 6 11pm in Auckland (resting)
        assert _titles(service.tickle_candidates(chicago)) == ["a"]
        assert service.tickle_candidates(auckland) == []

    def test_stale_after_three_tickles_and_nothing_resets_it(self, L, freeze):
        a = service.create_todo(L, "a", status="next_action")
        for day in ("01", "08", "15"):
            freeze(f"2026-08-{day}T12:00:00")
            assert service.tickle_candidates(L)[0]["stale"] is False
            service.record_tickle(L, a["id"])
        freeze("2026-08-22T12:00:00")
        assert service.tickle_candidates(L)[0]["stale"] is True
        # Re-statusing resets nothing.
        service.update_todo(L, a["id"], {"status": "someday_maybe"})
        assert service.tickle_candidates(L) == []
        service.update_todo(L, a["id"], {"status": "next_action"})
        back = service.tickle_candidates(L)[0]
        assert (back["stale"], back["tickle_count"]) == (True, 3)

    def test_a_repeats_next_occurrence_starts_fresh(self, L):
        a = service.create_todo(L, "a", status="next_action", repeat="daily")
        service.record_tickle(L, a["id"])
        service.update_todo(L, a["id"], {"status": "done"})
        nxt = service.tickle_candidates(L)[0]
        assert nxt["id"] != a["id"]
        assert (nxt["tickle_count"], nxt["last_tickled_at"]) == (0, None)

    def test_tickle_columns_are_not_writable_through_update(self, L):
        a = service.create_todo(L, "a", status="next_action")
        with pytest.raises(ValidationError, match="Unknown fields"):
            service.update_todo(L, a["id"], {"tickle_count": 0})
        with pytest.raises(ValidationError, match="Unknown fields"):
            service.bulk_update(L, [a["id"]], {"last_tickled_at": None})

    def test_one_list_cannot_tickle_or_see_anothers_todos(self, L, other):
        mine = service.create_todo(L, "mine", status="next_action")
        assert service.tickle_candidates(other) == []
        assert service.record_tickle(other, mine["id"]) is None
        assert service.get_todo(L, mine["id"])["tickle_count"] == 0
        assert _titles(service.tickle_candidates(L)) == ["mine"]


# ── The same fields through HTTP ──────────────────────────────────────────────


def test_people_and_revisit_over_http(new_list, freeze):
    freeze("2026-08-08T18:00:00")
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(
        f"{api}/todos",
        json={
            "title": "ask about the lease",
            "status": "someday_maybe",
            "people": ["Ana", " Bo "],
            "revisit_on": "2026-08-08",
        },
    ).json()
    assert (todo["people"], todo["revisit_on"]) == (["Ana", "Bo"], "2026-08-08")
    c.post(f"{api}/todos", json={"title": "other", "people": ["Cy"]})

    assert [t["id"] for t in c.get(f"{api}/todos", params={"person": "Ana"}).json()["todos"]] == [todo["id"]]
    assert c.get(f"{api}/filters").json()["people"] == ["Ana", "Bo", "Cy"]
    assert [t["id"] for t in c.get(f"{api}/today").json()["todos"]] == [todo["id"]]

    url = f"{api}/todos/{todo['id']}"
    # Omitted fields are untouched; an explicit null clears.
    after = c.put(url, json={"title": "renamed"}).json()
    assert (after["people"], after["revisit_on"]) == (["Ana", "Bo"], "2026-08-08")
    after = c.put(url, json={"people": None, "revisit_on": None}).json()
    assert (after["people"], after["revisit_on"]) == ([], None)
    assert c.get(f"{api}/today").json()["todos"] == []

    res = c.put(url, json={"revisit_on": "soon"})
    assert res.status_code == 400 and "revisit_on must be YYYY-MM-DD" in res.json()["detail"]
    assert c.put(url, json={"people": "Ana"}).status_code == 422
    res = c.post(f"{api}/todos/bulk", json={"ids": [todo["id"]], "fields": {"people": ["Dee"]}})
    assert res.json() == {"updated": [todo["id"]], "not_found": []}
    assert c.get(url).json()["people"] == ["Dee"]


def test_areas_over_http(new_list, monkeypatch):
    a, b = new_list(), new_list()
    ca, cb, api = a["client"], b["client"], a["api"]
    res = ca.post(f"{api}/areas", json={"name": "Work", "notes": "the day job"})
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    work = res.json()
    assert (work["name"], work["notes"], work["status"]) == ("Work", "the day job", "active")
    assert ca.post(f"{api}/areas", json={"name": "work"}).status_code == 400  # duplicate
    assert ca.post(f"{api}/areas", json={"name": " "}).status_code == 400
    assert ca.get(f"{api}/areas").json() == {"areas": [work]}
    assert ca.get(f"{api}/areas", params={"status": "bogus"}).status_code == 400

    # Attach a project and a loose todo; a todo in the project inherits.
    project = ca.post(f"{api}/projects", json={"name": "Launch", "area_id": work["id"]}).json()
    assert (project["area_id"], project["area_name"]) == (work["id"], "Work")
    inherited = ca.post(f"{api}/todos", json={"title": "in project", "project_id": project["id"]}).json()
    assert (inherited["area_id"], inherited["effective_area_id"], inherited["area_name"]) == (None, work["id"], "Work")
    loose = ca.post(f"{api}/todos", json={"title": "loose", "area_id": work["id"]}).json()
    assert loose["area_id"] == work["id"]
    ca.post(f"{api}/todos", json={"title": "elsewhere"})
    in_area = ca.get(f"{api}/todos", params={"area": work["id"]}).json()["todos"]
    assert [t["title"] for t in in_area] == ["in project", "loose"]
    assert [p["name"] for p in ca.get(f"{api}/projects", params={"area": "Work"}).json()["projects"]] == ["Launch"]
    assert ca.get(f"{api}/filters").json()["areas"] == [{"id": work["id"], "name": "Work"}]
    assert ca.put(f"{api}/todos/{loose['id']}", json={"area_id": None}).json()["area_id"] is None
    assert ca.put(f"{api}/projects/{project['id']}", json={"area_id": None}).json()["area_id"] is None

    # Rename, archive, restore — never delete.
    url = f"{api}/areas/{work['id']}"
    assert ca.put(url, json={"name": "Career"}).json()["name"] == "Career"
    assert ca.put(url, json={"status": "dropped"}).json()["status"] == "dropped"
    assert ca.get(f"{api}/areas", params={"status": "active"}).json()["areas"] == []
    assert ca.put(url, json={"status": "active"}).json()["status"] == "active"
    assert ca.put(url, json={"status": "completed"}).status_code == 400
    assert ca.put(url, json={}).status_code == 400
    assert ca.put(f"{api}/areas/99999", json={"name": "x"}).status_code == 404
    assert ca.delete(url).status_code == 405
    assert ca.get(f"{api}/areas").json()["areas"][0]["name"] == "Career"

    # The other list can neither see, change nor attach it.
    assert cb.get(f"{b['api']}/areas").json()["areas"] == []
    assert cb.put(f"{b['api']}/areas/{work['id']}", json={"name": "x"}).status_code == 404
    assert cb.post(f"{b['api']}/todos", json={"title": "x", "area_id": work["id"]}).status_code == 400
    assert cb.post(f"{b['api']}/projects", json={"name": "x", "area_id": work["id"]}).status_code == 400
    theirs = cb.post(f"{b['api']}/todos", json={"title": "theirs"}).json()
    res = cb.post(f"{b['api']}/todos/bulk", json={"ids": [theirs["id"]], "fields": {"area_id": work["id"]}})
    assert res.status_code == 400
    assert cb.get(f"{b['api']}/projects").json()["projects"] == []
    assert ca.get(f"{api}/areas").json()["areas"][0]["name"] == "Career"

    # The cap refuses new areas and leaves the existing one alone.
    monkeypatch.setattr(common, "ANON_CAPS", (200, 20, 1))
    res = ca.post(f"{api}/areas", json={"name": "Home"})
    assert res.status_code == 400 and "holds 1 areas" in res.json()["detail"]
    assert ca.put(url, json={"notes": "still editable"}).status_code == 200


def test_no_session_is_401_on_the_area_routes(client):
    assert client.get("/api/app/areas").status_code == 401
    assert client.post("/api/app/areas", json={"name": "x"}).status_code == 401
    assert client.put("/api/app/areas/1", json={"name": "x"}).status_code == 401


def test_project_purpose_and_outcome_over_http(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    project = c.post(
        f"{api}/projects",
        json={
            "name": "Launch",
            "purpose": "grow revenue",
            "outcome": "live by Q4",
        },
    ).json()
    assert (project["purpose"], project["outcome"]) == ("grow revenue", "live by Q4")
    assert c.post(f"{api}/projects", json={"name": "Plain"}).json()["purpose"] == ""
    url = f"{api}/projects/{project['id']}"

    # Omitted is untouched; an explicit null or empty clears.
    after = c.put(url, json={"outcome": "live by Q3"}).json()
    assert (after["purpose"], after["outcome"], after["name"]) == ("grow revenue", "live by Q3", "Launch")
    assert c.put(url, json={"purpose": None}).json()["purpose"] == ""
    assert c.put(url, json={"outcome": ""}).json()["outcome"] == ""
    listed = c.get(f"{api}/projects").json()["projects"]
    assert {p["name"]: p["outcome"] for p in listed} == {"Launch": "", "Plain": ""}
    assert c.put(url, json={"purpose": "x" * 20_001}).status_code == 422


def test_the_brain_tickle_has_no_http_route(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    todo = c.post(f"{api}/todos", json={"title": "x", "status": "next_action"}).json()
    for path in ("tickle", "brain-tickle", f"todos/{todo['id']}/tickle"):
        assert c.get(f"{api}/{path}").status_code in (404, 405), path
        assert c.post(f"{api}/{path}").status_code in (404, 405), path
    # …and the bookkeeping cannot be written through the todo routes.
    assert c.put(f"{api}/todos/{todo['id']}", json={"tickle_count": 5}).status_code == 400
    assert c.get(f"{api}/todos/{todo['id']}").json()["tickle_count"] == 0
