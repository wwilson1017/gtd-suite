"""Projects GTD's Card Table automation: rules, card buttons, board buttons and
due-date rules (automation.py), fired from boards.py and recordings.py."""

import datetime
from zoneinfo import ZoneInfo

import pytest

from backend import automation, boards, common, recordings
from backend.common import NotFoundError, ValidationError
from backend.tests.test_mcp import (  # noqa: F401 (fixtures)
    anyio_backend,
    app,
    call,
    connect,
    http,
    link,
    made,
)


@pytest.fixture()
def B(L) -> int:
    return boards.create_board(L, "Kitchen", columns=["Doing", "Review", "Done"])["id"]


def col(L, B, name) -> int:
    return next(c["id"] for c in boards.get_board(L, B)["columns"] if c["name"] == name)


def card_in(L, B, column) -> list[str]:
    return [c["title"] for c in next(c for c in boards.get_board(L, B)["columns"] if c["name"] == column)["cards"]]


def day(n: int) -> str:
    return (common.business_today("America/Chicago") + datetime.timedelta(days=n)).isoformat()


def test_a_rule_acts_when_a_card_moves_in_and_the_trail_says_so(L, B):
    label = boards.create_label(L, B, "Shipped", "green")
    automation.create_rule(
        L,
        B,
        "rule",
        "Done means shipped",
        {"on": "card_moved", "column": "Done"},
        [{"do": "add_label", "label": label["id"]}, {"do": "comment", "text": "Shipped it."}, {"do": "unassign_all"}],
    )
    card = boards.create_card(L, B, "Tile order", column="Doing", assignee_ids=["me"])
    moved = boards.move_card(L, card["id"], "Done")
    assert [lbl["name"] for lbl in moved["labels"]] == ["Shipped"] and moved["assignees"] == []
    assert [c["body"] for c in recordings.comments(L, card_id=card["id"])] == ["Shipped it."]
    assert recordings.comments(L, card_id=card["id"])[0]["creator"]["name"] == automation.ACTOR
    rule = automation.list_rules(L, B)[0]
    assert (rule["runs"], rule["last_error"]) == (1, None)
    boards.move_card(L, card["id"], "Doing")  # out of Done: no rule for that
    assert len(recordings.comments(L, card_id=card["id"])) == 1
    # Archived, it stops; restored, it acts again.
    automation.update_rule(L, rule["id"], {"status": "archived"})
    boards.move_card(L, card["id"], "Done")
    assert len(recordings.comments(L, card_id=card["id"])) == 1
    automation.update_rule(L, rule["id"], {"status": "active"})
    boards.move_card(L, card["id"], "Doing")
    boards.move_card(L, card["id"], "Done")
    assert len(recordings.comments(L, card_id=card["id"])) == 2


def test_added_completed_and_all_subtasks_done(L, B):
    automation.create_rule(
        L,
        B,
        "rule",
        "",
        {"on": "card_added", "column": "Triage"},
        [{"do": "assign", "people": ["me"]}, {"do": "set_due", "days": 2}],
    )
    automation.create_rule(L, B, "rule", "", {"on": "subtasks_done"}, [{"do": "move", "column": "Review"}])
    automation.create_rule(L, B, "rule", "", {"on": "card_completed"}, [{"do": "archive"}])
    card = boards.create_card(L, B, "Grout")
    fresh = boards.get_card(L, card["id"])
    assert [a["kind"] for a in fresh["assignees"]] == ["me"] and fresh["due_date"] == day(2)
    steps = [recordings.create(L, None, "step", {"title": t}, card_id=card["id"]) for t in ("Mix", "Apply")]
    recordings.complete(L, steps[0]["id"])
    assert boards.get_card(L, card["id"])["column_name"] == "Triage"
    recordings.complete(L, steps[1]["id"])
    assert boards.get_card(L, card["id"])["column_name"] == "Review"
    boards.update_card(L, card["id"], {"completed": True})
    assert boards.get_card(L, card["id"])["status"] == "archived"
    # Moving a card into Done completes it too, and fires card_completed once.
    moved = boards.create_card(L, B, "Dragged", column="Doing")
    boards.move_card(L, moved["id"], "Done")
    assert boards.get_card(L, moved["id"])["status"] == "archived"


