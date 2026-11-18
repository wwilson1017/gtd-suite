"""Projects GTD as Basecamp: people, recordings (messages, to-dos, comments, …),
boosts, the activity trail, bookmarks and the project page (recordings.py,
people.py), through the service and the web API."""

import pytest

from backend import boards, people, recordings
from backend.common import ConflictError, NotFoundError, ValidationError


@pytest.fixture()
def B(L) -> int:
    return boards.create_board(L, "Kitchen")["id"]


def make(L, B, kind, title="", **kw):
    fields = {k: v for k, v in kw.items() if k not in ("parent_id", "card_id", "source", "client")}
    if title:
        fields["title"] = title
    return recordings.create(
        L,
        B,
        kind,
        fields,
        parent_id=kw.get("parent_id"),
        card_id=kw.get("card_id"),
        source=kw.get("source", "ui"),
        client=kw.get("client"),
    )


# ── People ────────────────────────────────────────────────────────────────────


def test_me_is_made_on_first_write_and_ai_tools_become_people(L):
    assert people.list_people(L) == []
    B = boards.create_board(L, "Kitchen")["id"]  # starting it was the first write
    make(L, B, "message", "Kickoff")
    make(L, B, "message", "From Claude", source="agent", client="Claude")
    make(L, B, "message", "Also Claude", source="agent", client="claude")
    make(L, B, "message", "Unnamed", source="agent")
    assert [(p["kind"], p["name"]) for p in people.list_people(L)] == [
        ("me", "Me"),
        ("ai", "AI tool"),
        ("ai", "Claude"),
    ]


def test_ai_names_cannot_grow_people_past_the_cap(L, B, monkeypatch):
    monkeypatch.setattr(people, "MAX_PEOPLE", 4)  # two places, plus me and "AI tool"
    make(L, B, "message", "a", source="agent", client="Claude")  # me, Claude: the named ones are full
    with pytest.raises(ValidationError, match="at most 2 people"):
        people.add(L, "Ana")
    for n, tool in enumerate(("Tool 1", "Tool 2")):
        made = make(L, B, "message", f"x{n}", source="agent", client=tool)
        assert made["creator"]["name"] == "AI tool"
    assert make(L, B, "message", "d", source="agent", client="Claude")["creator"]["name"] == "Claude"
    assert len(people.list_people(L)) == 3 <= people.MAX_PEOPLE


def test_an_archived_person_cannot_be_assigned_by_id(L, B):
    ana = people.add(L, "Ana")
    people.update(L, ana["id"], {"status": "archived"})
    with pytest.raises(ValidationError, match="Nobody here"):
        make(L, B, "todo", "x", assignee_ids=[ana["id"]])


def test_people_can_be_added_named_and_resolved(L, B):
    ana = people.add(L, "Ana", "Designer")
    assert ana["title"] == "Designer" and ana["color"] in people.COLORS
    with pytest.raises(ValidationError, match="already here"):
        people.add(L, "ana")
    todo = make(L, B, "todo", "Pick tiles", assignee_ids=["ana", "me"])
    assert [a["name"] for a in todo["assignees"]] == ["Ana", "Me"]
    with pytest.raises(ValidationError, match="Nobody here is called Bob"):
        make(L, B, "todo", "x", assignee_ids=["Bob"])
    me = next(p for p in people.list_people(L) if p["kind"] == "me")
    assert [a["name"] for a in make(L, B, "todo", "y", assignee_ids=[me["id"], "me"])["assignees"]] == ["Me"]  # once
    with pytest.raises(ValidationError, match="archive yourself"):
        people.update(L, me["id"], {"status": "archived"})
    assert people.update(L, me["id"], {"name": "Will"})["name"] == "Will"


# ── Messages ──────────────────────────────────────────────────────────────────


def test_messages_list_pinned_first_then_by_sort(L, B):
    a = make(L, B, "message", "Alpha", body="first")
    b = make(L, B, "message", "Bravo")
    c = make(L, B, "message", "Charlie", category="✨ FYI")
    assert [m["title"] for m in recordings.list_items(L, B, "message")] == ["Charlie", "Bravo", "Alpha"]
    recordings.update(L, a["id"], {"pinned": True})
    recordings.update(L, c["id"], {"pinned": True})
    assert [m["title"] for m in recordings.list_items(L, B, "message")] == ["Alpha", "Charlie", "Bravo"]
    recordings.comment(L, "late word", rec_id=b["id"])
    recordings.update(L, a["id"], {"pinned": False})
    recordings.update(L, c["id"], {"pinned": False})
    assert [m["title"] for m in recordings.list_items(L, B, "message", sort="activity")][0] == "Bravo"
    assert [m["title"] for m in recordings.list_items(L, B, "message", sort="alpha")] == ["Alpha", "Bravo", "Charlie"]
    assert recordings.get(L, c["id"])["category"] == "✨ FYI"


