"""Service layer against a real SQLite file: CRUD, filters, projects, capture,
recurrence, caps and the write-transaction contract."""

import datetime
import threading

import pytest

from backend import common, db, lists, service
from backend.common import ValidationError


def _titles(todos):
    return [t["title"] for t in todos]


class TestCreateTodo:
    def test_defaults(self, L):
        todo = service.create_todo(L, "Call the bank")
        assert todo["title"] == "Call the bank"
        assert todo["status"] == "inbox"
        assert todo["source"] == "agent"
        assert todo["source_client"] is None
        assert todo["tags"] == []
        assert todo["star"] is False
        assert todo["auto_star_on_due"] is False
        assert todo["project_id"] is None
        assert todo["project_name"] is None
        assert todo["due_date"] is None
        assert todo["completed_at"] is None
        assert todo["created_at"].endswith("Z") and todo["updated_at"].endswith("Z")

    def test_title_required(self, L):
        with pytest.raises(ValidationError, match="title is required"):
            service.create_todo(L, "   ")

    def test_title_too_long(self, L):
        with pytest.raises(ValidationError, match="title too long"):
            service.create_todo(L, "x" * 20_001)

    def test_invalid_status_rejected(self, L):
        with pytest.raises(ValidationError, match="Invalid status"):
            service.create_todo(L, "x", status="doing")

    def test_invalid_due_date_rejected(self, L):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            service.create_todo(L, "x", due_date="tomorrow")

    def test_invalid_source_rejected(self, L):
        with pytest.raises(ValidationError, match="Invalid source"):
            service.create_todo(L, "x", source="carrier_pigeon")

    def test_tags_normalized(self, L):
        todo = service.create_todo(L, "x", tags=["  home ", "", "energy:low"])
        assert todo["tags"] == ["home", "energy:low"]

    def test_tags_must_be_string_list(self, L):
        with pytest.raises(ValidationError, match="list of strings"):
            service.create_todo(L, "x", tags="home")

    def test_project_auto_created_by_name(self, L):
        todo = service.create_todo(L, "x", project="Renovation")
        assert todo["project_name"] == "Renovation"
        projects = service.list_projects(L)
        assert [p["name"] for p in projects] == ["Renovation"]
        assert projects[0]["status"] == "active"

    def test_project_name_case_insensitive_dedupe(self, L):
        a = service.create_todo(L, "x", project="Renovation")
        b = service.create_todo(L, "y", project="renovation")
        assert a["project_id"] == b["project_id"]
        assert len(service.list_projects(L)) == 1

    def test_created_done_gets_completed_at(self, L):
        assert service.create_todo(L, "x", status="done")["completed_at"] is not None

    def test_unknown_project_id_rejected(self, L):
        with pytest.raises(ValidationError, match="Project id not found"):
            service.create_todo(L, "x", project_id=999)

    def test_failed_create_leaves_no_auto_created_project(self, L):
        # The project insert and the todo insert are one transaction.
        with pytest.raises(Exception):
            service.create_todo(L, "x", project="Half made", source_client=BrokenStr())
        assert service.list_projects(L) == []


class BrokenStr:
    def __str__(self):
        raise RuntimeError("boom")