def test_what_a_rule_does_never_sets_off_another(L, B):
    automation.create_rule(
        L, B, "rule", "", {"on": "card_moved", "column": "Doing"}, [{"do": "move", "column": "Review"}]
    )
    automation.create_rule(
        L, B, "rule", "", {"on": "card_moved", "column": "Review"}, [{"do": "move", "column": "Doing"}]
    )
    card = boards.create_card(L, B, "Ping pong")
    assert boards.move_card(L, card["id"], "Doing")["column_name"] == "Review"  # once, then it stops


def test_an_ai_tools_write_fires_rules_too(L, B):
    automation.create_rule(L, B, "rule", "", {"on": "card_added"}, [{"do": "comment", "text": "Thanks, Claude."}])
    card = boards.create_card(L, B, "From Claude", source="agent", source_client="Claude")
    assert [c["body"] for c in recordings.comments(L, card_id=card["id"])] == ["Thanks, Claude."]


def test_buttons(L, B):
    tidy = automation.create_rule(
        L,
        B,
        "card_button",
        "Start it",
        {},
        [{"do": "move", "column": "Doing", "position": "top"}, {"do": "hold", "on": False}],
    )
    sweep = automation.create_rule(L, B, "board_button", "Clear Done", {"column": "Done"}, [{"do": "archive"}])
    a, b = boards.create_card(L, B, "A"), boards.create_card(L, B, "B", column="Done")
    boards.create_card(L, B, "C", column="Done")
    assert automation.press(L, tidy["id"], a["id"])["cards"] == 1
    assert card_in(L, B, "Doing") == ["A"]
    assert automation.press(L, sweep["id"])["cards"] == 2 and card_in(L, B, "Done") == []
    assert boards.get_card(L, b["id"])["status"] == "archived"
    with pytest.raises(ValidationError, match="Which card"):
        automation.press(L, tidy["id"])
    automation.update_rule(L, tidy["id"], {"status": "archived"})
    with pytest.raises(ValidationError, match="archived"):
        automation.press(L, tidy["id"], a["id"])
    # Assigning keeps who is on the card, but drops someone archived since.
    from backend import people

    bob = people.add(L, "Bob")
    helper = automation.create_rule(L, B, "card_button", "Take it", {}, [{"do": "assign", "people": ["me"]}])
    held = boards.create_card(L, B, "Held", assignee_ids=[bob["id"]])
    people.update(L, bob["id"], {"status": "archived"})
    assert automation.press(L, helper["id"], held["id"])["cards"] == 1
    assert [a["kind"] for a in boards.get_card(L, held["id"])["assignees"]] == ["me"]
    monkey_max = automation.MAX_BUTTON_CARDS
    automation.MAX_BUTTON_CARDS = 1
    try:
        for t in ("D1", "D2"):
            boards.create_card(L, B, t, column="Done")
        with pytest.raises(ValidationError, match="more than 1 cards"):  # every card or none
            automation.press(L, sweep["id"])
    finally:
        automation.MAX_BUTTON_CARDS = monkey_max
    other = boards.create_board(L, "Garage")["id"]
    elsewhere = boards.create_card(L, other, "Elsewhere")
    automation.update_rule(L, tidy["id"], {"status": "active"})
    with pytest.raises(NotFoundError):
        automation.press(L, tidy["id"], elsewhere["id"])


def test_a_due_date_rule_acts_once_per_due_date(L, B):
    automation.create_rule(
        L,
        B,
        "rule",
        "",
        {"on": "due_soon", "days": 1},
        [{"do": "comment", "text": "Due soon."}, {"do": "move", "column": "Doing", "position": "top"}],
    )
    soon = boards.create_card(L, B, "Soon", due_date=day(1))
    later = boards.create_card(L, B, "Later", due_date=day(5))
    boards.create_card(L, B, "Template", due_date=day(0), template=True)
    assert automation.due_tick() == 1
    assert automation.due_tick() == 0  # once per due date
    assert card_in(L, B, "Doing") == ["Soon"] and len(recordings.comments(L, card_id=later["id"])) == 0
    boards.update_card(L, soon["id"], {"due_date": day(0)})  # a new due date: it may act again
    assert automation.due_tick() == 1
    tpl = boards.create_board(L, "A template")["id"]
    boards.update_board(L, tpl, {"template": True})
    automation.create_rule(L, tpl, "rule", "", {"on": "due_soon"}, [{"do": "comment", "text": "No."}])
    boards.create_card(L, tpl, "Template work", due_date=day(0))
    assert automation.due_tick() == 0


