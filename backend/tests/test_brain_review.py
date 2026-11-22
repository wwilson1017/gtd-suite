"""Review dates on memories and pages, and the monthly tidy brain_start offers (issue #44)."""

import pytest

from backend import brain, db
from backend.common import ValidationError
from backend.tests.conftest import confirm_list
from backend.tests.test_keys import acct, by_key, new_key  # noqa: F401 (fixture)
from backend.tests.test_mcp import anyio_backend, app, call, connect  # noqa: F401 (fixtures)

AI = "Claude"


@pytest.fixture()
def B(L):
    confirm_list(L)
    return brain.first_brain(L)


def tidy(B):
    return brain.start(B, AI, ["brain"]).get("tidy")


def test_a_tidy_is_offered_after_30_days_and_curate_quiets_it(B, freeze):
    freeze("2026-01-01T12:00:00")
    with db.transaction() as conn:
        conn.execute("UPDATE brains SET created_at = '2026-01-01T12:00:00Z' WHERE id = ?", (B,))
    freeze("2026-01-31T11:00:00")
    assert tidy(B) is None  # not yet 30 days old
    freeze("2026-02-01T12:00:00")
    assert "brain_curate" in tidy(B)  # never tidied, and that old
    brain.curate(B, by=AI)
    assert tidy(B) is None
    freeze("2026-03-02T11:00:00")
    assert tidy(B) is None
    freeze("2026-03-04T12:00:00")
    assert "30 days" in tidy(B)


def test_a_read_only_brain_is_neither_offered_a_tidy_nor_stamped(B, L, freeze):
    freeze("2027-01-01T12:00:00")
    brain.update_brain(L, B, ai_access="read")
    assert tidy(B) is None
    brain.curate(B, by=AI)
    brain.curate(B, stamp=False)
    assert db.get_db().execute("SELECT tidied_at FROM brains WHERE id = ?", (B,)).fetchone()[0] is None
    brain.curate(B)  # the person's own tidy counts
    assert db.get_db().execute("SELECT tidied_at FROM brains WHERE id = ?", (B,)).fetchone()[0]


def test_entries_past_their_review_date_lead_the_queue_most_overdue_first(B, freeze):
    freeze("2026-01-01T12:00:00")
    old = brain.remember(B, ["Maya works nights"], AI)["added"][0]
    locked = brain.remember(B, ["Never email after 6pm"])["added"][0]
    brain.update_memory(B, locked["id"], locked=True)
    brain.write_page(B, "people/maya", "Maya")
    brain.write_page(B, "people/later", "---\nreview_on: 2026-12-01\nlast_checked: 2026-01-01\n---\nLater")
    brain.write_page(B, "people/soon", "---\nreview_on: 2026-02-01\n---\nSoon")
    brain.write_page(B, "people/odd", "---\nreview_on: someday\n---\nOdd")
    brain.write_page(B, "archive/gone", "Gone")
    dated = brain.remember(B, ["The lease ends in March"], AI, review_on="2026-03-01")["added"][0]
    assert dated["review_on"] == "2026-03-01" and old["review_on"] is None

    freeze("2026-03-01T00:30:00")  # due on its day; the undated ones are not yet 90 days old
    queue = brain.curate(B)["queue"]
    assert next(iter(queue)) == "review_due"
    assert queue["review_due"] == [
        {"path": "people/soon", "review_by": "2026-02-01"},
        {"memory": dated["id"], "text": "The lease ends in March", "review_by": "2026-03-01"},
    ]

    freeze("2026-04-15T12:00:00")  # 90 days after the writes: the default date has passed
    queue = brain.curate(B)["queue"]
    due = [e.get("path") or e["memory"] for e in queue["review_due"]]
    assert due == ["people/soon", dated["id"], old["id"], "people/maya", "people/odd"]
    assert queue["review_due"][2]["review_by"] == "2026-04-01"
    assert queue["stale_check"] == []  # a later review date outranks an old last_checked

    # Checked and still true: a new date takes it out; a rewrite restarts the default.
    brain.update_memory(B, dated["id"], by=AI, review_on="2026-09-01")
    brain.update_memory(B, old["id"], text="Maya works days", by=AI)
    brain.edit_page(B, "people/soon", "review_on: 2026-02-01", "review_on: 2026-08-01", by=AI)
    assert [e["path"] for e in brain.curate(B)["queue"]["review_due"]] == ["people/maya", "people/odd"]


