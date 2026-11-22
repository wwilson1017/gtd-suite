"""Tickles: one unanswered question a day, from the golden page and repeated misses (#43)."""

import pytest

from backend import brain, db
from backend.common import ValidationError
from backend.tests.conftest import confirm_list
from backend.tests.test_brains import add_brain
from backend.tests.test_keys import acct, by_key, new_key  # noqa: F401 (fixture)
from backend.tests.test_mcp import anyio_backend, app, call, connect, link  # noqa: F401 (fixtures)


@pytest.fixture()
def B(L):
    confirm_list(L)
    return brain.first_brain(L)


def miss(b, query, times=2, by="Claude"):
    for _ in range(times):
        brain.search(b, query, by=by)


def tickle(b, by="Claude"):
    return brain.start(b, by, ["brain"]).get("tickle")


def test_a_golden_question_the_brain_cannot_answer_comes_first_then_rests(B, freeze):
    freeze("2026-11-02T15:00:00")
    assert tickle(B) is None  # nothing to ask yet, and a missing golden page is no error
    brain.write_page(B, "people/maya", "Apricot expert", title="Maya")
    brain.write_page(
        B, "curator/golden", "# Top\n- q1: apricot => people/maya\n- q2: Sam  Birthday => people/sam\nnot a line\n"
    )
    miss(B, "wifi password")
    got = tickle(B)
    assert (got["question"], got["from"], got["save_to"]) == ("Sam  Birthday", "golden", ["people/sam"])
    assert got["times_asked"] == 0 and got["stale"] is False and "brain_tickle_record" in got["do"]
    # Handing it out records nothing: an unattended run must not use up the day's question.
    assert tickle(B, "Cron")["question"] == "Sam  Birthday"
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_tickles").fetchone()[0] == 0
    # Ask, save, record: the record still takes the question, in any case or spacing.
    brain.write_page(B, "people/sam", "Sam's birthday is 3 May (source: the person, 2026-11-02)")
    assert brain.tickle_record(B, "sam birthday", "Claude") == {
        "ok": True,
        "question": "sam birthday",
        "times_asked": 1,
        "rests_days": 5,
    }
    assert brain.tickle_record(B, "Sam Birthday", "Grok")["times_asked"] == 1  # a retry is the same ask
    assert tickle(B) is None  # one a day, whatever else is waiting
    freeze("2026-11-03T15:00:00")
    assert tickle(B)["question"] == "wifi password"  # q2 passes now, so the repeated miss is next
    # Neither the probes nor the hand-outs logged a miss or wrote a scorecard.
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_misses").fetchone()[0] == 2
    assert not [p for p in brain.pages(B) if p["path"] == "curator/scorecard"]


def test_a_repeated_miss_is_asked_until_it_is_answered(B, freeze):
    freeze("2026-11-02T15:00:00")
    miss(B, "dentist phone", times=1)
    assert tickle(B) is None  # asked once: not yet
    brain.search(B, "[tag] Dentist  PHONE", by="Grok")
    miss(B, "invoice OR bill", times=3)
    got = tickle(B)
    assert (got["question"], got["from"], got["searched"]) == ("invoice or bill", "miss", 3)
    assert "save_to" not in got
    brain.remember(B, ["The bill goes to accounts@example.com"], by="Claude")
    assert tickle(B)["question"] == "dentist phone"  # OR stayed an OR: one side answers it
    # A curator page that only quotes the question does not answer it.
    brain.write_page(B, "curator/questions", "- dentist phone?")
    assert tickle(B)["question"] == "dentist phone"
    brain.write_page(B, "people/dentist", "Dentist: phone 555-0100")
    assert tickle(B) is None
    assert brain.overview(B)["misses"] == []
    # The record takes a repeated miss answered since, and nothing else.
    assert brain.tickle_record(B, "dentist phone", "Claude")["times_asked"] == 1
    with pytest.raises(ValidationError, match="not a question"):
        brain.tickle_record(B, "something an AI made up", "Claude")
    freeze("2026-12-03T15:00:00")
    assert brain._miss_groups(db.get_db(), B) == []  # misses age out after 30 days


def test_rest_counts_the_accounts_calendar_days_and_three_asks_is_stale(B, L, freeze):
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET tz = 'America/Chicago' WHERE id = ?", (L,))
    brain.write_page(B, "curator/golden", "- a: alpha => people/a\n- b: beta => people/b")
    freeze("2026-11-02T04:30:00")  # 1 Nov, 22:30 in Chicago
    assert tickle(B)["question"] == "alpha"
    brain.tickle_record(B, "alpha", "Claude")
    assert tickle(B) is None
    freeze("2026-11-02T07:00:00")  # 2 Nov, 01:00 in Chicago: a new day, alpha rests
    assert tickle(B)["question"] == "beta"
    freeze("2026-11-06T05:30:00")  # still 5 Nov there, the last rest day
    assert tickle(B)["question"] == "beta"
    freeze("2026-11-06T07:00:00")
    assert tickle(B)["question"] == "alpha"
    for day in ("2026-11-06", "2026-11-12"):
        freeze(day + "T15:00:00")
        brain.tickle_record(B, "alpha", "Claude")
    freeze("2026-11-18T15:00:00")
    got = tickle(B)
    assert (got["question"], got["times_asked"], got["stale"]) == ("alpha", 3, True)
    assert "asked 3 times" in got["do"]