class TestUpdateTodo:
    def test_done_sets_completed_at_and_undone_clears(self, L):
        todo = service.create_todo(L, "x")
        done = service.update_todo(L, todo["id"], {"status": "done"})
        assert done["completed_at"] is not None
        back = service.update_todo(L, todo["id"], {"status": "next_action"})
        assert back["completed_at"] is None
        assert back["status"] == "next_action"

    def test_unknown_field_rejected(self, L):
        todo = service.create_todo(L, "x")
        with pytest.raises(ValidationError, match="Unknown fields: priority"):
            service.update_todo(L, todo["id"], {"priority": "high"})

    def test_empty_update_rejected(self, L):
        todo = service.create_todo(L, "x")
        with pytest.raises(ValidationError, match="No fields to update"):
            service.update_todo(L, todo["id"], {})

    def test_missing_todo_returns_none(self, L):
        assert service.update_todo(L, 12345, {"title": "y"}) is None

    def test_clear_project_with_empty_name(self, L):
        todo = service.create_todo(L, "x", project="P1")
        assert service.update_todo(L, todo["id"], {"project": ""})["project_id"] is None

    def test_update_bumps_updated_at(self, L):
        todo = service.create_todo(L, "x")
        with db.transaction() as conn:
            conn.execute("UPDATE todos SET updated_at = '2020-01-01T00:00:00.000Z' WHERE id = ?", (todo["id"],))
        updated = service.update_todo(L, todo["id"], {"notes": "hi"})
        assert updated["updated_at"] > "2020-01-01T00:00:00.000Z"

    def test_provenance_is_not_updatable(self, L):
        todo = service.create_todo(L, "x", source="ui")
        for field in ("source", "source_client", "list_id"):
            with pytest.raises(ValidationError, match="Unknown fields"):
                service.update_todo(L, todo["id"], {field: "agent"})
        service.update_todo(L, todo["id"], {"title": "edited"})
        assert service.get_todo(L, todo["id"])["source"] == "ui"

    def test_auto_star_on_due_is_updatable(self, L):
        todo = service.create_todo(L, "x")
        assert service.update_todo(L, todo["id"], {"auto_star_on_due": True})["auto_star_on_due"] is True

    @pytest.mark.parametrize(
        "fields,message",
        [
            ({"title": ""}, "title cannot be empty"),
            ({"title": 123}, "title must be a string"),
            ({"due_date": "2026-13-40"}, "not a real calendar date"),
            ({"repeat": "hourly"}, "Invalid repeat"),
            ({"status": "bogus"}, "Invalid status"),
            ({"tags": "home"}, "list of strings"),
            ({"project_id": "seven"}, "project_id must be an integer"),
            ({"context": "x" * 501}, "context too long"),
        ],
    )
    def test_malformed_fields_rejected(self, L, fields, message):
        todo = service.create_todo(L, "x")
        with pytest.raises(ValidationError, match=message):
            service.update_todo(L, todo["id"], fields)
        assert service.get_todo(L, todo["id"])["updated_at"] == todo["updated_at"]


class TestBulkUpdate:
    def test_reports_updated_and_not_found(self, L):
        a = service.create_todo(L, "a")
        b = service.create_todo(L, "b")
        result = service.bulk_update(L, [b["id"], a["id"], 999], {"status": "next_action"})
        assert result["updated"] == [a["id"], b["id"]]
        assert result["not_found"] == [999]
        assert service.get_todo(L, a["id"])["status"] == "next_action"

    def test_done_transition_only_stamps_fresh_completions(self, L):
        a = service.create_todo(L, "a")
        b = service.create_todo(L, "b", status="done")
        first_completed = service.get_todo(L, b["id"])["completed_at"]
        result = service.bulk_update(L, [a["id"], b["id"]], {"status": "done"})
        assert result["updated"] == [a["id"], b["id"]]
        assert service.get_todo(L, a["id"])["completed_at"] is not None
        assert service.get_todo(L, b["id"])["completed_at"] == first_completed

    def test_validation_error_rejects_the_whole_batch(self, L):
        a = service.create_todo(L, "a")
        with pytest.raises(ValidationError):
            service.bulk_update(L, [a["id"]], {"status": "bogus"})
        assert service.get_todo(L, a["id"])["status"] == "inbox"

    def test_failure_on_a_later_row_rolls_back_the_earlier_ones(self, L, monkeypatch):
        a = service.create_todo(L, "a", status="next_action", repeat="daily")
        b = service.create_todo(L, "b", status="next_action", repeat="daily")
        monkeypatch.setattr(common, "ANON_CAPS", (3, 20, 10))  # room for one spawn, not two
        with pytest.raises(ValidationError, match="holds 3 todos"):
            service.bulk_update(L, [a["id"], b["id"]], {"status": "done"})
        assert service.get_todo(L, a["id"])["status"] == "next_action"
        assert service.get_todo(L, b["id"])["status"] == "next_action"
        assert len(service.list_todos(L)) == 2

    def test_caps_ids_and_rejects_non_integers(self, L):
        with pytest.raises(ValidationError, match="too many ids"):
            service.bulk_update(L, list(range(501)), {"status": "done"})
        with pytest.raises(ValidationError, match="ids must be integers"):
            service.bulk_update(L, [1, "seven"], {"status": "done"})
        with pytest.raises(ValidationError, match="ids is required"):
            service.bulk_update(L, [], {"status": "done"})

    def test_non_string_title_rejected_not_crash(self, L):
        a = service.create_todo(L, "a")
        with pytest.raises(ValidationError, match="title must be a string"):
            service.bulk_update(L, [a["id"]], {"title": 123})

    def test_bulk_complete_spawns_each_repeating_todo(self, L):
        a = service.create_todo(L, "water", status="next_action", repeat="daily")
        b = service.create_todo(L, "stretch", status="next_action", repeat="weekly")
        c = service.create_todo(L, "one-off", status="next_action")
        service.bulk_update(L, [a["id"], b["id"], c["id"]], {"status": "done"})
        assert sorted(_titles(service.list_todos(L, status="next_action"))) == ["stretch", "water"]


