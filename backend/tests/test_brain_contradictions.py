"""Disagreements stay visible until the person answers, with scoped, versioned settlement."""

from itertools import combinations

import pytest
from fastmcp.exceptions import ToolError

from backend import apps, brain, db, keys, lists, mcp_server
from backend.common import NotFoundError, ValidationError
from backend.tests.conftest import confirm_list, turn_on
from backend.tests.test_brains import add_brain
from backend.tests.test_mcp import anyio_backend as anyio_backend
from backend.tests.test_mcp import app as app
from backend.tests.test_mcp import call, link
from backend.tests.test_mcp import connect as connect
from backend.tests.test_mcp import made as made
from scripts import admin


@pytest.fixture()
def B(L):
    confirm_list(L)
    return L


@pytest.fixture()
def pair(B):
    bid = brain.first_brain(B)
    a, b = brain.remember(bid, ["Maya works nights", "Maya works days"])["added"]
    out = brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), "Her shifts disagree", by="AI one")
    return bid, a, b, out["contradiction"]


def stored(pair_id):
    return dict(db.get_db().execute("SELECT * FROM brain_contradictions WHERE id = ?", (pair_id,)).fetchone())


def test_flag_preserves_both_memories_and_exposes_sources(pair):
    bid, a, b, flagged = pair
    for original in (a, b):
        current = brain.get_memory(bid, original["id"])
        assert current["status"] == "active"
        assert (current["text"], current["version"]) == (original["text"], original["version"])
        assert len(brain.history(bid, "memory", original["id"])) == 1
    assert flagged["a"] == {"kind": "memory", "id": a["id"], "text": a["text"], "locked": False}
    assert flagged["b"] == {"kind": "memory", "id": b["id"], "text": b["text"], "locked": False}
    assert flagged["flagged_by"] == "AI one" and flagged["flagged_at"]
    assert brain.open_contradictions(bid) == ([flagged], 1)


def test_next_ai_is_asked_and_restricted_start_hides_pairs(pair):
    bid, _, _, flagged = pair
    result = brain.start(bid, "AI two", ["brain"])["contradictions"]
    assert result["open"] == 1 and result["pairs"] == [flagged]
    assert "Never pick one yourself" in result["ask"]
    assert "brain_contradiction_settle" in result["ask"]
    assert "contradictions" not in brain.start(bid, "AI two", ["brain"], restricted=True)


def test_curator_rules_steps_and_unattended_questions(pair):
    bid, _, _, flagged = pair
    result = brain.curate(bid)
    assert result["queue"]["contradictions"] == [flagged]
    assert brain.CURATOR_RULES[-1] == (
        "Never merge a disagreement: when two entries disagree, flag the pair and let the person settle it."
    )
    assert brain.CURATOR_RULES[-1] in result["rules"]
    step = result["steps"][-2]
    assert "brain_contradiction_flag" in step and "brain_contradiction_settle" in step
    assert "never merged" in step and "ask the person" in step
    unattended = brain.curate(bid, unattended=True, folder="weekly")["steps"][-2]
    assert "weekly/questions" in unattended and "never settle one yourself" in unattended
    assert "brain_contradiction_flag" in unattended
    assert "brain_contradiction_flag" in brain.CURATOR_SKILL
    assert "brain_contradiction_settle" in brain.CURATOR_SKILL


def test_duplicate_reversed_self_and_archived_pairs(pair):
    bid, a, b, flagged = pair
    before = stored(flagged["id"])
    for left, right in ((a, b), (b, a)):
        out = brain.flag_contradiction(bid, ("memory", left["id"]), ("memory", right["id"]), "Different note")
        assert out == {"contradiction": flagged, "already": True}
        assert stored(flagged["id"]) == before
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_contradictions").fetchone()[0] == 1
    with pytest.raises(ValidationError, match="An entry cannot disagree with itself"):
        brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", a["id"]), "Wrong")
    brain.update_memory(bid, a["id"], status="archived")
    with pytest.raises(NotFoundError, match="Archived entries cannot be flagged"):
        brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), "Wrong")


