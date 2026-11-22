"""Projects GTD's @mentions and "Change dates" on a to-do list
(recordings._mentions_in, mentions_of, shift_dates)."""

import datetime

import pytest

from backend import boards, common, db, people, recordings
from backend.common import ValidationError
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
    return boards.create_board(L, "Kitchen")["id"]


def make(L, B, kind, title="", parent_id=None, source="ui", client=None, **fields):
    if title:
        fields["title"] = title
    return recordings.create(L, B, kind, fields, parent_id=parent_id, source=source, client=client)


def pid(L, name):
    return next(p["id"] for p in people.list_people(L) if p["name"] == name)


def test_mentions_are_people_by_name(L, B):
    make(L, B, "message", "hi", source="agent", client="Claude")  # Claude is a person now
    people.add(L, "Ann")
    people.add(L, "Ann Lee")
    msg = make(
        L,
        B,
        "message",
        "Plan",
        body="@claude and (@Ann Lee), see this. mail me at x@Ann or @Annabel or https://a.b/@Ann",
    )
    assert sorted(msg["mentions"]) == sorted([pid(L, "Claude"), pid(L, "Ann Lee")])
    note = recordings.comment(L, "@Ann please check", rec_id=msg["id"])
    assert recordings.get(L, note["id"])["mentions"] == [pid(L, "Ann")]
    edited = recordings.update(L, msg["id"], {"body": "Nobody now"})
    assert edited.get("mentions") is None
    people.update(L, pid(L, "Ann"), {"status": "archived"})
    assert recordings.comment(L, "@Ann?", rec_id=msg["id"]).get("mentions") is None


def test_an_ai_tool_hears_where_it_was_mentioned(L, B):
    make(L, B, "message", "hi", source="agent", client="Claude")
    claude = pid(L, "Claude")
    tl = make(L, B, "todolist", "Prep")
    todo = make(L, B, "todo", "Order tile", parent_id=tl["id"])
    recordings.comment(L, "@Claude can you cost this out?", rec_id=todo["id"])
    recordings.create(L, B, "chat_line", {"body": "@Claude morning!"})
    heard = recordings.mentions_of(L, claude)
    assert [(m["type"], m["excerpt"]) for m in heard] == [
        ("chat_line", "@Claude morning!"),
        ("comment", "@Claude can you cost this out?"),
    ]
    assert heard[1]["parent_id"] == todo["id"]
    # Only the last two weeks count, and only on what is still out.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE recordings SET created_at = ? WHERE id = ?",
            (common.to_iso(common.utcnow() - datetime.timedelta(days=15)), heard[0]["id"]),
        )
    assert [m["type"] for m in recordings.mentions_of(L, claude)] == ["comment"]
    # An edit that mentions nobody new leaves an old mention old; one that adds someone
    # counts from the edit, and comes first.
    recordings.update(L, heard[0]["id"], {"body": "@Claude morning! Still on?"})
    assert [m["type"] for m in recordings.mentions_of(L, claude)] == ["comment"]
    old_msg = make(L, B, "message", "Old", body="Nobody yet")
    with db.transaction() as conn:
        conn.execute(
            "UPDATE recordings SET created_at = ? WHERE id = ?",
            (common.to_iso(common.utcnow() - datetime.timedelta(days=20)), old_msg["id"]),
        )
    recordings.update(L, old_msg["id"], {"body": "@Claude can you read this?"})
    assert [m["type"] for m in recordings.mentions_of(L, claude)] == ["message", "comment"]
    boards.update_board(L, B, {"status": "archived"})
    assert recordings.mentions_of(L, claude) == []


def test_change_dates_moves_every_open_date_in_a_list(L, B):
    tl = make(L, B, "todolist", "Launch")
    group = make(L, B, "todolist_group", "Week one", parent_id=tl["id"])
    a = make(L, B, "todo", "A", parent_id=tl["id"], starts_on="2026-11-01", due_on="2026-11-03")
    b = make(L, B, "todo", "B", parent_id=group["id"], due_on="2026-11-05")
    step = make(L, B, "step", "B1", parent_id=b["id"], due_on="2026-11-04")
    done = make(L, B, "todo", "Done", parent_id=tl["id"], due_on="2026-11-02")
    recordings.complete(L, done["id"])
    make(L, B, "todo", "Undated", parent_id=tl["id"])
    out = recordings.shift_dates(L, tl["id"], 7)
    assert out["shifted"] == 3
    get = lambda r: recordings.get(L, r["id"])  # noqa: E731
    assert (get(a)["starts_on"], get(a)["due_on"]) == ("2026-11-08", "2026-11-10")
    assert get(b)["due_on"] == "2026-11-12" and get(step)["due_on"] == "2026-11-11"
    assert get(done)["due_on"] == "2026-11-02"  # what is finished keeps its dates
    assert recordings.shift_dates(L, group["id"], -2)["shifted"] == 2
    assert recordings.activity(L)["events"][0]["detail"] == "moved 2 dates -2 days"
    for bad in (0, True, 99999):
        with pytest.raises(ValidationError):
            recordings.shift_dates(L, tl["id"], bad)
    with pytest.raises(ValidationError, match="to-do list"):
        recordings.shift_dates(L, a["id"], 1)
    with pytest.raises(ValidationError, match="out of range"):
        far = make(L, B, "todolist", "Far")
        make(L, B, "todo", "Edge", parent_id=far["id"], due_on="9999-12-30")
        recordings.shift_dates(L, far["id"], 5)


def test_the_shift_api(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    pid_ = c.post(f"{api}/boards", json={"name": "K"}).json()["id"]
    tl = c.post(f"{api}/projects/{pid_}/items", json={"type": "todolist", "title": "L"}).json()
    c.post(
        f"{api}/projects/{pid_}/items",
        json={"type": "todo", "title": "T", "parent_id": tl["id"], "due_on": "2026-11-01"},
    )
    assert c.post(f"{api}/items/{tl['id']}/shift", json={"days": 3}).json()["shifted"] == 1
    assert c.post(f"{api}/items/{tl['id']}/shift", json={"days": 0}).status_code == 400
    # My Tasks lists where I was mentioned (the account's own person, whatever its name).
    me = next(p for p in c.get(f"{api}/people").json()["people"] if p["kind"] == "me")
    c.post(f"{api}/projects/{pid_}/items", json={"type": "message", "title": "M", "body": f"@{me['name']} look"})
    assert [m["excerpt"] for m in c.get(f"{api}/assignments").json()["mentions"]] == [f"@{me['name']} look"]


@pytest.mark.anyio
async def test_activity_list_carries_mentions(connect, made):
    async with connect(link(made)) as c:
        await call(c, "board_create", name="Garage")
        msg = (await call(c, "item_create", project="Garage", type="message", title="Hi"))["item"]
        recordings.comment(made["list_id"], "@pytest-client what do you think?", rec_id=msg["id"])
        heard = (await call(c, "activity_list"))["assigned_to_you"]["mentions"]
        assert [m["excerpt"] for m in heard] == ["@pytest-client what do you think?"]