def test_no_tickle_where_the_ai_cannot_save_or_record(B, L, freeze):
    freeze("2026-11-02T15:00:00")
    brain.write_page(B, "curator/golden", "- a: alpha => people/a")
    assert tickle(B)
    assert "tickle" not in brain.start(B, "Claude", ["brain"], restricted=True)
    for access in ("read", "inbox"):
        brain.update_brain(L, B, ai_access=access)
        assert tickle(B) is None
        with pytest.raises(ValidationError):
            brain.tickle_record(B, "alpha", "Claude")
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_tickles").fetchone()[0] == 0


def test_only_the_first_twenty_golden_lines_are_probed(B, monkeypatch):
    brain.write_page(B, "curator/golden", "\n".join(f"- q{i}: word{i} => people/p{i}" for i in range(30)))
    brain.write_page(B, "people/all", " ".join(f"word{i}" for i in range(30)), title="All")
    for i in range(20):
        brain.write_page(B, f"people/p{i}", f"word{i}")
    probes = []
    actual = brain.search
    monkeypatch.setattr(brain, "search", lambda *a, **k: probes.append(a[1]) or actual(*a, **k))
    assert tickle(B) is None and len(probes) == 20


def test_onboarding_asks_for_the_top_questions_and_the_tidy_says_when_they_are_missing(B):
    script = " ".join(brain.onboard_script(B, "Claude")["script"])
    assert "Top questions" in script and "curator/golden" in script and "brain_eval" in script
    assert "top_questions" in brain.onboarded(B, "Claude")
    assert brain.curate(B)["queue"]["golden"].startswith("missing")
    brain.write_page(B, "curator/golden", "- q1: sam birthday => people/sam")
    assert "top_questions" not in brain.onboarded(B, "Claude")
    assert brain.curate(B)["queue"]["golden"] == "exists"
    assert brain.evaluate(B, by="Claude") == {"score": 0, "n": 1, "failures": ["q1"]}


def test_the_home_lists_what_ais_asked_and_the_brain_cannot_answer(B, freeze):
    freeze("2026-11-02T15:00:00")
    for i in range(7):
        miss(B, f"question{i}", times=i + 1)
    brain.remember(B, ["question6 is answered"], by="Claude")
    assert brain.overview(B)["misses"] == [
        {"query": f"question{i}", "asked": i + 1, "last": "2026-11-02T15:00:00.000Z"} for i in (5, 4, 3, 2, 1)
    ]


def test_tickle_rows_go_with_their_brain(B, L):
    brain.write_page(B, "curator/golden", "- a: alpha => people/a")
    brain.tickle_record(B, "alpha", "Claude")
    with db.transaction() as conn:
        for table in ("brain_ais", "brain_versions", "brain_pages", "brains"):
            conn.execute(f"DELETE FROM {table} WHERE list_id = ?", (L,))
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_tickles").fetchone()[0] == 0


@pytest.mark.anyio
async def test_the_agent_link_hands_out_one_tickle_and_records_it(connect, acct, freeze):  # noqa: F811
    freeze("2026-11-02T15:00:00")
    L = acct["list_id"]
    first = brain.first_brain(L)
    second = add_brain(L, "work")
    # Written through the blended link, a golden line names its page with the brain's folder.
    brain.write_page(first, "curator/golden", "- a: alpha => brain/people/a")
    brain.write_page(second, "curator/golden", "- a: alpha => people/a")
    brain.set_link_brains(L, [first, second])
    async with connect(link(acct), name="Claude") as c:
        started = await call(c, "brain_start")
        assert len(started["brains"]) == 2
        tickles = [g["tickle"] for g in started["guidance"] if "tickle" in g]
        assert tickles[0]["save_to"] == ["brain/people/a"] and "brain=brain" in tickles[0]["do"]
        assert len(tickles) == 1 and tickles[0]["question"] == "alpha"
        recorded = await call(c, "brain_tickle_record", question="alpha")
        assert recorded["times_asked"] == 1
        with pytest.raises(Exception, match="not a question"):
            await call(c, "brain_tickle_record", question="made up")
        # Answered where save_to said, the question passes for the tickle and for brain_eval.
        await call(c, "brain_page_write", path="brain/people/a", body="alpha is answered")
        assert (await call(c, "brain_eval", brain="brain"))["score"] == 1
    freeze("2026-11-03T15:00:00")
    async with connect(link(acct), name="Claude") as c:
        guidance = (await call(c, "brain_start"))["guidance"]
        assert "tickle" not in guidance[0] and guidance[1]["tickle"]["save_to"] == ["work/people/a"]
    # A read-only key is handed nothing: it could not record the ask.
    freeze("2026-11-03T15:00:00")
    async with by_key(connect, new_key(L, access="read")) as c:
        assert "tickle" not in await call(c, "brain_start")