def test_a_draft_posts_once_and_never_goes_back(L, B):
    draft = make(L, B, "message", "Plan", status="drafted")
    assert recordings.list_items(L, B, "message") == []
    assert [m["id"] for m in recordings.list_items(L, B, "message", status="drafted")] == [draft["id"]]
    assert recordings.activity(L)["events"][0]["action"] == "started"  # the draft made no trail
    recordings.update(L, draft["id"], {"status": "active"})
    assert recordings.activity(L)["events"][0]["action"] == "posted"
    with pytest.raises(ValidationError, match="back to being a draft"):
        recordings.update(L, draft["id"], {"status": "drafted"})
    with pytest.raises(ValidationError, match="Only a message"):
        make(L, B, "todo", "x", status="drafted")


def test_drafts_are_their_writers_and_an_ais_wait_for_the_person(L, B):
    mine = make(L, B, "message", "My draft", status="drafted")
    theirs = make(L, B, "message", "Claude's draft", status="drafted", source="agent", client="Claude")
    as_claude = {"source": "agent", "client": "Claude"}
    assert [m["title"] for m in recordings.list_items(L, B, "message", "drafted", **as_claude)] == ["Claude's draft"]
    assert [m["title"] for m in recordings.list_items(L, B, "message", "drafted", source="agent", client="Codex")] == []
    assert {m["title"] for m in recordings.list_items(L, B, "message", "drafted")} == {"My draft", "Claude's draft"}
    with pytest.raises(NotFoundError):
        recordings.thread(L, mine["id"], **as_claude)
    with pytest.raises(NotFoundError):
        recordings.update(L, mine["id"], {"status": "active"}, **as_claude)
    assert recordings.thread(L, theirs["id"])["recording"]["title"] == "Claude's draft"
    assert recordings.update(L, theirs["id"], {"status": "active"})["status"] == "active"  # the person posts it


def test_a_restored_pin_never_makes_eleven(L, B):
    msgs = [make(L, B, "message", f"m{n}", pinned=True) for n in range(recordings.MAX_PINNED)]
    recordings.update(L, msgs[0]["id"], {"status": "archived"})
    make(L, B, "message", "new pin", pinned=True)
    back = recordings.update(L, msgs[0]["id"], {"status": "active"})
    assert back["pinned_at"] is None
    pinned = [m for m in recordings.list_items(L, B, "message") if m.get("pinned_at")]
    assert len(pinned) == recordings.MAX_PINNED


def test_an_archived_groups_to_dos_leave_the_lists_progress(L, B):
    tl = make(L, B, "todolist", "T")
    make(L, B, "todo", "kept", parent_id=tl["id"])
    g = make(L, B, "todolist_group", "G", parent_id=tl["id"])
    make(L, B, "todo", "in group", parent_id=g["id"])
    recordings.update(L, g["id"], {"status": "archived"})
    [summary] = recordings.list_items(L, B, "todolist")
    assert summary["todos_count"] == 1


def test_an_archived_card_takes_no_comments_or_subtasks(L, B):
    card = boards.create_card(L, B, "Old")
    boards.update_card(L, card["id"], {"status": "archived"})
    with pytest.raises(ValidationError, match="card is archived"):
        recordings.comment(L, "hi", card_id=card["id"])
    with pytest.raises(ValidationError, match="card is archived"):
        make(L, B, "step", "x", card_id=card["id"])
    with pytest.raises(ValidationError, match="card is archived"):
        recordings.boost(L, "👍", card_id=card["id"])


def test_put_away_containers_take_no_new_work(L, B):
    tl = make(L, B, "todolist", "T")
    todo = make(L, B, "todo", "Sweep", parent_id=tl["id"])
    msg = make(L, B, "message", "Hello")
    recordings.update(L, tl["id"], {"status": "archived"})
    with pytest.raises(ValidationError, match="Restore it first"):
        recordings.complete(L, todo["id"])
    with pytest.raises(ValidationError, match="Restore it first"):
        recordings.boost(L, "🎉", rec_id=todo["id"])
    recordings.update(L, msg["id"], {"status": "archived"})
    with pytest.raises(ValidationError, match="Restore it first"):
        recordings.boost(L, "🎉", rec_id=msg["id"])
    card = boards.create_card(L, B, "C")
    step = make(L, B, "step", "s", card_id=card["id"])
    boards.update_card(L, card["id"], {"status": "archived"})
    with pytest.raises(ValidationError, match="card is archived"):
        recordings.complete(L, step["id"])