def test_rules_are_checked_and_a_failure_is_kept(L, B):
    for kind, trigger, actions, match in (
        ("spell", {}, [{"do": "archive"}], "kind"),
        ("rule", {"on": "card_teleported"}, [{"do": "archive"}], "trigger.on"),
        ("rule", {"on": "card_moved"}, [{"do": "archive"}], "which column"),
        ("rule", {"on": "card_added"}, [], "at least one action"),
        ("rule", {"on": "card_added"}, [{"do": "explode"}], "do must be"),
        ("rule", {"on": "card_added"}, [{"do": "archive"}] * 21, "At most 20"),
        ("rule", {"on": "card_added"}, [{"do": "set_due", "days": 999}], "set_due"),
        ("rule", {"on": "due_soon", "days": 90}, [{"do": "archive"}], "days"),
        ("card_button", {}, [{"do": "archive"}], "needs a name"),
    ):
        with pytest.raises(ValidationError, match=match):
            automation.create_rule(L, B, kind, "", trigger, actions)
    other = boards.create_board(L, "Garage")["id"]
    with pytest.raises(NotFoundError):
        automation.create_rule(
            L, B, "rule", "", {"on": "card_moved", "column": col(L, other, "Done")}, [{"do": "archive"}]
        )
    # An action that can't be done stops that run and is kept for the page to show.
    hold = automation.create_rule(L, B, "rule", "", {"on": "card_added"}, [{"do": "hold", "on": True}])
    boards.create_card(L, B, "Nowhere to hold it")
    assert "On Hold" in automation.get_rule(L, hold["id"])["last_error"]
    automation.update_rule(L, hold["id"], {"status": "archived"})  # archiving clears it
    assert automation.get_rule(L, hold["id"])["last_error"] is None


def test_a_project_holds_at_most_so_many_rules(L, B, monkeypatch):
    monkeypatch.setattr(automation, "MAX_RULES", 2)
    for n in range(2):
        automation.create_rule(L, B, "card_button", f"B{n}", {}, [{"do": "complete"}])
    with pytest.raises(ValidationError, match="at most 2"):
        automation.create_rule(L, B, "card_button", "B3", {}, [{"do": "complete"}])
    # Restoring one counts too.
    first = automation.list_rules(L, B)[0]
    automation.update_rule(L, first["id"], {"status": "archived"})
    automation.create_rule(L, B, "card_button", "B3", {}, [{"do": "complete"}])
    with pytest.raises(ValidationError, match="at most 2"):
        automation.update_rule(L, first["id"], {"status": "active"})


def test_rules_stay_in_their_own_account(L, B, new_list):
    other = new_list()["list_id"]
    theirs = boards.create_board(other, "Theirs")["id"]
    rule = automation.create_rule(other, theirs, "card_button", "Go", {}, [{"do": "archive"}])
    with pytest.raises(NotFoundError):
        automation.get_rule(L, rule["id"])
    with pytest.raises(NotFoundError):
        automation.press(L, rule["id"], boards.create_card(L, B, "Mine")["id"])
    with pytest.raises(NotFoundError):
        automation.create_rule(L, theirs, "rule", "", {"on": "card_added"}, [{"do": "archive"}])


def test_the_automation_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid = c.post(f"{api}/boards", json={"name": "K"}).json()["id"]
    rule = c.post(
        f"{api}/boards/{pid}/rules", json={"kind": "card_button", "name": "Ship", "actions": [{"do": "complete"}]}
    )
    assert rule.status_code == 200
    card = c.post(f"{api}/boards/{pid}/cards", json={"title": "Box"}).json()
    pressed = c.post(f"{api}/rules/{rule.json()['id']}/press", json={"card_id": card["id"]}).json()
    assert pressed["cards"] == 1 and c.get(f"{api}/cards/{card['id']}").json()["completed"] is True
    assert c.put(f"{api}/rules/{rule.json()['id']}", json={"status": "archived"}).json()["status"] == "archived"
    assert c.get(f"{api}/boards/{pid}/rules").json()["rules"] == []
    assert len(c.get(f"{api}/boards/{pid}/rules?status=archived").json()["rules"]) == 1
    bad = c.post(
        f"{api}/boards/{pid}/rules", json={"kind": "rule", "trigger": {"on": "nope"}, "actions": [{"do": "archive"}]}
    )
    assert bad.status_code == 400


