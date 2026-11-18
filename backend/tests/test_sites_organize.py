"""Simple Sites, organised: a private note and a folder on every page and link, search
and folder filters for the app and the agent link."""

import pytest

from backend import sites
from backend.common import ValidationError
from backend.tests.conftest import confirm_list
from backend.tests.test_sites import acct, page, served  # noqa: F401 (fixtures)


def test_a_note_and_a_folder_go_with_a_page_and_never_onto_it(acct, client):
    lid = acct["id"]
    made = sites.publish(lid, "# Board pack", note="For the October board meeting", folder="  Board  ")
    assert (made["note"], made["folder"]) == ("For the October board meeting", "Board")
    from backend.tests.test_sites import ON_SITES, path_of

    assert "October board meeting" not in client.get(path_of(made), headers=ON_SITES).text
    with pytest.raises(ValidationError, match="at most 500"):
        sites.publish(lid, "# x", note="n" * 501)


def test_filing_and_noting_keep_the_page_where_it_was_in_recent_order(acct, freeze):
    confirm_list(acct["id"])  # Ordering needs more than the unconfirmed first page.
    lid = acct["id"]
    freeze("2026-10-17T10:00:00")
    old = page(lid)
    freeze("2026-10-17T11:00:00")
    newer = page(lid)
    freeze("2026-10-17T12:00:00")
    sites.update(lid, old["id"], note="moved", folder="Archive")
    assert [s["id"] for s in sites.list_sites(lid)] == [newer["id"], old["id"]]
    sites.update(lid, old["id"], title="Renamed")  # a real change does move it up
    assert [s["id"] for s in sites.list_sites(lid)][0] == old["id"]


def test_folders_and_search(acct):
    lid = acct["id"]
    confirm_list(lid)
    a = sites.publish(lid, "# Q3 numbers", folder="Board", note="for Dana")
    b = sites.publish(lid, "# Lunch menu", folder="Office")
    c = sites.shorten(lid, "https://example.com/form_100%", folder="Office", title="Sign-up form")
    sites.publish(lid, "# Loose page")
    assert {s["id"] for s in sites.list_sites(lid, folder="Office")} == {b["id"], c["id"]}
    assert [s["title"] for s in sites.list_sites(lid, folder="")] == ["Loose page"]
    assert [s["id"] for s in sites.list_sites(lid, query="dana")] == [a["id"]]  # the note, any case
    assert [s["id"] for s in sites.list_sites(lid, query="form_100%")] == [c["id"]]  # no wildcards
    assert sites.list_sites(lid, query="lunch office") == [sites.list_sites(lid, query="lunch")[0]]
    assert [s["id"] for s in sites.list_sites(lid, query="%")] == [c["id"]]  # a literal %, not "all"
    assert [s["id"] for s in sites.list_sites(lid, query=b["address"])] == [b["id"]]  # the full address
    d = sites.publish(lid, "# Café", folder="École")
    assert [s["id"] for s in sites.list_sites(lid, query="école CAFÉ")] == [d["id"]]  # any letter, any case
    assert sites.list_sites(lid, query=" ".join(["café"] * 10 + ["missing"])) == []  # every word counts
    assert sites.folders(lid) == [
        {"name": "Board", "count": 1},
        {"name": "École", "count": 1},
        {"name": "Office", "count": 2},
    ]


def test_the_agent_link_files_notes_and_finds(acct, client):
    link = acct["path"]
    res = client.post(
        f"{link}?cmd=PUBLISH", json={"content": "# Deck", "note": "for the team", "folder": "Talks"}
    ).json()
    sid = res["page"]["id"]
    assert (res["page"]["note"], res["page"]["folder"]) == ("for the team", "Talks")
    moved = client.post(f"{link}?cmd=EDIT_SITE&id={sid}", json={"folder": "Archive"}).json()
    assert moved["site"]["folder"] == "Archive" and moved["site"]["note"] == "for the team"
    found = client.get(f"{link}?cmd=SITES&folder=Archive").json()
    assert [s["id"] for s in found["sites"]] == [sid]
    assert found["folders"] == [{"name": "Archive", "count": 1}]
    assert client.get(f"{link}?cmd=SITES&q=team").json()["sites"][0]["id"] == sid
    assert client.post(f"{link}?cmd=EDIT_SITE&id={sid}", json={"content": "x"}).status_code == 400


def test_the_browser_api_files_and_searches(acct, new_list):
    made = new_list()
    c = made["client"]
    from backend.tests.conftest import turn_on

    turn_on(made["list_id"], "sites")
    one = c.post("/api/app/sites", json={"content": "# A", "folder": "Work", "note": "for me"}).json()
    assert c.put(f"/api/app/sites/{one['id']}", json={"folder": "Home"}).json()["folder"] == "Home"
    listed = c.get("/api/app/sites?folder=Home&q=me").json()
    assert [s["id"] for s in listed["sites"]] == [one["id"]]
    assert listed["folders"] == [{"name": "Home", "count": 1}]