def test_activity_links_a_card_where_it_is_now(L, B):
    card = boards.create_card(L, B, "Tile")
    other = boards.create_board(L, "Bath")["id"]
    boards.move_card(L, card["id"], "In progress", board=other)
    created = next(e for e in recordings.activity(L)["events"] if e["action"] == "created")
    assert (created["board_id"], created["card_board_id"]) == (B, other)


def test_a_cards_subtask_stays_on_its_card(L, B):
    card = boards.create_card(L, B, "C")
    step = make(L, B, "step", "s", card_id=card["id"])
    todo = make(L, B, "todo", "T")
    with pytest.raises(ValidationError, match="stays on its card"):
        recordings.move(L, step["id"], parent_id=todo["id"])


def test_at_most_ten_pinned(L, B):
    for n in range(recordings.MAX_PINNED):
        make(L, B, "message", f"m{n}", pinned=True)
    with pytest.raises(ValidationError, match="At most 10"):
        make(L, B, "message", "one more", pinned=True)


# ── To-dos ────────────────────────────────────────────────────────────────────


def test_todo_lists_groups_progress_and_completion(L, B):
    tl = make(L, B, "todolist", "Demo", color="blue")
    group = make(L, B, "todolist_group", "Upstairs", parent_id=tl["id"])
    t1 = make(L, B, "todo", "Rip out tiles", parent_id=tl["id"], due_on="2026-11-01")
    t2 = make(L, B, "todo", "Patch wall", parent_id=group["id"])
    make(L, B, "todo", "Paint", parent_id=group["id"])
    recordings.complete(L, t1["id"])
    recordings.complete(L, t2["id"])
    [summary] = recordings.list_items(L, B, "todolist")
    assert (summary["completed_count"], summary["todos_count"]) == (2, 3)
    page = recordings.thread(L, tl["id"])
    assert [c["title"] for c in page["children"]] == ["Upstairs"]  # t1 is done, so it left
    assert [t["title"] for t in page["children"][0]["todos"]] == ["Paint"]
    assert [t["title"] for t in page["children"][0]["completed_todos"]] == ["Patch wall"]
    assert [t["title"] for t in page["completed"]] == ["Rip out tiles"]
    assert recordings.get(L, t1["id"])["completer"]["kind"] == "me"
    recordings.complete(L, t1["id"], False)
    assert not recordings.get(L, t1["id"])["completed"]
    with pytest.raises(ValidationError, match="can't go inside"):
        make(L, B, "todolist_group", "nested", parent_id=group["id"])
    with pytest.raises(ValidationError, match="color must be one of"):
        make(L, B, "todolist", "Odd", color="mauve")
    with pytest.raises(ValidationError, match="Only a to-do"):
        recordings.complete(L, tl["id"])


def test_loose_todos_and_subtasks(L, B):
    loose = make(L, B, "todo", "Call the plumber")
    tl = make(L, B, "todolist", "Demo")
    make(L, B, "todo", "In a list", parent_id=tl["id"])
    assert [t["title"] for t in recordings.list_items(L, B, "todo")] == ["Call the plumber"]
    step = make(L, B, "step", "Find the number", parent_id=loose["id"])
    recordings.complete(L, step["id"])
    assert [s["completed"] for s in recordings.thread(L, loose["id"])["children"]] == [True]
    with pytest.raises(ValidationError, match="goes on a to-do or a card"):
        make(L, B, "step", "floating")
    card = boards.create_card(L, B, "Order cabinets")
    on_card = make(L, B, "step", "Measure", card_id=card["id"])
    assert on_card["card_id"] == card["id"] and on_card["board_id"] == B