def test_cap_all_curator_pairs_and_start_limit(B):
    bid = brain.first_brain(B)
    memories = brain.remember(bid, [f"Fact number {i}" for i in range(11)])["added"]
    pairs = list(combinations(memories, 2))
    ids = []
    for i, (a, b) in enumerate(pairs[:50]):
        ids.append(
            brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), "Disagree")["contradiction"]["id"]
        )
        if i == 24:
            assert len(brain.curate(bid)["queue"]["contradictions"]) == 25
    shown, count = brain.open_contradictions(bid)
    assert count == 50 and [p["id"] for p in shown] == ids[:20]
    assert len(brain.curate(bid)["queue"]["contradictions"]) == 50
    start = brain.start(bid, "Reader", ["brain"])["contradictions"]
    assert start["open"] == 50 and [p["id"] for p in start["pairs"]] == ids[:3]
    a, b = pairs[50]
    with pytest.raises(ValidationError, match="Ask the person about the open"):
        brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), "Disagree")
    # The cap counts active pairs, not dormant or settled rows.
    brain.settle_contradiction(bid, ids[0], "both")
    brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), "Disagree")


def test_memory_page_settlement_versions_the_loser_and_keeps_the_pair(B):
    bid = brain.first_brain(B)
    a = brain.remember(bid, ["Maya works nights"])["added"][0]
    b = brain.write_page(bid, "people/maya", "Maya works days", title="Maya")
    pair = brain.flag_contradiction(bid, ("memory", a["id"]), ("page", b["id"]), "Shifts disagree")["contradiction"]
    assert pair["b"] == {"kind": "page", "id": b["id"], "path": "people/maya", "title": "Maya"}
    out = brain.settle_contradiction(bid, pair["id"], "a", by="AI two", answer="I work nights now")
    assert out["already"] is False and out["kept"] == pair["a"] and out["replaced"] == pair["b"]
    assert out["contradiction"]["b"] == {"kind": "page", "id": b["id"]}
    assert brain.get_page(bid, b["id"])["status"] == "archived"
    assert brain.get_page(bid, b["id"])["version"] == b["version"] + 1
    assert brain.history(bid, "page", b["id"])[0]["reason"] == (
        f"Contradiction {pair['id']}: the person kept memory {a['id']}; it replaces this."
    )
    assert "contradictions" not in brain.start(bid, "AI one", ["brain"])
    assert brain.curate(bid)["queue"]["contradictions"] == []
    row = stored(pair["id"])
    assert row["settled_at"] and row["settled_by"] == "AI two" and row["kept"] == "a"
    assert row["answer"] == "I work nights now"


def test_keep_b_archives_memory_and_names_page(B):
    bid = brain.first_brain(B)
    memory = brain.remember(bid, ["Maya works nights"])["added"][0]
    page = brain.write_page(bid, "people/maya", "Maya works days")
    flagged = brain.flag_contradiction(bid, ("memory", memory["id"]), ("page", page["id"]), "Disagree")["contradiction"]
    brain.settle_contradiction(bid, flagged["id"], "b", by="AI")
    assert brain.get_memory(bid, memory["id"])["status"] == "archived"
    assert brain.get_page(bid, page["id"])["version"] == page["version"]
    assert "page people/maya; it replaces this." in brain.history(bid, "memory", memory["id"])[0]["reason"]


def test_both_and_repeated_settlement_change_nothing_more(pair):
    bid, a, b, flagged = pair
    out = brain.settle_contradiction(bid, flagged["id"], "both", by="AI two", answer="Different weeks")
    assert out["kept"] is None and out["replaced"] is None and out["already"] is False
    before = stored(flagged["id"])
    again = brain.settle_contradiction(bid, flagged["id"], "a", by="AI one", answer="Changed my mind")
    assert again == {"contradiction": out["contradiction"], "already": True}
    assert stored(flagged["id"]) == before
    for original in (a, b):
        current = brain.get_memory(bid, original["id"])
        assert current["status"] == "active" and current["version"] == original["version"]
    assert brain.open_contradictions(bid) == ([], 0)


def test_locked_loser_rolls_back_settlement_and_writer(pair):
    bid, a, _, flagged = pair
    brain.update_memory(bid, a["id"], locked=True)
    before = stored(flagged["id"])
    with pytest.raises(ValidationError, match="locked"):
        brain.settle_contradiction(bid, flagged["id"], "b", by="AI two")
    assert stored(flagged["id"]) == before
    assert brain.open_contradictions(bid)[1] == 1
    assert brain.get_memory(bid, a["id"])["status"] == "active"
    assert "AI two" not in {ai["name"] for ai in brain.ais(bid)}


@pytest.mark.parametrize("access", ["read", "inbox"])
def test_flag_checks_policy(B, access):
    bid = brain.first_brain(B)
    a, b = brain.remember(bid, ["Nights", "Days"])["added"]
    brain.update_brain(B, bid, ai_access=access)
    with pytest.raises(ValidationError):
        brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), "Disagree", by="AI")
    assert brain.open_contradictions(bid) == ([], 0)
    assert brain.ais(bid) == []


