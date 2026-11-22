"""Level cases moved from test_brains.py."""

import json
import pytest
from backend import brain, common, db, files, keys, lists
from backend.common import ValidationError
from backend.tests.conftest import confirm_list as confirm_list
from backend.tests.test_files import CFG as CFG, FakeStore as FakeStore, item as item
from backend.tests.test_brains import TABLES as TABLES, store as store


@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize(
    "hosted,tier,brains_cap,links_cap",
    [(True, None, 1, 3), (True, "pro", 10, 100), (True, "max", 100, 1000), (False, None, 100, 1000)],
)
def test_brain_and_staff_link_plan_caps(verified, hosted, tier, brains_cap, links_cap):
    assert common.brains_cap_for(verified, hosted, tier) == brains_cap
    assert common.links_cap_for(verified, hosted, tier) == links_cap


def test_owner_brain_routes_caps_and_lapse(new_list, monkeypatch):
    made = new_list()
    c, account = made["client"], made["list_id"]
    first = brain.first_brain(account)
    assert c.get("/api/app/session").json()["caps"]["brains"] == 1
    assert c.post("/api/app/brains", json={"name": "Work"}).status_code == 400
    assert c.post(f"/api/app/brains/{first}/archive").status_code == 400
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '9999-01-01T00:00:00Z', comp_plan = 'pro' WHERE id = ?", (account,)
        )
    second = c.post("/api/app/brains", json={"name": "Work", "rules": ["Work only"], "ai_access": "inbox"}).json()
    assert second["settled_at"] and second["folder"] == "work"
    assert c.put(f"/api/app/brains/{second['id']}", json={"description": "Company"}).json()["rules"] == ["Work only"]
    assert c.put("/api/app/link-brains", json={"brains": [second["id"], first]}).json() == {
        "brains": [second["id"], first]
    }
    page = brain.write_page(first, "hello", "Move me")
    move = {"kind": "page", "id": page["id"], "to_brain": second["id"], "path": "hello", "expected_version": 1}
    assert c.post("/api/app/brain/move", json=move).json()["version"] == 2
    outsider = lists.create_list()["list_id"]
    move["to_brain"] = brain.first_brain(outsider)
    assert c.post("/api/app/brain/move", json=move).status_code == 400
    for method, path, body in [
        ("post", "/api/app/brains", {}),
        ("put", "/api/app/link-brains", {"brains": []}),
        ("put", f"/api/app/brains/{first}", {}),
    ]:
        assert getattr(c, method)(path, json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert getattr(c, method)(path, json=body, headers={"X-List": str(outsider)}).status_code == 409
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET pro_comp_until = NULL WHERE id = ?", (account,))
    assert c.post("/api/app/brains", json={"name": "Third"}).status_code == 400
    assert [b["id"] for b in brain.main_brains(account)] == [second["id"], first]
    assert c.post(f"/api/app/brains/{second['id']}/archive").status_code == 200
    assert [b["id"] for b in brain.main_brains(account)] == [first]
    refused = c.post(f"/api/app/brains/{second['id']}/restore")  # a restore counts against the cap too
    assert refused.status_code == 400 and "at most 1 brains" in refused.text
    assert brain.brain_status(account, second["id"], "archived")["status"] == "archived"  # archived to archived
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '9999-01-01T00:00:00Z', comp_plan = 'pro' WHERE id = ?", (account,)
        )
    assert c.post(f"/api/app/brains/{second['id']}/restore").status_code == 200
    assert c.post(f"/api/app/brains/{first}/restore").status_code == 200  # already active: no count
    assert c.get("/api/app/brains").headers["cache-control"] == "no-store"


def test_merge_brain_preserves_rows_keys_policy_and_disables_source(L, store):
    from scripts import admin

    target = lists.create_list()["list_id"]
    confirm_list(L)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '9999-01-01T00:00:00Z', comp_plan = 'pro' WHERE id = ?", (target,)
        )
    source = brain.first_brain(L)
    page = brain.write_page(source, "private", "Before")
    brain.write_page(source, "private", "After")
    brain.remember(source, ["Secret memory"])
    brain.search(source, "missingword", by="Curator")
    upload = files.reserve(source, [item("file.pdf", b"x")])["files"][0]
    store.put(upload["upload"], b"x")
    files.done(source, upload["id"])
    key = keys.create(L, "ACME", access="write", folders=["inbox"])
    staff = keys.create(L, "Staff", kind="link")
    keys.create(target, "acme")
    brain.update_brain(L, source, name="Original", description="Personal", rules=["Personal only"], ai_access="inbox")
    before = {t: [dict(r) for r in db.get_db().execute(f"SELECT * FROM {t} WHERE list_id = ?", (L,))] for t in TABLES}
    dry = admin.merge_brain(L, target, "Personal", "personal")
    assert dry["counts"]["brain_pages"] == 1 and dry["clashes"] == ["ACME"]
    assert dry["keys"][0]["brains"] == json.dumps([source])
    assert keys.resolve(key["key"])["list_id"] == L
    result = admin.merge_brain(L, target, "Personal", "personal", yes=True)
    bid = result["to_brain"]
    moved = next(b for b in brain.brains(target) if b["id"] == bid)
    assert moved["ai_access"] == "inbox" and moved["rules"] == ["Personal only"] and moved["description"] == "Personal"
    for table, rows in before.items():
        assert [dict(r) for r in db.get_db().execute(f"SELECT * FROM {table} WHERE brain_id = ?", (bid,))] == [
            {**r, "brain_id": bid, "list_id": target} for r in rows
        ]
    resolved = keys.resolve(key["key"])
    assert (resolved["list_id"], resolved["name"], resolved["brains"], resolved["folders"]) == (
        target,
        "ACME-personal",
        [bid],
        ["inbox"],
    )
    assert keys.resolve_link(staff["key"])["brains"] == [bid]
    assert len(brain.history(bid, "page", page["id"])) == 2
    assert db.get_db().execute("SELECT disabled_at FROM lists WHERE id = ?", (L,)).fetchone()[0]
    with pytest.raises(ValidationError, match="disabled"):
        admin.merge_brain(L, target, "Again", "again", yes=True)
    assert db.get_db().execute("PRAGMA foreign_key_check").fetchall() == []


def test_merge_names_an_unsettled_source_brain_for_good(L):
    from scripts import admin

    target = lists.create_list()["list_id"]
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '9999-01-01T00:00:00Z', comp_plan = 'pro' WHERE id = ?", (target,)
        )
    source = brain.first_brain(L)
    assert (
        brain._brain_out(db.get_db().execute("SELECT * FROM brains WHERE id = ?", (source,)).fetchone())["settled_at"]
        is None
    )  # as every migrated brain is
    bid = admin.merge_brain(L, target, "Personal", "personal", yes=True)["to_brain"]
    moved = next(b for b in brain.brains(target) if b["id"] == bid)
    assert moved["settled_at"] and moved["name"] == "Personal" and moved["folder"] == "personal"
    with pytest.raises(ValidationError, match="Only the person"):
        brain.setup(bid, "Renamed", "", ["Other rules"], by="Claude")