def test_the_todoset_whole(L, B):
    make(L, B, "todo", "Loose")
    done = make(L, B, "todo", "Loose done")
    recordings.complete(L, done["id"])
    tl = make(L, B, "todolist", "Demo")
    g = make(L, B, "todolist_group", "Upstairs", parent_id=tl["id"])
    make(L, B, "todo", "In group", parent_id=g["id"])
    t = make(L, B, "todo", "Direct", parent_id=tl["id"])
    recordings.complete(L, t["id"])
    whole = recordings.todoset(L, B)
    assert [t["title"] for t in whole["loose"]] == ["Loose"]
    assert [t["title"] for t in whole["loose_completed"]] == ["Loose done"]
    [demo] = whole["lists"]
    assert [k["title"] for k in demo["children"]] == ["Upstairs"]
    assert [t["title"] for t in demo["children"][0]["todos"]] == ["In group"]
    assert [t["title"] for t in demo["completed_todos"]] == ["Direct"]
    assert (demo["completed_count"], demo["todos_count"]) == (1, 2)


def test_a_date_edit_is_checked_against_the_saved_range(L, B):
    todo = make(L, B, "todo", "Paint", starts_on="2026-11-01")
    with pytest.raises(ValidationError, match="starts_on must not be after due_on"):
        recordings.update(L, todo["id"], {"due_on": "2026-10-01"})
    assert recordings.update(L, todo["id"], {"due_on": "2026-11-05"})["due_on"] == "2026-11-05"


def test_moving_a_todo_between_lists_and_projects(L, B):
    a, b = make(L, B, "todolist", "A"), make(L, B, "todolist", "B")
    todo = make(L, B, "todo", "Thing", parent_id=a["id"])
    recordings.comment(L, "note", rec_id=todo["id"])
    recordings.move(L, todo["id"], parent_id=b["id"])
    assert recordings.get(L, todo["id"])["parent_id"] == b["id"]
    other = boards.create_board(L, "Garden")["id"]
    recordings.move(L, b["id"], board=other)
    moved = recordings.thread(L, todo["id"])
    assert moved["recording"]["board_id"] == other
    assert moved["comments"][0]["board_id"] == other
    with pytest.raises(ValidationError, match="under a parent instead"):
        recordings.move(L, todo["id"], board=B)


def test_a_drop_names_the_to_do_it_lands_above(L, B):
    tl, other = make(L, B, "todolist", "A"), make(L, B, "todolist", "B")
    a, b, c = (make(L, B, "todo", t, parent_id=tl["id"]) for t in "abc")
    recordings.complete(L, a["id"])  # hidden on the page, still a sibling
    x = make(L, B, "todo", "x", parent_id=other["id"])
    recordings.move(L, x["id"], parent_id=tl["id"], before=c["id"])
    assert [t["title"] for t in recordings.children(L, tl["id"])] == ["a", "b", "x", "c"]
    with pytest.raises(ValidationError, match="same place"):
        recordings.move(L, x["id"], before=x["id"])


def test_a_cards_comments_follow_it_to_another_project(L, B):
    card = boards.create_card(L, B, "Tile")
    note = recordings.comment(L, "Ordered", card_id=card["id"])
    other = boards.create_board(L, "Bath")["id"]
    boards.move_card(L, card["id"], "In progress", board=other)
    assert recordings.get(L, note["id"])["board_id"] == other


def test_reordering_lists(L, B):
    a, b, c = (make(L, B, "todolist", t) for t in "ABC")
    recordings.move(L, c["id"], position="top")
    assert [t["title"] for t in recordings.list_items(L, B, "todolist")] == ["C", "A", "B"]
    recordings.move(L, a["id"], position=2)
    assert [t["title"] for t in recordings.list_items(L, B, "todolist")] == ["C", "B", "A"]


# ── Comments, boosts, versions, statuses ──────────────────────────────────────


def test_comments_and_boosts_on_recordings_and_cards(L, B):
    msg = make(L, B, "message", "Hello")
    comment = recordings.comment(L, "Welcome!", rec_id=msg["id"], source="agent", client="Claude")
    assert comment["creator"]["name"] == "Claude"
    boost = recordings.boost(L, "🎉", rec_id=msg["id"])
    recordings.boost(L, "Nice", rec_id=comment["id"])
    page = recordings.thread(L, msg["id"])
    assert [b["content"] for b in page["recording"]["boosts"]] == ["🎉"]
    assert [b["content"] for b in page["comments"][0]["boosts"]] == ["Nice"]
    assert page["recording"]["comments_count"] == 1
    recordings.unboost(L, boost["id"])
    assert recordings.thread(L, msg["id"])["recording"]["boosts"] == []
    with pytest.raises(ValidationError, match="at most 16"):
        recordings.boost(L, "x" * 17, rec_id=msg["id"])
    with pytest.raises(ValidationError, match="needs some text"):
        recordings.comment(L, "  ", rec_id=msg["id"])
    card = boards.create_card(L, B, "Order cabinets")
    recordings.comment(L, "Ordered", card_id=card["id"])
    recordings.boost(L, "👍", card_id=card["id"])
    make(L, B, "step", "Measure", card_id=card["id"])
    thread = recordings.card_thread(L, card["id"])
    assert [c["body"] for c in thread["comments"]] == ["Ordered"]
    assert [s["title"] for s in thread["subtasks"]] == ["Measure"]
    assert [b["content"] for b in thread["boosts"]] == ["👍"]
    group = make(L, B, "todolist_group", "G", parent_id=make(L, B, "todolist", "T")["id"])
    with pytest.raises(ValidationError, match="can't take comments"):
        recordings.comment(L, "hi", rec_id=group["id"])


