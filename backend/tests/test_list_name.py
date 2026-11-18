"""The optional list name."""

import pytest

from backend import common, lists, pages


def test_a_list_has_no_name_by_default_and_one_click_still_creates_it(new_list):
    made = new_list()
    c = made["client"]
    assert made["name"] == ""
    assert c.get("/api/app/name").json() == {"name": ""}
    assert c.get("/api/app/filters").json()["name"] == ""
    assert c.get("/api/app/session").json()["email"] is None


def test_create_accepts_a_name_and_ignores_an_email(client):
    body = client.post("/api/lists", json={"name": "  Home   and garden ", "email": "Me@Example.com"}).json()
    assert body["name"] == "Home and garden"
    session = client.get("/api/app/session").json()
    assert (
        client.get("/api/app/filters", headers={"X-List": str(session["list_id"])}).json()["name"] == "Home and garden"
    )
    assert session["email"] is None  # an email is added under Connect, never at creation


def test_the_name_route_sets_changes_and_clears(client, new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    res = c.put(f"{api}/name", json={"name": " Work "})
    assert res.json() == {"name": "Work"} and res.headers["cache-control"] == "no-store"
    assert c.get(f"{api}/name").json() == {"name": "Work"}
    assert c.put(f"{api}/name", json={"name": None}).json() == {"name": ""}
    assert c.get(f"{api}/filters").json()["name"] == ""
    assert client.put("/api/app/name", json={"name": "x"}).status_code == 401


def test_the_name_is_capped_and_must_be_printable(create, new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    ok = "n" * common.MAX_LIST_NAME_CHARS
    assert c.put(f"{api}/name", json={"name": ok}).json() == {"name": ok}
    res = c.put(f"{api}/name", json={"name": ok + "n"})
    assert res.status_code == 400 and "too long" in res.json()["detail"]
    assert c.put(f"{api}/name", json={"name": "a\x00b"}).status_code == 400
    assert c.get(f"{api}/name").json() == {"name": ok}
    assert create(json={"name": ok + "n"}).status_code == 400


def test_requiring_a_name_is_one_flag(create, monkeypatch):
    monkeypatch.setattr(common, "LIST_NAME_REQUIRED", True)
    res = create(json={"tz": "UTC"})
    assert res.status_code == 400 and res.json()["detail"] == "Give your list a name"
    assert create(json={"name": "Mine"}).status_code == 200


@pytest.fixture()
def built(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html><head></head><body></body></html>")
    monkeypatch.setattr(pages, "INDEX_PATH", tmp_path / "index.html")
    monkeypatch.setattr(pages, "_index_cache", None)


def test_the_installed_app_is_todo_gtd_whatever_the_list_is_called(new_list, built):
    made = new_list()
    c = made["client"]
    lists.set_name(made["list_id"], 'Home "& <garden>')
    manifest = c.get("/app/manifest.webmanifest").json()
    assert manifest["name"] == manifest["short_name"] == "Todo GTD"
    page = c.get("/app").text
    assert 'apple-mobile-web-app-title" content="Todo GTD"' in page and "garden" not in page