class TestListTodos:
    def test_filter_by_status(self, L):
        service.create_todo(L, "a")
        service.create_todo(L, "b", status="next_action")
        assert _titles(service.list_todos(L, status="next_action")) == ["b"]

    def test_filter_by_project_name_and_id(self, L):
        t = service.create_todo(L, "a", project="Ops")
        service.create_todo(L, "b")
        assert _titles(service.list_todos(L, project="ops")) == ["a"]
        assert _titles(service.list_todos(L, project=t["project_id"])) == ["a"]
        assert service.list_todos(L, project="NoSuch") == []

    def test_filter_by_context_case_insensitive(self, L):
        service.create_todo(L, "a", context="@Home")
        service.create_todo(L, "b", context="@office")
        assert _titles(service.list_todos(L, context="@home")) == ["a"]

    def test_filter_by_tag_exact_match(self, L):
        service.create_todo(L, "a", tags=["home"])
        service.create_todo(L, "b", tags=["homework"])
        service.create_todo(L, "c", tags=['say "hi"', "50%"])
        assert _titles(service.list_todos(L, tag="home")) == ["a"]
        assert _titles(service.list_todos(L, tag='say "hi"')) == ["c"]
        assert _titles(service.list_todos(L, tag="50%")) == ["c"]
        assert service.list_todos(L, tag="%") == []

    def test_filter_by_starred(self, L):
        service.create_todo(L, "a", star=True)
        service.create_todo(L, "b")
        assert _titles(service.list_todos(L, starred=True)) == ["a"]
        assert _titles(service.list_todos(L, starred=False)) == ["b"]

    def test_due_ranges_exclude_undated(self, L):
        service.create_todo(L, "early", due_date="2026-01-05")
        service.create_todo(L, "late", due_date="2026-03-05")
        service.create_todo(L, "undated")
        assert _titles(service.list_todos(L, due_before="2026-02-01")) == ["early"]
        assert _titles(service.list_todos(L, due_after="2026-02-01")) == ["late"]

    def test_search_title_and_notes_with_wildcards_escaped(self, L):
        service.create_todo(L, "Buy 100% juice")
        service.create_todo(L, "other", notes="contains JUICE too")
        service.create_todo(L, "snake_case")
        service.create_todo(L, "unrelated")
        assert len(service.list_todos(L, search="juice")) == 2
        assert _titles(service.list_todos(L, search="100%")) == ["Buy 100% juice"]
        assert _titles(service.list_todos(L, search="e_c")) == ["snake_case"]
        assert service.list_todos(L, search="%") == [service.list_todos(L, search="100%")[0]]

    def test_search_matches_context_tags_and_project_name(self, L):
        service.create_todo(L, "a", context="@calls")
        service.create_todo(L, "b", tags=["errands", "café"])
        service.create_todo(L, "c", project="Garage Sale")
        service.create_todo(L, "unrelated")
        assert _titles(service.list_todos(L, search="calls")) == ["a"]
        assert _titles(service.list_todos(L, search="errand")) == ["b"]
        assert _titles(service.list_todos(L, search="café")) == ["b"]
        assert _titles(service.list_todos(L, search="garage")) == ["c"]

    def test_global_search_orders_open_before_done(self, L):
        # Repeating todos pile up done copies with identical titles; the open
        # occurrence must win the LIMIT window in a global (no-status) search.
        service.create_todo(L, "Water the plants", status="done")
        service.create_todo(L, "Water the plants", status="done")
        open_todo = service.create_todo(L, "Water the plants", status="next_action")
        results = service.list_todos(L, search="water")
        assert results[0]["id"] == open_todo["id"]
        assert [t["status"] for t in results] == ["next_action", "done", "done"]
        assert [t["status"] for t in service.list_todos(L, status="done", search="water")] == ["done", "done"]

    def test_ordering_is_fifo(self, L):
        service.create_todo(L, "first")
        service.create_todo(L, "second")
        assert _titles(service.list_todos(L)) == ["first", "second"]

    def test_done_list_is_newest_finished_first(self, L):
        a = service.create_todo(L, "finished early")
        b = service.create_todo(L, "finished late")
        with db.transaction() as conn:
            conn.execute(
                "UPDATE todos SET status='done', completed_at='2026-01-01T10:00:00.000Z' WHERE id=?", (a["id"],)
            )
            conn.execute(
                "UPDATE todos SET status='done', completed_at='2026-06-01T10:00:00.000Z' WHERE id=?", (b["id"],)
            )
        assert _titles(service.list_todos(L, status="done")) == ["finished late", "finished early"]

    def test_limit_is_clamped(self, L):
        for i in range(3):
            service.create_todo(L, f"t{i}")
        assert len(service.list_todos(L, limit=2)) == 2
        assert len(service.list_todos(L, limit=0)) == 1
        assert len(service.list_todos(L, limit=10**9)) == 3