def test_a_stale_version_is_refused_and_trash_comes_back(L, B):
    msg = make(L, B, "message", "Hello")
    recordings.update(L, msg["id"], {"body": "agent edit"}, source="agent", client="Claude")
    with pytest.raises(ConflictError):
        recordings.update(L, msg["id"], {"body": "my stale edit"}, version=msg["version"])
    recordings.update(L, msg["id"], {"status": "trashed"})
    assert recordings.list_items(L, B, "message") == []
    assert [m["title"] for m in recordings.list_items(L, B, "message", status="trashed")] == ["Hello"]
    recordings.update(L, msg["id"], {"status": "active"})
    assert [e["action"] for e in recordings.activity(L)["events"][:2]] == ["restored", "trashed"]


def test_other_lists_never_see_each_other(L, B, todo_db):
    from backend import lists

    other = lists.create_list("UTC")["list_id"]
    msg = make(L, B, "message", "Private")
    with pytest.raises(NotFoundError):
        recordings.get(other, msg["id"])
    with pytest.raises(NotFoundError):
        recordings.comment(other, "hi", rec_id=msg["id"])
    with pytest.raises(NotFoundError):
        recordings.create(other, B, "message", {"title": "x"})


def test_a_foreign_parent_never_rides_in_on_a_card(L, B, todo_db):
    from backend import lists

    other = lists.create_list("UTC")["list_id"]
    ob = boards.create_board(other, "Theirs")["id"]
    theirs = make(other, ob, "message", "Victim secret")
    card = boards.create_card(L, B, "Mine")
    with pytest.raises(ValidationError, match="one thing"):
        recordings.create(L, B, "comment", {"body": "x"}, parent_id=theirs["id"], card_id=card["id"])
    assert "Victim secret" not in str(recordings.activity(L))


def test_assignments_skip_a_put_away_list(L, B):
    tl = make(L, B, "todolist", "Chores")
    make(L, B, "todo", "Sweep", parent_id=tl["id"], assignee_ids=["me"])
    assert [t["title"] for t in recordings.assignments(L)] == ["Sweep"]
    recordings.update(L, tl["id"], {"status": "archived"})
    assert recordings.assignments(L) == []


def test_moving_into_a_project_switches_its_tool_on(L, B):
    B2 = boards.create_board(L, "Empty", tools=[])["id"]
    msg = make(L, B, "message", "Hello")
    recordings.move(L, msg["id"], board=B2)
    assert any(e["tool"] == "message_board" and e["enabled"] for e in recordings.project(L, B2)["dock"])


def test_the_recordings_cap_counts_boosts_and_comments(L, B, monkeypatch):
    from backend import common, db

    monkeypatch.setattr(common, "RECORDING_ANON_CAP", 2)
    a = make(L, B, "message", "One")
    make(L, B, "message", "Two")
    with pytest.raises(ValidationError, match="until an email is confirmed"):
        make(L, B, "message", "Three")
    with pytest.raises(ValidationError, match="until an email is confirmed"):
        recordings.boost(L, "Nice!", rec_id=a["id"])
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET email_verified_at = ? WHERE id = ?", (common.now_iso(), L))
    monkeypatch.setattr(common, "RECORDING_VERIFIED_CAP", 2)
    with pytest.raises(ValidationError, match="at most 2"):
        make(L, B, "message", "Three")
    # A boost takes a place too: with room for three, one boost leaves none.
    monkeypatch.setattr(common, "RECORDING_VERIFIED_CAP", 3)
    recordings.boost(L, "Nice!", rec_id=a["id"])
    with pytest.raises(ValidationError, match="at most 3"):
        make(L, B, "message", "Three")