def test_review_due_is_cut_to_twenty(B, freeze):
    freeze("2026-01-01T12:00:00")
    brain.remember(B, [f"Fact number {i}" for i in range(25)], AI)
    freeze("2026-06-01T12:00:00")
    assert len(brain.curate(B)["queue"]["review_due"]) == 20


def test_a_memory_review_date_is_a_checked_versioned_write(B, L):
    m = brain.remember(B, ["Maya works nights"], AI)["added"][0]
    with pytest.raises(ValidationError, match="review_on"):
        brain.update_memory(B, m["id"], review_on="2026-02-30", by=AI)
    with pytest.raises(ValidationError, match="review_on"):
        brain.remember(B, ["Another fact"], AI, review_on="next week")
    set_ = brain.update_memory(B, m["id"], review_on="2027-03-01", by=AI)
    assert (set_["review_on"], set_["version"]) == ("2027-03-01", 2)
    newest = brain.history(B, "memory", m["id"])[0]
    assert (newest["action"], newest["reason"]) == ("set the review date of", "review by 2027-03-01")
    assert brain.update_memory(B, m["id"], review_on="2027-03-01", by=AI)["version"] == 2  # no change
    assert brain.update_memory(B, m["id"], text="Maya works days", by=AI)["review_on"] == "2027-03-01"
    assert brain.update_memory(B, m["id"], review_on="", by=AI)["review_on"] is None
    brain.update_brain(L, B, ai_access="read")
    with pytest.raises(ValidationError, match="read-only"):
        brain.update_memory(B, m["id"], review_on="2027-04-01", by=AI)


def test_migration_adds_the_columns_once(B):
    brain.remember(B, ["Kept"], AI)
    with db.transaction() as conn:
        conn.execute("ALTER TABLE brains DROP COLUMN tidied_at")
        conn.execute("ALTER TABLE brain_memories DROP COLUMN review_on")
    db._migrate(db.get_db())
    db._migrate(db.get_db())
    assert brain.memories(B)[0]["review_on"] is None and not brain.tidy_due(B)


@pytest.mark.anyio
async def test_the_tools_set_dates_and_a_read_key_neither_hears_of_nor_records_a_tidy(connect, acct, freeze):  # noqa: F811
    B = brain.first_brain(acct["list_id"])
    with db.transaction() as conn:
        conn.execute("UPDATE brains SET created_at = '2026-01-01T12:00:00Z' WHERE id = ?", (B,))
    async with by_key(connect, new_key(acct["list_id"], "reader", access="read")) as c:
        assert "tidy" not in await call(c, "brain_start")
        await call(c, "brain_curate")
    assert brain.tidy_due(B)
    async with by_key(connect, new_key(acct["list_id"])) as c:
        assert "brain_curate" in (await call(c, "brain_start"))["tidy"]
        added = (await call(c, "brain_remember", memories=["The lease ends in March"], review_on="2020-03-01"))["added"]
        assert added[0]["review_on"] == "2020-03-01"
        queue = (await call(c, "brain_curate"))["queue"]
        assert queue["review_due"][0]["memory"] == added[0]["id"]
        moved = await call(c, "brain_memory_update", id=added[0]["id"], review_on="2999-01-01")
        assert moved["memory"]["review_on"] == "2999-01-01"
        assert "tidy" not in await call(c, "brain_start")