class TestRecurrence:
    def test_completing_repeating_todo_spawns_next_occurrence(self, L):
        a = service.create_todo(
            L,
            "Water the plants",
            status="next_action",
            context="@home",
            notes="both rooms",
            tags=["chore"],
            due_date="2099-06-01",
            repeat="weekly",
            star=True,
            project="House",
        )
        service.update_todo(L, a["id"], {"status": "done"})
        todos = service.list_todos(L, status="next_action")
        assert len(todos) == 1
        nxt = todos[0]
        assert nxt["id"] != a["id"]
        assert nxt["title"] == "Water the plants"
        assert nxt["notes"] == "both rooms"
        assert nxt["due_date"] == "2099-06-08"
        assert nxt["repeat"] == "weekly"
        assert nxt["context"] == "@home"
        assert nxt["tags"] == ["chore"]
        assert nxt["project_name"] == "House"
        assert nxt["star"] is False  # today's priority doesn't carry over
        assert nxt["completed_at"] is None
        assert [t["id"] for t in service.list_todos(L, status="done")] == [a["id"]]

    @pytest.mark.parametrize("prior", ["inbox", "waiting_for", "delegated", "someday_maybe"])
    def test_spawn_preserves_prior_status(self, L, prior):
        a = service.create_todo(L, "repeating", status=prior, repeat="daily")
        service.update_todo(L, a["id"], {"status": "done"})
        spawned = service.list_todos(L, status=prior)
        assert _titles(spawned) == ["repeating"]
        assert spawned[0]["id"] != a["id"]

    def test_spawn_from_dropped_falls_back_to_next_action(self, L):
        a = service.create_todo(L, "was dropped", status="dropped", repeat="weekly")
        service.update_todo(L, a["id"], {"status": "done"})
        assert _titles(service.list_todos(L, status="next_action")) == ["was dropped"]

    def test_non_repeating_does_not_spawn(self, L):
        a = service.create_todo(L, "one-off", status="next_action")
        service.update_todo(L, a["id"], {"status": "done"})
        assert service.list_todos(L, status="next_action") == []

    def test_completing_an_already_done_todo_does_not_respawn_or_retimestamp(self, L):
        b = service.create_todo(L, "weekly thing", status="next_action", repeat="weekly")
        first = service.update_todo(L, b["id"], {"status": "done"})
        again = service.update_todo(L, b["id"], {"notes": "edited after done", "status": "done"})
        assert again["completed_at"] == first["completed_at"]
        assert len(service.list_todos(L, status="next_action")) == 1

    def test_reopen_then_complete_spawns_again(self, L):
        # A deliberate re-completion is a new transition.
        b = service.create_todo(L, "weekly thing", status="next_action", repeat="weekly")
        service.update_todo(L, b["id"], {"status": "done"})
        service.update_todo(L, b["id"], {"status": "next_action"})
        service.update_todo(L, b["id"], {"status": "done"})
        assert len(service.list_todos(L, status="next_action")) == 2

    def test_clearing_repeat_while_completing_does_not_spawn(self, L):
        a = service.create_todo(L, "was repeating", status="next_action", repeat="weekly")
        service.update_todo(L, a["id"], {"repeat": "", "status": "done"})
        assert service.list_todos(L, status="next_action") == []

    def test_edits_saved_with_the_completion_carry_to_the_spawn(self, L):
        a = service.create_todo(L, "old title", status="next_action", repeat="weekly")
        service.update_todo(L, a["id"], {"title": "new title", "repeat": "daily", "status": "done"})
        nxt = service.list_todos(L, status="next_action")[0]
        assert (nxt["title"], nxt["repeat"]) == ("new title", "daily")

    def test_invalid_repeat_rejected(self, L):
        with pytest.raises(ValidationError, match="repeat"):
            service.create_todo(L, "x", repeat="fortnightly")
        a = service.create_todo(L, "y")
        with pytest.raises(ValidationError, match="repeat"):
            service.update_todo(L, a["id"], {"repeat": "hourly"})
        assert service.create_todo(L, "z", repeat="None")["repeat"] == ""

    def test_spawn_copies_provenance(self, L):
        a = service.create_todo(L, "r", repeat="daily", source="agent", source_client="Claude")
        service.update_todo(L, a["id"], {"status": "done"})
        nxt = service.list_todos(L, status="inbox")[0]
        assert (nxt["source"], nxt["source_client"]) == ("agent", "Claude")

    def test_failed_spawn_rolls_back_the_completion(self, L, monkeypatch):
        a = service.create_todo(L, "r", status="next_action", repeat="daily")

        def boom(*args, **kwargs):
            raise RuntimeError("spawn failed")

        monkeypatch.setattr(common, "next_due", boom)
        with pytest.raises(RuntimeError, match="spawn failed"):
            service.update_todo(L, a["id"], {"status": "done", "title": "renamed"})
        after = service.get_todo(L, a["id"])
        assert after["status"] == "next_action"
        assert after["title"] == "r"
        assert after["completed_at"] is None
        assert len(service.list_todos(L)) == 1
        # The connection is usable again (the transaction was closed).
        monkeypatch.undo()
        assert service.update_todo(L, a["id"], {"status": "done"})["status"] == "done"

    def test_two_threads_completing_the_same_todo_spawn_once(self, L):
        a = service.create_todo(L, "r", status="next_action", repeat="daily")
        barrier = threading.Barrier(8)
        errors = []

        def complete():
            try:
                barrier.wait()
                service.update_todo(L, a["id"], {"status": "done"})
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=complete) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(service.list_todos(L, status="done")) == 1
        assert len(service.list_todos(L, status="next_action")) == 1