def test_refusals_on_put_away_and_wrong_places(L, B):
    tl = make(L, B, "todolist", "Chores")
    todo = make(L, B, "todo", "Sweep", parent_id=tl["id"])
    msg = make(L, B, "message", "Hello")
    group = make(L, B, "todolist_group", "G", parent_id=tl["id"])
    card = boards.create_card(L, B, "C")
    with pytest.raises(ValidationError, match="A card can't hold"):
        recordings.create(L, B, "message", {"title": "x"}, card_id=card["id"])
    with pytest.raises(ValidationError, match="starts_on"):
        make(L, B, "todo", "Dates", parent_id=tl["id"], starts_on="2026-02-01", due_on="2026-01-01")
    with pytest.raises(ValidationError, match="group can't be boosted"):
        recordings.boost(L, "Hi", rec_id=group["id"])
    b = recordings.boost(L, "Hi", rec_id=msg["id"])
    for bad in (999999, b["id"] + 1000):
        with pytest.raises(NotFoundError):
            recordings.unboost(L, bad)
    recordings.update(L, todo["id"], {"status": "trashed"})
    with pytest.raises(ValidationError, match="Restore it first"):
        recordings.comment(L, "x", rec_id=todo["id"])
    with pytest.raises(ValidationError, match="Restore it first"):
        recordings.move(L, todo["id"], parent_id=group["id"])
    recordings.update(L, tl["id"], {"status": "trashed"})
    with pytest.raises(ValidationError, match="Restore it first"):
        make(L, B, "todo", "Late", parent_id=tl["id"])
    B3 = boards.create_board(L, "Old")["id"]
    boards.update_board(L, B3, {"status": "archived"})
    with pytest.raises(ValidationError, match="This project is archived"):
        make(L, B3, "message", "x")
    with pytest.raises(ValidationError, match="archived"):
        recordings.move(L, msg["id"], board=B3)


# ── The trail, bookmarks, the project page ────────────────────────────────────


def test_the_activity_trail_names_who_did_what(L, B):
    card = boards.create_card(L, B, "Order cabinets", source="agent", source_client="Claude")
    boards.move_card(L, card["id"], "In progress", source="agent", client="Claude")
    todo = make(L, B, "todo", "Call")
    recordings.complete(L, todo["id"])
    page = recordings.activity(L, limit=3)
    assert [(e["creator"]["name"], e["verb"]) for e in page["events"]] == [
        ("Me", "completed"),
        ("Me", "added"),
        ("Claude", "moved"),
    ]
    assert page["events"][2]["card_title"] == "Order cabinets" and page["events"][2]["detail"] == "In progress"
    rest = recordings.activity(L, before=page["next_before"])
    assert [e["action"] for e in rest["events"]] == ["created", "started"]
    assert rest["next_before"] is None


def test_bookmarks_and_assignments(L, B):
    msg = make(L, B, "message", "Hello")
    recordings.bookmark(L, True, rec_id=msg["id"])
    recordings.bookmark(L, True, board_id=B)
    assert [b["title"] for b in recordings.bookmarks(L)] == ["Kitchen", "Hello"]
    recordings.bookmark(L, False, rec_id=msg["id"])
    assert [b["title"] for b in recordings.bookmarks(L)] == ["Kitchen"]
    make(L, B, "todo", "Later", assignee_ids=["me"])
    make(L, B, "todo", "Sooner", assignee_ids=["me"], due_on="2026-11-01")
    make(L, B, "todo", "Not mine")
    assert [t["title"] for t in recordings.assignments(L)] == ["Sooner", "Later"]