@pytest.mark.parametrize("keep", ["a", "b", "both"])
def test_settle_checks_policy_for_every_keep(B, pair, keep):
    bid, a, b, flagged = pair
    brain.update_brain(B, bid, ai_access="read")
    with pytest.raises(ValidationError):
        brain.settle_contradiction(bid, flagged["id"], keep, by="AI two")
    assert brain.open_contradictions(bid)[1] == 1
    assert stored(flagged["id"])["settled_at"] is None
    assert all(brain.get_memory(bid, m["id"])["version"] == m["version"] for m in (a, b))


def test_archive_hides_pair_and_restore_shows_it(pair):
    bid, a, _, flagged = pair
    brain.update_memory(bid, a["id"], status="archived")
    assert brain.open_contradictions(bid) == ([], 0)
    assert stored(flagged["id"])["settled_at"] is None
    brain.update_memory(bid, a["id"], status="active")
    assert brain.open_contradictions(bid) == ([flagged], 1)


@pytest.mark.parametrize("kind", ["memory", "page"])
@pytest.mark.parametrize("moved", [False, True])
@pytest.mark.parametrize("settled", [False, True])
def test_forget_scrubs_account_pairs_even_after_move_or_settlement(B, kind, moved, settled):
    bid = brain.first_brain(B)
    other = add_brain(B, "other")
    a = brain.remember(bid, ["Maya works nights"])["added"][0]
    b = (
        brain.remember(bid, ["Maya works days"])["added"][0]
        if kind == "memory"
        else brain.write_page(bid, "people/maya", "Maya works days")
    )
    flagged = brain.flag_contradiction(bid, ("memory", a["id"]), (kind, b["id"]), "Private disagreement")[
        "contradiction"
    ]
    if settled:
        brain.settle_contradiction(bid, flagged["id"], "both", by="AI", answer="Private answer")
    before = stored(flagged["id"])
    if moved:
        with db.transaction() as conn:
            brain.move_to_brain_in(conn, kind, b["id"], other, None, brain.YOU, None)
        assert brain.open_contradictions(bid) == ([], 0)
    brain.forget(other if moved else bid, kind, b["id"])
    row = stored(flagged["id"])
    assert row["note"] == row["answer"] == ""
    assert row["kept"] == ("both" if settled else "forgotten")
    assert row["settled_by"] == ("AI" if settled else brain.YOU)
    assert row["settled_at"]
    if settled:
        assert row["settled_at"] == before["settled_at"]
    assert brain.open_contradictions(bid) == ([], 0)


@pytest.mark.parametrize("changed", ["a", "b"])
def test_two_pages_stale_pair_cannot_archive_remaining_side(B, changed):
    bid = brain.first_brain(B)
    a = brain.write_page(bid, "people/maya", "Nights")
    b = brain.write_page(bid, "work/maya", "Days")
    flagged = brain.flag_contradiction(bid, ("page", a["id"]), ("page", b["id"]), "Disagree")["contradiction"]
    brain.write_page(bid, (a if changed == "a" else b)["path"], status="archived")
    survivor = b if changed == "a" else a
    with pytest.raises(ValidationError, match="This pair changed since it was flagged"):
        brain.settle_contradiction(bid, flagged["id"], "a", by="AI")
    assert brain.get_page(bid, survivor["id"])["status"] == "active"
    assert brain.get_page(bid, survivor["id"])["version"] == survivor["version"]
    assert stored(flagged["id"])["settled_at"] is None
    assert not brain.settle_contradiction(bid, flagged["id"], "both", by="AI")["already"]