class TestAutoStar:
    """Opt-in: the spawned occurrence comes back starred only when it is due today."""

    @pytest.fixture(autouse=True)
    def _clock(self, freeze):
        freeze("2026-08-07T18:00:00")  # 1pm Aug 7 in Chicago (the L fixture's zone)
        self.today = datetime.date(2026, 8, 7)

    def _spawn(self, L, days_ago, **kw):
        due = (self.today - datetime.timedelta(days=days_ago)).isoformat()
        a = service.create_todo(L, "routine", status="next_action", repeat="weekly", due_date=due, **kw)
        service.update_todo(L, a["id"], {"status": "done"})
        return service.list_todos(L, status="next_action")[0]

    def test_stars_when_spawn_is_due_today(self, L):
        nxt = self._spawn(L, 7, auto_star_on_due=True)
        assert nxt["due_date"] == "2026-08-07"
        assert nxt["star"] is True
        assert nxt["auto_star_on_due"] is True  # the rule carries forward

    def test_does_not_star_a_future_occurrence(self, L):
        nxt = self._spawn(L, -1, auto_star_on_due=True)
        assert nxt["due_date"] == "2026-08-15"
        assert nxt["star"] is False

    def test_does_not_star_when_more_than_one_interval_late(self, L):
        nxt = self._spawn(L, 14, auto_star_on_due=True)
        assert nxt["due_date"] == "2026-08-14"  # re-anchored past today
        assert nxt["star"] is False

    def test_due_today_without_the_flag_is_not_starred(self, L):
        nxt = self._spawn(L, 7)
        assert nxt["due_date"] == "2026-08-07"
        assert nxt["star"] is False
        assert nxt["auto_star_on_due"] is False