def test_the_project_page_has_a_dock_and_previews(L, B):
    # A board from before the dock keeps its card table; the rest wait for "+".
    assert [(t["tool"], t["enabled"]) for t in recordings.project(L, B)["dock"]] == [
        ("kanban_board", True),
        ("message_board", False),
        ("todoset", False),
        ("vault", False),
        ("chat", False),
        ("schedule", False),
        ("questionnaire", False),
        ("doors", False),
    ]
    fresh = boards.create_board(L, "Fresh", tools=[])["id"]
    assert not any(t["enabled"] for t in recordings.project(L, fresh)["dock"])
    # Adding to a tool that is off turns it on: nothing sits in a hidden tool.
    make(L, B, "message", "Hello")
    make(L, B, "todolist", "Demo")
    page = recordings.project(L, B)
    assert [(t["tool"], t["enabled"]) for t in page["dock"]][:3] == [
        ("kanban_board", True),
        ("message_board", True),
        ("todoset", True),
    ]
    assert [m["title"] for m in page["previews"]["message_board"]] == ["Hello"]
    assert [c["name"] for c in page["previews"]["kanban_board"]] == ["Triage", "Not now", "In progress", "Done"]
    dock = recordings.set_dock(
        L, B, [{"tool": "kanban_board", "title": "Board"}, {"tool": "message_board", "enabled": False}]
    )
    assert [(t["tool"], t["title"], t["enabled"]) for t in dock][:3] == [
        ("kanban_board", "Board", True),
        ("message_board", "Messages", False),
        ("todoset", "To-dos", False),
    ]
    with pytest.raises(ValidationError, match="Each tool is one of"):
        recordings.set_dock(L, B, [{"tool": "nope"}])
    # A dock saved under the old (Basecamp) default names shows today's; a name the person chose stays.
    recordings.set_dock(
        L,
        B,
        [
            {"tool": "kanban_board", "title": "Card Table"},
            {"tool": "message_board", "title": "Message Board"},
            {"tool": "vault", "title": "Plans"},
        ],
    )
    assert [t["title"] for t in recordings.project(L, B)["dock"]][:3] == ["Board", "Messages", "Plans"]


# ── The web app's API ─────────────────────────────────────────────────────────


