"""Own page addresses require browser consent; agents can only suggest them."""

from types import SimpleNamespace

import pytest

from backend import agent_cmd, apps, db, lists, mcp_server, sites, sites_agent
from backend.tests.test_connect import approve, create, start


def test_migration_enables_only_existing_folder_accounts(L):
    other = lists.create_list("UTC")["list_id"]
    empty = lists.create_list("UTC")["list_id"]
    page = sites.publish(L, "Folder")
    sites.publish(other, "Body")
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET layout = 'files', status = 'unpublished' WHERE id = ?", (page["id"],))
        conn.execute("ALTER TABLE lists DROP COLUMN sites_own_host")
    db.init_db()
    assert [lists.get_list(lid)["sites_own_host"] for lid in (L, other, empty)] == [1, 0, 0]
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 0 WHERE id = ?", (L,))
        conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (other,))
    db.init_db()
    assert [lists.get_list(lid)["sites_own_host"] for lid in (L, other, empty)] == [0, 1, 0]


def test_browser_setting_guards_and_folder_refusal(client):
    path = "/api/app/sites/own-host"
    assert client.put(path, json={"on": True}).status_code == 401
    client.post("/api/lists", json={})
    session = client.get("/api/app/session").json()
    lid = session["list_id"]
    assert session["sites_own_host"] is False
    assert client.put(path, json={"on": True}).status_code == 409
    client.headers["X-List"] = str(lid + 1)
    assert client.put(path, json={"on": True}).status_code == 409
    client.headers["X-List"] = str(lid)
    assert client.put(path, json={"on": True}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    response = client.put(path, json={"on": True})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert client.get("/api/app/session").json()["sites_own_host"] is True
    page = sites.publish(lid, "Folder")
    with db.transaction() as conn:
        conn.execute("UPDATE sites SET layout = 'files' WHERE id = ?", (page["id"],))
    response = client.put(path, json={"on": False})
    assert response.status_code == 409 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"error": "Unpublish your folder sites first: they only work at their own address."}
    assert client.get("/api/app/session").json()["sites_own_host"] is True
    sites.update(lid, page["id"], status="unpublished")
    assert client.put(path, json={"on": False}).status_code == 200
    assert client.get("/api/app/session").json()["sites_own_host"] is False


@pytest.mark.parametrize("choice", [None, False, True])
def test_connect_consent(client, monkeypatch, choice):
    monkeypatch.setenv("SITES_BASE_URL", "http://testserver")
    code = start(client)
    lid = create(client, code)
    assert approve(client, code, **({} if choice is None else {"own_host": choice})).status_code == 200
    assert bool(lists.get_list(lid)["sites_own_host"]) is (choice is True)
    # An absent or unchecked choice never turns an existing setting off.
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (lid,))
    code = start(client)
    assert (
        approve(
            client, code, typed_code=code["user_code"], **({} if choice is None else {"own_host": choice})
        ).status_code
        == 200
    )
    assert lists.get_list(lid)["sites_own_host"] == 1


@pytest.mark.parametrize(
    "word", ["LOCALstorage", "sessionStorage", "indexedDB", "fetch(", "youtube.com/embed", "youtube-nocookie.com/embed"]
)
def test_agent_publish_suggestion(L, monkeypatch, word):
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    token = mcp_server._list_id.set(L)
    try:
        result = sites_agent.site_publish(content=word, note="Private note")
        assert "note" in result and "Settings (https://sites.example/app/connect/addresses)" in result["note"]
        assert word.lower() in result["note"].lower()
        assert result["page"]["note"] == "Private note"
        page_id = result["page"]["id"]
        assert "note" in sites_agent.site_publish(content=word, id=page_id)
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET sites_own_host = 1 WHERE id = ?", (L,))
        assert "note" not in sites_agent.site_publish(content=word, id=page_id)
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET sites_own_host = 0 WHERE id = ?", (L,))
        assert "note" not in sites_agent.site_publish(content="Plain", id=page_id)
        monkeypatch.delenv("SITES_CONTENT_DOMAIN")
        assert "note" not in sites_agent.site_publish(content=word, id=page_id)
    finally:
        mcp_server._list_id.reset(token)


def test_agents_cannot_change_own_host():
    assert not any("own_host" in name.lower() for name in mcp_server._TOOL_TITLES)
    assert not any("own_host" in name.lower() for name in agent_cmd._commands(list(apps.APPS)))


def test_command_publish_and_update_suggestion(L, monkeypatch):
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    ctx = SimpleNamespace(list_id=L, client="test")
    result = sites_agent._publish(ctx, {}, {"content": "localStorage"})
    assert "note" in result
    result = sites_agent._publish(ctx, {"id": result["page"]["id"]}, {"content": "indexedDB"})
    assert "indexedDB" in result["note"]


def test_command_update_without_content_has_no_note(L, monkeypatch):
    monkeypatch.setenv("SITES_BASE_URL", "https://sites.example")
    monkeypatch.setenv("SITES_CONTENT_DOMAIN", "content.example")
    ctx = SimpleNamespace(list_id=L, client="test")
    page = sites_agent._publish(ctx, {}, {"content": "plain"})["page"]
    assert "note" not in sites_agent._publish(ctx, {"id": page["id"]}, {"title": "Renamed"})