class TestPerListToday:
    """ "Today" is each list's own calendar date."""

    def test_today_view_across_a_timezone_boundary(self, todo_db, freeze):
        freeze("2026-08-08T01:00:00")  # Aug 7 8pm in Chicago, Aug 8 1pm in Auckland
        chicago = lists.create_list("America/Chicago")["list_id"]
        auckland = lists.create_list("Pacific/Auckland")["list_id"]
        for lst in (chicago, auckland):
            service.create_todo(lst, "due the 7th", due_date="2026-08-07")
            service.create_todo(lst, "due the 8th", due_date="2026-08-08")
            service.create_todo(lst, "starred", star=True)
            service.create_todo(lst, "later", due_date="2026-09-01")
            service.create_todo(lst, "done", due_date="2026-08-01", status="done")
            service.create_todo(lst, "archived", due_date="2026-08-01", status="dropped")
        assert _titles(service.today_view(chicago)) == ["due the 7th", "starred"]
        assert _titles(service.today_view(auckland)) == ["due the 7th", "due the 8th", "starred"]

    def test_today_view_across_a_dst_boundary(self, L, freeze):
        service.create_todo(L, "due Nov 1", due_date="2026-11-01")
        freeze("2026-11-01T04:30:00")  # 23:30 Oct 31, still daylight time
        assert service.today_view(L) == []
        freeze("2026-11-01T05:30:00")  # 00:30 Nov 1 CDT — a fixed UTC-6 would say Oct 31
        assert _titles(service.today_view(L)) == ["due Nov 1"]

    def test_spawn_uses_the_lists_own_today(self, todo_db, freeze):
        freeze("2026-08-08T01:00:00")
        results = {}
        for tz in ("America/Chicago", "Pacific/Auckland"):
            lst = lists.create_list(tz)["list_id"]
            a = service.create_todo(
                lst, "daily", status="next_action", repeat="daily", due_date="2026-08-06", auto_star_on_due=True
            )
            service.update_todo(lst, a["id"], {"status": "done"})
            nxt = service.list_todos(lst, status="next_action")[0]
            results[tz] = (nxt["due_date"], nxt["star"])
        # Chicago: one day late on the 7th → due today, starred.
        assert results["America/Chicago"] == ("2026-08-07", True)
        # Auckland: two days late on the 8th → re-anchored to tomorrow, not starred.
        assert results["Pacific/Auckland"] == ("2026-08-09", False)

    def test_filters_carry_the_lists_timezone(self, todo_db):
        assert service.get_filters(lists.create_list("Europe/Paris")["list_id"])["tz"] == "Europe/Paris"
        assert service.get_filters(lists.create_list("Mars/Olympus")["list_id"])["tz"] == "UTC"
        assert service.get_filters(lists.create_list()["list_id"])["tz"] == "UTC"


class TestProjects:
    def test_duplicate_name_rejected(self, L):
        service.create_project(L, "Ops")
        with pytest.raises(ValidationError, match="already exists"):
            service.create_project(L, "ops")

    def test_name_required_and_status_validated(self, L):
        with pytest.raises(ValidationError, match="name is required"):
            service.create_project(L, "  ")
        with pytest.raises(ValidationError, match="Invalid project status"):
            service.create_project(L, "x", status="paused")

    def test_open_count_excludes_done_and_dropped(self, L):
        service.create_todo(L, "a", project="P")
        service.create_todo(L, "b", project="P", status="done")
        service.create_todo(L, "c", project="P", status="dropped")
        assert service.list_projects(L)[0]["open_count"] == 1

    def test_update_project_rename_dup_rejected(self, L):
        service.create_project(L, "A")
        p = service.create_project(L, "B")
        with pytest.raises(ValidationError, match="already exists"):
            service.update_project(L, p["id"], {"name": "a"})
        assert service.update_project(L, p["id"], {"name": "b"})["name"] == "b"  # own name, recased

    def test_update_missing_returns_none(self, L):
        assert service.update_project(L, 999, {"name": "x"}) is None

    def test_archive_and_restore_keeps_todos_attached(self, L):
        todo = service.create_todo(L, "x", project="P")
        pid = todo["project_id"]
        assert service.update_project(L, pid, {"status": "dropped"})["status"] == "dropped"
        assert service.list_projects(L, status="active") == []
        assert service.get_todo(L, todo["id"])["project_id"] == pid
        assert service.update_project(L, pid, {"status": "active"})["status"] == "active"

    def test_list_is_sorted_by_name_case_insensitively(self, L):
        for name in ("beta", "Alpha", "Gamma"):
            service.create_project(L, name)
        assert [p["name"] for p in service.list_projects(L)] == ["Alpha", "beta", "Gamma"]