def test_the_project_api_round_trip(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    board = c.post(f"{api}/boards", json={"name": "Kitchen"}).json()
    pid = board["id"]
    tl = c.post(f"{api}/projects/{pid}/items", json={"type": "todolist", "title": "Demo"}).json()
    todo = c.post(
        f"{api}/projects/{pid}/items",
        json={"type": "todo", "title": "Tiles", "parent_id": tl["id"], "assignee_ids": ["me"], "due_on": "2026-11-01"},
    ).json()
    assert todo["assignees"][0]["kind"] == "me"
    done = c.post(f"{api}/items/{todo['id']}/complete", json={"done": True}).json()
    assert done["completed"]
    page = c.get(f"{api}/items/{tl['id']}").json()
    assert page["recording"]["completed_count"] == 1 and page["completed"][0]["id"] == todo["id"]
    msg = c.post(f"{api}/projects/{pid}/items", json={"type": "message", "title": "Hi", "body": "**bold**"}).json()
    assert c.post(f"{api}/items/{msg['id']}/comments", json={"body": "Welcome"}).status_code == 200
    boost = c.post(f"{api}/items/{msg['id']}/boosts", json={"content": "🎉"}).json()
    assert c.post(f"{api}/boosts/{boost['id']}/remove").json()["status"] == "removed"
    stale = c.put(f"{api}/items/{msg['id']}", json={"body": "x", "version": msg["version"] - 1})
    assert stale.status_code == 409 and stale.headers["cache-control"] == "no-store"
    assert c.put(f"{api}/items/{msg['id']}", json={"pinned": True, "version": msg["version"]}).json()["pinned_at"]
    unchanged = c.put(f"{api}/items/{msg['id']}", json={}).json()
    assert unchanged["version"] == msg["version"] + 1  # an empty edit changes nothing
    assert c.put(f"{api}/items/{todo['id']}", json={"category": "x"}).status_code == 400
    items = c.get(f"{api}/projects/{pid}/items?type=message").json()["items"]
    assert [m["comments_count"] for m in items] == [1]
    assert c.post(f"{api}/bookmarks", json={"item_id": msg["id"]}).json() == {"bookmarked": True}
    assert [b["title"] for b in c.get(f"{api}/bookmarks").json()["bookmarks"]] == ["Hi"]
    project = c.get(f"{api}/projects/{pid}").json()
    assert [t["tool"] for t in project["dock"] if t["enabled"]] == ["kanban_board", "message_board", "todoset"]
    home = c.get(f"{api}/home").json()
    assert [p["name"] for p in home["projects"]] == ["Kitchen"]
    assert home["activity"][0]["verb"] == "reacted to" and home["assignments"] == []  # it is done
    assert c.post(f"{api}/people", json={"name": "Ana"}).json()["name"] == "Ana"
    assert [p["name"] for p in c.get(f"{api}/people").json()["people"]] == ["Me", "Ana"]
    card = c.post(f"{api}/boards/{pid}/cards", json={"title": "Cabinets"}).json()
    c.post(f"{api}/cards/{card['id']}/comments", json={"body": "Ordered"})
    assert c.get(f"{api}/cards/{card['id']}/thread").json()["comments"][0]["body"] == "Ordered"
    # Another account sees none of it; a write from another site is refused.
    other = new_list()["client"]
    assert other.get(f"{api}/items/{msg['id']}").status_code == 404
    assert other.post(f"{api}/items/{msg['id']}/comments", json={"body": "x"}).status_code == 404
    cross = c.post(f"{api}/items/{msg['id']}/comments", json={"body": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    unpinned = c.get(f"{api}/home", headers={"X-List": "999"})
    assert unpinned.status_code == 409


# ── The agent link ────────────────────────────────────────────────────────────

from backend.tests.test_mcp import (  # noqa: E402,F401 (fixtures)
    anyio_backend,
    app,
    call,
    connect,
    http,
    link,
    made,
)


@pytest.mark.anyio
async def test_an_agent_works_a_project_over_mcp(connect, made):
    async with connect(link(made)) as c:
        tools = {t.name for t in await c.list_tools()}
        assert {
            "project_open",
            "item_list",
            "item_get",
            "item_create",
            "item_update",
            "item_archive",
            "todo_complete",
            "comment_add",
            "activity_list",
        } <= tools
        assert not any("delete" in t for t in tools)
        await call(c, "board_create", name="Garage")
        tl = (await call(c, "item_create", project="garage", type="todolist", title="Clear out"))["item"]
        todo = (
            await call(
                c,
                "item_create",
                project="garage",
                type="todo",
                title="Sell the bike",
                parent_id=tl["id"],
                assignees=["me"],
                due_on="2026-11-01",
            )
        )["item"]
        assert todo["creator"]["kind"] == "ai" and todo["assignees"][0]["kind"] == "me"
        await call(c, "comment_add", id=todo["id"], text="Listed it online")
        await call(c, "todo_complete", id=todo["id"])
        page = (await call(c, "project_open", project="Garage"))["project"]
        assert page["previews"]["todoset"][0]["completed_count"] == 1
        assert [e["verb"] for e in page["activity"][:3]] == ["completed", "commented on", "added"]
        msg = (await call(c, "item_create", project="Garage", type="message", title="Plan", draft=True))["item"]
        assert msg["status"] == "drafted"
        posted = (await call(c, "item_update", id=msg["id"], post=True))["item"]
        assert posted["status"] == "active"
        stale = await c.call_tool(
            "item_update", {"id": msg["id"], "body": "x", "expected_version": 1}, raise_on_error=False
        )
        assert stale.is_error and "changed since" in stale.content[0].text
        archived = (await call(c, "item_archive", id=msg["id"]))["item"]
        assert archived["status"] == "archived"
        assert (await call(c, "activity_list", project="Garage"))["events"][0]["verb"] == "archived"


@pytest.mark.anyio
async def test_project_commands_read_by_get_and_write_by_post(http, made):
    base = f"/mcp/{made['agent_token']}"
    assert (await http.post(f"{base}?cmd=CREATE_BOARD", json={"name": "Trip"})).json()["ok"]
    assert (await http.get(f"{base}?cmd=ADD_ITEM&project=Trip")).status_code == 405
    res = await http.post(
        f"{base}?cmd=ADD_ITEM&project=Trip", json={"type": "todo", "title": "Book"}, headers={"User-Agent": "Codex/1.0"}
    )
    item = res.json()["item"]
    assert item["creator"]["name"] == "Codex"
    res = await http.post(f"{base}?cmd=COMMENT&id={item['id']}", json={"text": "Booked"})
    assert res.json()["comment"]["body"] == "Booked"
    assert (await http.post(f"{base}?cmd=COMPLETE_TODO&id={item['id']}")).json()["item"]["completed"]
    items = (await http.get(f"{base}?cmd=ITEMS&project=trip&type=todo")).json()["items"]
    assert [i["title"] for i in items] == ["Book"]
    page = (await http.get(f"{base}?cmd=PROJECT&project=Trip")).json()["project"]
    assert [t["tool"] for t in page["dock"] if t["enabled"]] == list(recordings.TOOLS)
    assert [p["name"] for p in (await http.get(f"{base}?cmd=PEOPLE")).json()["people"]] == ["AI tool", "Codex"]
    assert (await http.post(f"{base}?cmd=TRASH_ITEM&id={item['id']}")).status_code == 400
    assert (await http.post(f"{base}?cmd=ARCHIVE_ITEM&id={item['id']}")).json()["item"]["status"] == "archived"
    guide = (await http.get(base, headers={"Accept": "application/json"})).json()
    assert "PROJECT" in str(guide) and "ACTIVITY" in str(guide)