def test_validation_secrets_and_brain_scope(B, pair):
    bid, a, b, flagged = pair
    for note, message in (("  ", "required"), ("x" * 501, "note too long")):
        with pytest.raises(ValidationError, match=message):
            brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), note)
    with pytest.raises(ValidationError, match="kind must"):
        brain.flag_contradiction(bid, ("file", a["id"]), ("memory", b["id"]), "Disagree")
    other = add_brain(B, "other")
    for missing in (other, brain.first_brain(lists.create_list()["list_id"])):
        with pytest.raises(NotFoundError):
            brain.flag_contradiction(missing, ("memory", a["id"]), ("memory", b["id"]), "Disagree")
        with pytest.raises(NotFoundError, match="Contradiction not found"):
            brain.settle_contradiction(missing, flagged["id"], "both")
        assert brain.open_contradictions(missing) == ([], 0)
    with pytest.raises(ValidationError, match="keep must"):
        brain.settle_contradiction(bid, flagged["id"], "neither")
    with pytest.raises(ValidationError, match="answer too long"):
        brain.settle_contradiction(bid, flagged["id"], "a", answer="x" * 501)
    assert brain.get_memory(bid, b["id"])["version"] == b["version"]
    secret = "API key sk-proj-abcdefghijklmnopqrstuvwx123"
    out = brain.settle_contradiction(bid, flagged["id"], "both", answer=secret)
    assert out["contradiction"]["answer"] == "API key [removed: key]"
    new = brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), secret)
    assert new["contradiction"]["note"] == "API key [removed: key]"


def test_table_registry_and_older_admin_cascade(B, pair, monkeypatch, capsys):
    assert "brain_contradictions" in apps.content_tables()
    assert "brain_contradictions" in admin._LIST_TABLES
    monkeypatch.setattr(admin, "_LIST_TABLES", tuple(t for t in admin._LIST_TABLES if t != "brain_contradictions"))
    assert admin.main(["delete", str(B), f"--yes-delete-list-{B}", "--no-snapshot"]) == 0
    assert lists.get_list(B) is None
    assert db.get_db().execute("SELECT COUNT(*) FROM brain_contradictions").fetchone()[0] == 0


def test_folder_keys_do_not_get_either_tool():
    assert "brain_contradiction_flag" not in mcp_server.FOLDER_KEY_TOOLS
    assert "brain_contradiction_settle" not in mcp_server.FOLDER_KEY_TOOLS


@pytest.mark.anyio
async def test_two_ais_flag_ask_and_settle_over_mcp(connect, made):
    lid = made["list_id"]
    turn_on(lid, "brain")
    confirm_list(lid)
    async with connect(link(made), name="AI one") as one:
        memory = (await call(one, "brain_remember", memories=["Maya works nights"]))["added"][0]
        await call(one, "brain_page_write", path="people/maya", body="Maya works days")
        flagged = (
            await call(
                one, "brain_contradiction_flag", a=f"memory:{memory['id']}", b="people/maya", note="Shifts disagree"
            )
        )["contradiction"]
    async with connect(link(made), name="AI two") as two:
        question = (await call(two, "brain_start"))["contradictions"]
        assert question["open"] == 1 and question["pairs"] == [flagged]
        settled = await call(two, "brain_contradiction_settle", id=flagged["id"], keep="a", answer="I work nights")
        assert settled["contradiction"]["settled_by"] == "AI two"
    async with connect(link(made), name="AI one") as one:
        assert "contradictions" not in await call(one, "brain_start")


@pytest.mark.anyio
async def test_mcp_grant_excludes_pair_and_cross_brain_flag_is_refused(connect, made):
    lid = made["list_id"]
    turn_on(lid, "brain")
    confirm_list(lid)
    bid = brain.first_brain(lid)
    other = add_brain(lid, "other")
    a, b = brain.remember(bid, ["Nights", "Days"])["added"]
    brain.write_page(other, "people/maya", "Different shifts")
    flagged = brain.flag_contradiction(bid, ("memory", a["id"]), ("memory", b["id"]), "Disagree")["contradiction"]
    key = keys.create(lid, "Other only", access="write", brains=[other])["key"]
    async with connect("http://testserver/mcp", headers={"Authorization": f"Bearer {key}"}) as client:
        with pytest.raises(ToolError, match="Contradiction not found"):
            await call(client, "brain_contradiction_settle", id=flagged["id"], keep="both")
    assert brain.open_contradictions(bid)[1] == 1
    both = keys.create(lid, "Both brains", access="write", brains=[bid, other])["key"]
    async with connect("http://testserver/mcp", headers={"Authorization": f"Bearer {both}"}) as client:
        with pytest.raises(ToolError, match="Both entries must be in the same brain"):
            await call(
                client, "brain_contradiction_flag", a=f"memory:{a['id']}", b="other/people/maya", note="Disagree"
            )
        own_page = brain.write_page(bid, "people/maya", "Days")
        result = await call(
            client, "brain_contradiction_flag", a=f"memory:{a['id']}", b="brain/people/maya", note="Disagree"
        )
        assert result["contradiction"]["b"] == {
            "kind": "page",
            "id": own_page["id"],
            "path": "brain/people/maya",
            "title": own_page["title"],
        }