class TestFilters:
    def test_counts_include_all_statuses_with_zeros(self, L):
        service.create_todo(L, "a")
        filters = service.get_filters(L)
        assert filters["status_counts"]["inbox"] == 1
        assert set(filters["status_counts"]) == set(common.TODO_STATUSES)
        assert filters["status_counts"]["done"] == 0

    def test_contexts_and_tags_deduped(self, L):
        service.create_todo(L, "a", context="@home", tags=["deep", "quick"])
        service.create_todo(L, "b", context="@home", tags=["quick"])
        service.create_todo(L, "c")
        filters = service.get_filters(L)
        assert filters["contexts"] == ["@home"]
        assert filters["tags"] == ["deep", "quick"]


class TestCapture:
    def test_capture_trims_and_lands_in_inbox(self, L):
        todo = service.capture(L, "  buy milk  ")
        assert todo["title"] == "buy milk"
        assert todo["status"] == "inbox"
        assert todo["source"] == "capture"

    def test_capture_empty_rejected(self, L):
        with pytest.raises(ValidationError, match="Nothing to capture"):
            service.capture(L, "   ")

    def test_capture_oversize_rejected(self, L):
        with pytest.raises(ValidationError, match="too long"):
            service.capture(L, "x" * 20_001)


class TestBulkCreate:
    def test_creates_in_order_and_a_done_repeat_spawns_nothing(self, L):
        out = service.bulk_create(
            L, [{"title": "a", "project": "P"}, {"title": "b", "status": "done", "repeat": "daily"}]
        )
        assert out["created"] == 2
        a, b = (service.get_todo(L, i) for i in out["ids"])
        assert (a["title"], a["project_name"], a["source"]) == ("a", "P", "agent")
        assert b["completed_at"] and len(service.list_todos(L)) == 2

    def test_a_bad_item_rolls_back_the_batch_and_is_named(self, L, monkeypatch):
        with pytest.raises(ValidationError, match=r"todos\[1\]: Invalid status 'soon'"):
            service.bulk_create(L, [{"title": "a", "project": "P"}, {"title": "b", "status": "soon"}])
        with pytest.raises(ValidationError, match=r"todos\[0\]: must be an object"):
            service.bulk_create(L, ["a"])
        monkeypatch.setattr(common, "ANON_CAPS", (200, 1, 10))
        with pytest.raises(ValidationError, match=r"todos\[1\]: This list holds 1 projects"):
            service.bulk_create(L, [{"title": "a", "project": "P"}, {"title": "b", "project": "Q"}])
        assert service.list_todos(L) == [] and service.list_projects(L) == []