def test_every_way_a_card_moves_or_arrives_fires_the_rules(L, B):
    automation.create_rule(
        L, B, "rule", "", {"on": "card_moved", "column": "Done"}, [{"do": "comment", "text": "In Done."}]
    )
    automation.create_rule(
        L, B, "rule", "", {"on": "card_added", "column": "Review"}, [{"do": "comment", "text": "Arrived."}]
    )
    said = lambda card: [c["body"] for c in recordings.comments(L, card_id=card["id"])]  # noqa: E731
    ticked = boards.create_card(L, B, "Ticked", column="Doing")
    boards.update_card(L, ticked["id"], {"completed": True})  # the checkbox relocates it to Done
    assert said(ticked) == ["In Done."]
    bulk = [boards.create_card(L, B, f"Bulk {n}", column="Doing") for n in range(2)]
    boards.create_card(L, B, "Bulk weekly", column="Doing", due_date=day(0), repeat="every_week")
    boards.move_all_cards(L, col(L, B, "Doing"), "Done")
    assert [said(c) for c in bulk] == [["In Done."], ["In Done."]]
    # A repeating card moved to Done in bulk still adds its next one, back in Doing.
    assert [
        c["title"] for c in next(c for c in boards.get_board(L, B)["columns"] if c["name"] == "Doing")["cards"]
    ] == ["Bulk weekly"]
    original = boards.create_card(L, B, "Original", column="Review")  # card_added fires for it
    copied = boards.copy_card(L, original["id"])
    assert said(copied) == ["Arrived."]
    repeating = boards.create_card(L, B, "Weekly", column="Review", due_date=day(0), repeat="every_week")
    boards.move_card(L, repeating["id"], "Done")
    nxt = next(c for c in boards.get_board(L, B)["columns"] if c["name"] == "Review")["cards"]
    newest = next(c for c in nxt if c["title"] == "Weekly")
    assert "Arrived." in [c["body"] for c in recordings.comments(L, card_id=newest["id"])]


# ── Scheduled rules (Trello's scheduled commands) ─────────────────────────────


def test_when_a_scheduled_rule_runs():
    utc = lambda *a: datetime.datetime(*a, tzinfo=datetime.timezone.utc)  # noqa: E731
    week = {"every": "week", "day": 1, "time": "09:00"}  # Mondays, 9:00 in Chicago (14:00 UTC in October)
    assert automation.occurrence(week, "America/Chicago", utc(2026, 10, 12, 15)) == "2026-10-12T14:00:00.000Z"
    assert automation.occurrence(week, "America/Chicago", utc(2026, 10, 12, 13)) is None  # not 9:00 yet
    assert automation.occurrence(week, "America/Chicago", utc(2026, 10, 13, 15)) is None  # a Tuesday
    weekday = {"every": "weekday", "time": "09:00"}
    assert automation.occurrence(weekday, "America/Chicago", utc(2026, 10, 17, 15)) is None  # a Saturday
    assert automation.occurrence(weekday, "America/Chicago", utc(2026, 10, 16, 15)) == "2026-10-16T14:00:00.000Z"
    month = {"every": "month", "day": 13, "time": "17:30"}
    assert automation.occurrence(month, "America/Chicago", utc(2026, 10, 13, 23)) == "2026-10-13T22:30:00.000Z"
    assert automation.occurrence(month, "America/Chicago", utc(2026, 10, 14, 23)) is None
    # Clocks springing forward skip 02:00-03:00 on 8 March 2026: a 02:30 run happens once, at 08:30 UTC.
    gap = {"every": "day", "time": "02:30"}
    assert automation.occurrence(gap, "America/Chicago", utc(2026, 3, 8, 8)) is None
    assert automation.occurrence(gap, "America/Chicago", utc(2026, 3, 8, 8, 30)) == "2026-03-08T08:30:00.000Z"
    # Falling back on 1 November 2026: 9:00 is 15:00 UTC (CST) that day.
    assert (
        automation.occurrence({"every": "day", "time": "09:00"}, "America/Chicago", utc(2026, 11, 1, 15, 30))
        == "2026-11-01T15:00:00.000Z"
    )
    # The local day decides: 03:00 UTC on the 14th is still the 13th in Chicago.
    assert (
        automation.occurrence({"every": "day", "time": "21:00"}, "America/Chicago", utc(2026, 10, 14, 3))
        == "2026-10-14T02:00:00.000Z"
    )