class TestCaps:
    """Totals per list, counting archived rows, by hosting mode and confirmed
    email (common.caps_for). A refusal changes nothing. The tests run hosted, so
    a fresh list has the anonymous caps; each test shrinks them."""

    def test_todo_cap_counts_archived_rows(self, L, monkeypatch):
        monkeypatch.setattr(common, "ANON_CAPS", (3, 20, 10))
        service.create_todo(L, "a")
        service.create_todo(L, "b", status="done")
        service.create_todo(L, "c", status="dropped")
        with pytest.raises(ValidationError, match="holds 3 todos"):
            service.create_todo(L, "d")
        with pytest.raises(ValidationError, match="holds 3 todos"):
            service.capture(L, "e")
        assert len(service.list_todos(L)) == 3

    def test_todo_cap_is_per_list(self, L, monkeypatch):
        monkeypatch.setattr(common, "ANON_CAPS", (1, 20, 10))
        service.create_todo(L, "a")
        other = lists.create_list()["list_id"]
        assert service.create_todo(other, "fine")["title"] == "fine"

    def test_existing_todos_stay_editable_at_the_cap(self, L, monkeypatch):
        a = service.create_todo(L, "a")
        monkeypatch.setattr(common, "ANON_CAPS", (1, 20, 10))
        assert service.update_todo(L, a["id"], {"status": "done"})["status"] == "done"

    def test_spawn_at_the_cap_refuses_and_rolls_back_the_completion(self, L, monkeypatch):
        a = service.create_todo(L, "r", status="next_action", repeat="daily")
        monkeypatch.setattr(common, "ANON_CAPS", (1, 20, 10))
        with pytest.raises(ValidationError, match="Clear the repeat"):
            service.update_todo(L, a["id"], {"status": "done"})
        assert service.get_todo(L, a["id"])["status"] == "next_action"
        done = service.update_todo(L, a["id"], {"status": "done", "repeat": ""})
        assert done["status"] == "done"
        assert len(service.list_todos(L)) == 1

    def test_project_cap(self, L, monkeypatch):
        monkeypatch.setattr(common, "ANON_CAPS", (200, 2, 10))
        service.create_project(L, "a")
        service.create_project(L, "b", status="dropped")
        with pytest.raises(ValidationError, match="holds 2 projects"):
            service.create_project(L, "c")
        # Auto-creating by name is capped too, and the todo is not half-made.
        with pytest.raises(ValidationError, match="holds 2 projects"):
            service.create_todo(L, "x", project="c")
        t = service.create_todo(L, "y", project="A")  # an existing project still attaches
        with pytest.raises(ValidationError, match="holds 2 projects"):
            service.update_todo(L, t["id"], {"project": "c"})
        assert len(service.list_projects(L)) == 2
        assert _titles(service.list_todos(L)) == ["y"]

    @pytest.fixture()
    def small(self, monkeypatch):
        """Every tier shrunk, each to its own numbers."""
        monkeypatch.setattr(common, "ANON_CAPS", (1, 1, 1))
        monkeypatch.setattr(common, "VERIFIED_CAPS", (2, 2, 2))
        monkeypatch.setattr(common, "SELF_HOST_CAPS", (3, 3, 3))

    def _fill(self, list_id, n):
        """Make n of each; return the refusals the next one of each gets."""
        for i in range(n):
            service.create_todo(list_id, f"t{i}")
            service.create_project(list_id, f"p{i}")
            service.create_area(list_id, f"a{i}")
        refusals = []
        for make in (
            lambda: service.create_todo(list_id, "over"),
            lambda: service.create_project(list_id, "over"),
            lambda: service.create_area(list_id, "over"),
        ):
            with pytest.raises(ValidationError) as e:
                make()
            refusals.append(str(e.value))
        return refusals

    def test_a_hosted_list_without_a_confirmed_email_holds_the_anonymous_caps(self, L, small):
        assert self._fill(L, 1) == [
            f"This list holds 1 {kind} until an email is confirmed in Settings. Nothing was changed."
            for kind in ("todos", "projects", "areas")
        ]

    def test_an_unconfirmed_email_changes_nothing(self, L, small):
        lists.set_email(L, "me@example.com")
        assert "holds 1 todos" in self._fill(L, 1)[0]

    def test_a_confirmed_email_lifts_the_caps_and_keeps_the_full_list_wording(self, L, small, confirm):
        service.create_todo(L, "a")
        with pytest.raises(ValidationError, match="holds 1 todos"):
            service.create_todo(L, "b")
        confirm(L)
        service.create_todo(L, "b")
        other = lists.create_list()["list_id"]
        confirm(other)
        assert self._fill(other, 2) == [
            "This list is full (2 todos, counting done and archived ones). Nothing was changed.",
            "This list has reached its limit of 2 projects (counting completed and archived "
            "ones). Nothing was changed.",
            "This list has reached its limit of 2 areas (counting archived ones). Nothing was changed.",
        ]

    def test_one_list_self_host_has_its_own_caps_confirmed_or_not(self, L, small, confirm, monkeypatch):
        monkeypatch.delenv("OPEN_SIGNUP")
        assert "full (3 todos" in self._fill(L, 3)[0]
        other = lists.create_list()["list_id"]
        confirm(other)
        assert "full (3 todos" in self._fill(other, 3)[0]

    def test_removing_a_confirmed_email_trims_nothing(self, L, small, confirm):
        confirm(L)
        service.create_todo(L, "a")
        service.create_todo(L, "b")
        lists.set_email(L, "")
        assert len(service.list_todos(L)) == 2
        with pytest.raises(ValidationError, match="holds 1 todos"):
            service.create_todo(L, "c")