def test_a_scheduled_rule_acts_on_its_column_once_per_run(L, B, monkeypatch):
    automation.create_rule(
        L,
        B,
        "rule",
        "Friday sweep",
        {"on": "scheduled", "column": "Review", "every": "day", "time": "09:00"},
        [{"do": "move", "column": "Done"}],
    )
    for title in ("A", "B"):
        boards.create_card(L, B, title, column="Review")
    tomorrow = common.business_today("America/Chicago") + datetime.timedelta(days=1)
    zone = ZoneInfo("America/Chicago")  # the list's timezone (the L fixture's)

    def at(day, hh, mm):
        monkeypatch.setattr(
            common,
            "utcnow",
            lambda: datetime.datetime.combine(day, datetime.time(hh, mm), zone).astimezone(datetime.timezone.utc),
        )

    at(tomorrow, 8, 59)
    assert automation.scheduled_tick() == 0  # not yet
    at(tomorrow, 9, 1)
    assert automation.scheduled_tick() == 2 and sorted(card_in(L, B, "Done")) == ["A", "B"]
    assert automation.scheduled_tick() == 0  # once a run
    boards.create_card(L, B, "C", column="Review")
    at(tomorrow, 18, 0)
    assert automation.scheduled_tick() == 0 and card_in(L, B, "Review") == ["C"]  # today's run is spent
    at(tomorrow + datetime.timedelta(days=1), 9, 0)
    assert automation.scheduled_tick() == 1 and card_in(L, B, "Review") == []


def test_a_scheduled_rule_is_checked(L, B):
    for trigger, match in (
        ({"on": "scheduled"}, "give it a column"),
        ({"on": "scheduled", "column": "Review", "every": "hourly"}, "trigger.every"),
        ({"on": "scheduled", "column": "Review", "every": "week", "day": 7}, "0 to 6"),
        ({"on": "scheduled", "column": "Review", "every": "month", "day": 31}, "1 to 28"),
        ({"on": "scheduled", "column": "Review", "time": "25:00"}, "HH:MM"),
    ):
        with pytest.raises(ValidationError, match=match):
            automation.create_rule(L, B, "rule", "", trigger, [{"do": "archive"}])
    rule = automation.create_rule(L, B, "rule", "", {"on": "scheduled", "column": "Review"}, [{"do": "archive"}])
    assert rule["trigger"] == {
        "on": "scheduled",
        "column": col(L, B, "Review"),
        "every": "week",
        "day": 1,
        "time": "09:00",
    }


def test_a_scheduled_rule_over_a_full_column_says_so_once(L, B, monkeypatch):
    monkeypatch.setattr(automation, "MAX_BUTTON_CARDS", 1)
    rule = automation.create_rule(
        L, B, "rule", "", {"on": "scheduled", "column": "Review", "every": "day", "time": "09:00"}, [{"do": "archive"}]
    )
    for title in ("A", "B"):
        boards.create_card(L, B, title, column="Review")
    tomorrow = common.business_today("America/Chicago") + datetime.timedelta(days=1)
    when = datetime.datetime.combine(tomorrow, datetime.time(9, 5), ZoneInfo("America/Chicago"))
    monkeypatch.setattr(common, "utcnow", lambda: when.astimezone(datetime.timezone.utc))
    assert automation.scheduled_tick() == 0 and sorted(card_in(L, B, "Review")) == ["A", "B"]
    assert "more than 1 cards" in automation.get_rule(L, rule["id"])["last_error"]
    assert automation.scheduled_tick() == 0  # the run is spent; the next one tries again


def test_a_scheduled_rule_made_after_todays_time_first_runs_tomorrow(L, B, monkeypatch):
    # Midnight has always passed when the rule is made, so today's run is not its to make.
    automation.create_rule(
        L,
        B,
        "rule",
        "",
        {"on": "scheduled", "column": "Review", "every": "day", "time": "00:00"},
        [{"do": "move", "column": "Done"}],
    )
    boards.create_card(L, B, "A", column="Review")
    zone, today = ZoneInfo("America/Chicago"), common.business_today("America/Chicago")
    for day, expect in ((today, 0), (today + datetime.timedelta(days=1), 1)):
        when = datetime.datetime.combine(day, datetime.time(23, 59), zone)
        monkeypatch.setattr(common, "utcnow", lambda w=when: w.astimezone(datetime.timezone.utc))
        assert automation.scheduled_tick() == expect
