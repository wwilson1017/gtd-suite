"""Enhanced security (Settings › Security): one switch per account. While it is on the agent
link stops answering after 30 unused days, a new key or staff link needs an end date, and a
new AI tool's first call mails the person. End dates on keys work with the switch off too."""

import threading

import pytest

from backend import connect, db, keys, lists, signin
from backend.common import ValidationError
from backend.tests import test_mcp
from backend.tests.conftest import confirm_list

pytestmark = pytest.mark.anyio

# The MCP suite's fixtures, under their own names: pytest looks a fixture up in the module that asks for it.
anyio_backend, app, http, made = test_mcp.anyio_backend, test_mcp.app, test_mcp.http, test_mcp.made
INIT, MCP_HEADERS = test_mcp.INIT, test_mcp.MCP_HEADERS
PATH = "/api/app/security"


def column(list_id: int, name: str):
    return db.get_db().execute(f"SELECT {name} FROM lists WHERE id = ?", (list_id,)).fetchone()[0]


def bearer(token: str) -> dict:
    return {**MCP_HEADERS, "Authorization": f"Bearer {token}"}


# ── The switch ────────────────────────────────────────────────────────────────


def test_the_switch_is_the_signed_in_browsers_own(client):
    assert client.put(PATH, json={"on": True}).status_code == 401
    client.post("/api/lists", json={})
    session = client.get("/api/app/session").json()
    lid = session["list_id"]
    assert session["enhanced_security"] is False and session["agent_link_expired"] is False
    assert client.put(PATH, json={"on": True}).status_code == 409  # no X-List
    client.headers["X-List"] = str(lid + 1)
    assert client.put(PATH, json={"on": True}).status_code == 409
    client.headers["X-List"] = str(lid)
    assert client.put(PATH, json={"on": True}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert column(lid, "enhanced_security") == 0
    response = client.put(PATH, json={"on": True})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"enhanced_security": True, "agent_link_expired": False}
    assert client.get("/api/app/session").json()["enhanced_security"] is True
    assert client.put(PATH, json={"on": False}).json() == {"enhanced_security": False, "agent_link_expired": False}
    assert client.get("/api/app/session").json()["enhanced_security"] is False


def test_off_to_on_starts_the_thirty_days_and_on_to_on_does_not(L, freeze):
    freeze("2026-01-01T00:00:00")
    lists.set_enhanced_security(L, True)
    assert column(L, "agent_used_at") == "2026-01-01T00:00:00.000Z"
    freeze("2026-01-20T00:00:00")
    lists.set_enhanced_security(L, True)
    assert column(L, "agent_used_at") == "2026-01-01T00:00:00.000Z"
    lists.set_enhanced_security(L, False)
    lists.set_enhanced_security(L, True)
    assert column(L, "agent_used_at") == "2026-01-20T00:00:00.000Z"


# ── The agent link's idle expiry ──────────────────────────────────────────────


def test_an_idle_link_is_a_miss_only_with_the_switch_on_and_off_revives_it(L, freeze):
    token = lists.get_list(L)["agent_token"]
    freeze("2026-01-01T00:00:00")
    lists.set_enhanced_security(L, True)
    freeze("2026-01-31T00:59:59")  # a second short of 30 days and an hour
    assert lists.resolve_agent(token) == L and not lists.agent_link_expired(lists.get_list(L))
    freeze("2026-01-31T01:00:00")
    assert lists.resolve_agent(token) is None and lists.agent_link_expired(lists.get_list(L))
    # Only the agent link idles out: the capture link, and a key, still answer.
    assert lists.resolve_capture(lists.get_list(L)["capture_token"]) == L
    assert keys.resolve(keys.create(L, "program", days=30)["key"])
    lists.set_enhanced_security(L, True)  # on to on: still expired
    assert lists.resolve_agent(token) is None
    lists.set_enhanced_security(L, False)
    assert lists.resolve_agent(token) == L and not lists.agent_link_expired(lists.get_list(L))


def test_with_the_switch_off_an_old_stamp_changes_nothing(L, freeze):
    token = lists.get_list(L)["agent_token"]
    freeze("2026-01-01T00:00:00")
    lists.touch(L, "agent_used_at")
    freeze("2026-04-01T00:00:00")
    assert lists.resolve_agent(token) == L and not lists.agent_link_expired(lists.get_list(L))


def test_a_replaced_link_starts_fresh(L, freeze):
    freeze("2026-01-01T00:00:00")
    lists.set_enhanced_security(L, True)
    freeze("2026-03-01T00:00:00")
    assert lists.agent_link_expired(lists.get_list(L))
    token = lists.rotate_agent(L)
    assert lists.resolve_agent(token) == L and column(L, "agent_used_at") == "2026-03-01T00:00:00.000Z"
    freeze("2026-05-01T00:00:00")
    assert lists.resolve_agent(token) is None
    assert lists.reset_single() and column(L, "agent_used_at") == "2026-05-01T00:00:00.000Z"
    assert lists.resolve_agent(lists.get_list(L)["agent_token"]) == L


async def test_use_stamps_the_link_hourly_so_thirty_days_run_from_the_last_use(http, made, freeze):
    lid, path = made["list_id"], f"/link/{made['agent_token']}"
    freeze("2026-01-01T00:00:00")
    lists.set_enhanced_security(lid, True)
    freeze("2026-01-01T00:59:00")  # within the hour of the stamp: used, not restamped
    assert (await http.get(path)).status_code == 200  # the bare guide counts as use
    assert column(lid, "agent_used_at") == "2026-01-01T00:00:00.000Z"
    # 30 days after that last use the link still answers, and the call restamps it.
    freeze("2026-01-31T00:59:00")
    assert (await http.post(path, json=INIT, headers=MCP_HEADERS)).status_code == 200
    assert column(lid, "agent_used_at") == "2026-01-31T00:59:00.000Z"
    # A key's or a browser's use of the account is not the link's.
    freeze("2026-02-20T00:00:00")
    key = keys.create(lid, "program", days=365)["key"]
    assert (await http.get("/api/v1", headers=bearer(key))).status_code == 200
    assert column(lid, "agent_used_at") == "2026-01-31T00:59:00.000Z"


async def test_an_expired_link_is_a_404_on_its_path_and_a_401_as_a_bearer(http, made, freeze, monkeypatch):
    from backend import ratelimit

    lid, token = made["list_id"], made["agent_token"]
    freeze("2026-01-01T00:00:00")
    lists.set_enhanced_security(lid, True)
    freeze("2026-02-01T00:00:00")
    charged = []
    status = ratelimit.wrong_token_status
    monkeypatch.setattr(ratelimit, "wrong_token_status", lambda request: charged.append(True) or status(request))
    for path in (f"/link/{token}", f"/mcp/{token}", f"/{token}/mcp"):
        for res in (await http.get(path), await http.post(path, json=INIT, headers=MCP_HEADERS)):
            assert res.status_code == 404 and "www-authenticate" not in res.headers, path
    res = await http.post("/mcp", json=INIT, headers=bearer(token))
    assert res.status_code == 401 and res.headers["www-authenticate"] == "Bearer"
    assert len(charged) == 7  # each one a miss, charged to the address like any other
    assert column(lid, "agent_used_at") == "2026-01-01T00:00:00.000Z"  # a miss is not use
    lists.set_enhanced_security(lid, False)
    assert (await http.post(f"/link/{token}", json=INIT, headers=MCP_HEADERS)).status_code == 200
    assert (await http.post("/mcp", json=INIT, headers=bearer(token))).status_code == 200


def test_the_session_says_the_link_expired(client, freeze):
    client.post("/api/lists", json={})
    lid = client.get("/api/app/session").json()["list_id"]
    client.headers["X-List"] = str(lid)
    start = freeze("2026-01-01T00:00:00")
    client.put(PATH, json={"on": True})
    with db.transaction() as conn:  # not the clock: a session lasts less than the 30 days
        conn.execute(
            "UPDATE lists SET agent_used_at = ? WHERE id = ?",
            ((start - lists.AGENT_IDLE).strftime("%Y-%m-%dT%H:%M:%S.000Z"), lid),
        )
    assert client.get("/api/app/session").json()["agent_link_expired"] is True
    assert client.put(PATH, json={"on": True}).json() == {"enhanced_security": True, "agent_link_expired": True}
    client.post("/api/app/agent-link/rotate")
    assert client.get("/api/app/session").json()["agent_link_expired"] is False


def test_approving_a_device_connection_is_use_so_the_link_it_collects_answers(L, freeze):
    token = lists.get_list(L)["agent_token"]
    freeze("2026-01-01T00:00:00")
    lists.set_enhanced_security(L, True)
    freeze("2026-03-01T00:00:00")
    assert lists.resolve_agent(token) is None
    code = connect.start()
    connect.approve(L, code["user_code"], code["user_code"])
    assert connect.poll(code["device_token"]) == {"status": "approved", "agent_token": token}
    assert lists.resolve_agent(token) == L and column(L, "agent_used_at") == "2026-03-01T00:00:00.000Z"


# ── End dates on keys and staff links ─────────────────────────────────────────


def test_a_key_needs_an_end_date_only_while_the_switch_is_on(L, freeze):
    now = freeze("2026-01-01T00:00:00")
    plain = keys.create(L, "plain")
    assert plain["expires_at"] is None and plain["expired"] is False
    assert keys.create(L, "dated", days=90)["expires_at"] == "2026-04-01T00:00:00.000Z"
    with pytest.raises(ValidationError, match="30, 90 or 365"):
        keys.create(L, "odd", days=7)
    lists.set_enhanced_security(L, True)
    for kind in ("key", "link"):
        with pytest.raises(ValidationError, match="choose an end date"):
            keys.create(L, f"none {kind}", kind=kind)
        assert keys.create(L, f"year {kind}", kind=kind, days=365)["expires_at"].startswith("2027-01-01")
    # A key made before the switch went on is untouched: it has no end date and still works.
    assert keys.resolve(plain["key"]) and keys.resolve(plain["key"])["expires_at"] is None
    assert now  # the clock stayed put


def test_the_browser_passes_the_end_date_and_is_told_when_one_is_needed(client, new_list):
    browser = new_list()["client"]
    made = browser.post("/api/app/keys", json={"name": "dated", "days": 30})
    assert made.status_code == 200 and made.json()["expires_at"]
    assert browser.post("/api/app/keys", json={"name": "odd", "days": 31}).status_code == 422
    browser.put(PATH, json={"on": True})
    refused = browser.post("/api/app/keys", json={"name": "none"})
    assert refused.status_code == 400 and "end date" in refused.json()["detail"]
    listed = {k["name"]: (k["expires_at"] is None, k["expired"]) for k in browser.get("/api/app/keys").json()["keys"]}
    assert listed == {"dated": (False, False)}


async def test_a_key_past_its_end_date_is_a_miss_whatever_the_switch_says(http, made, freeze):
    lid = made["list_id"]
    freeze("2026-01-01T00:00:00")
    key = keys.create(lid, "program", days=30)
    staff = keys.create(lid, "Reception", kind="link", days=30)["key"]
    freeze("2026-01-30T23:59:59")
    assert (await http.get("/api/v1", headers=bearer(key["key"]))).status_code == 200
    assert (await http.post(f"/link/{staff}", json=INIT, headers=MCP_HEADERS)).status_code == 200
    freeze("2026-01-31T00:00:00")
    res = await http.get("/api/v1", headers=bearer(key["key"]))
    assert res.status_code == 403 and res.json() == {"error": "unknown or revoked key"}
    assert "www-authenticate" not in res.headers
    res = await http.post("/mcp", json=INIT, headers=bearer(key["key"]))
    assert res.status_code == 401 and res.headers["www-authenticate"] == "Bearer"
    res = await http.post(f"/link/{staff}", json=INIT, headers=MCP_HEADERS)
    assert res.status_code == 404 and "www-authenticate" not in res.headers
    assert keys.resolve(key["key"]) is None and keys.resolve_link(staff) is None
    # It stays listed, as expired, until it is revoked.
    assert {k["name"]: k["expired"] for k in keys.list_keys(lid)} == {"program": True, "Reception": True}
    keys.revoke(lid, key["id"])
    assert [k["name"] for k in keys.list_keys(lid)] == ["Reception"]


def test_an_expired_key_leaves_its_place_under_the_cap_but_keeps_its_name(L, freeze):
    freeze("2026-01-01T00:00:00")
    first = keys.create(L, "k0", days=30)
    for i in range(1, keys.MAX_PER_LIST):
        keys.create(L, f"k{i}")
    with pytest.raises(ValidationError, match="at most 20"):
        keys.create(L, "one more")
    freeze("2026-02-01T00:00:00")
    with pytest.raises(ValidationError, match="already a key called k0"):
        keys.create(L, "k0")
    keys.create(L, "one more")
    keys.revoke(L, first["id"])
    with pytest.raises(ValidationError, match="at most 20"):
        keys.create(L, "k0")


def test_an_old_database_gains_the_columns_with_the_switch_off(L):
    key = keys.create(L, "program")["key"]
    with db.transaction() as conn:
        for name in ("enhanced_security", "agent_used_at", "ai_alert_at"):
            conn.execute(f"ALTER TABLE lists DROP COLUMN {name}")
        conn.execute("ALTER TABLE api_keys DROP COLUMN expires_at")
    db.init_db()
    db.init_db()  # and again changes nothing
    row = lists.get_list(L)
    assert row["enhanced_security"] == 0 and row["agent_used_at"] is None
    assert lists.resolve_agent(row["agent_token"]) == L and keys.resolve(key)["expires_at"] is None


# ── The mail when a new AI tool connects ──────────────────────────────────────


def seen(list_id: int, name: str) -> None:
    """lists.seen_ai, waiting for the mail it may have started on its own thread."""
    lists.seen_ai(list_id, name)
    for thread in threading.enumerate():
        if thread.name == "new-ai-mail":
            thread.join()


def test_a_new_tool_mails_a_confirmed_email_once_a_day_without_its_name(L, mail, freeze):
    freeze("2026-01-01T00:00:00")
    seen(L, "Before")  # known before the switch: it never alerts
    confirm_list(L)
    lists.set_enhanced_security(L, True)
    seen(L, "Before")
    assert mail == []
    freeze("2026-01-02T00:00:00")
    seen(L, "Claude")
    seen(L, "Codex")  # the same day: recorded, no second mail
    assert [to for to, _ in mail] == ["me@example.com"]
    text = mail[0][1]
    assert "Claude" not in text and "Codex" not in text
    assert "https://todo.example/app/connect/ai" in text and "Enhanced security" in text
    assert "new AI tools connected to your account" in text and "revoke any program key or staff link" in text
    freeze("2026-01-02T23:59:59")
    seen(L, "Grok")
    assert len(mail) == 1
    freeze("2026-01-03T00:00:00")
    seen(L, "Claude")  # a name it knows, a copied one included, raises nothing
    assert len(mail) == 1
    seen(L, "Gemini")
    assert len(mail) == 2 and column(L, "ai_alert_at") == "2026-01-03T00:00:00.000Z"


def test_no_mail_with_the_switch_off_an_unconfirmed_email_or_past_the_cap(L, mail, freeze, monkeypatch):
    freeze("2026-01-01T00:00:00")
    confirm_list(L)
    seen(L, "Claude")  # the switch is off
    lists.set_enhanced_security(L, True)
    with db.transaction() as conn:
        lists.set_email_in(conn, L, "new@example.com")  # saved, never confirmed
    seen(L, "Codex")
    assert mail == [] and column(L, "ai_alert_at") is None
    confirm_list(L)
    monkeypatch.setattr(lists, "MAX_AI_TOOLS", 2)
    seen(L, "Grok")  # past the cap: neither recorded nor alerted
    assert mail == [] and column(L, "ai_alert_at") is None


def test_no_mail_and_no_stamp_when_the_server_cannot_mail(L, monkeypatch):
    sent = []
    monkeypatch.setattr(signin, "_send", lambda *a: sent.append(a))
    confirm_list(L)
    lists.set_enhanced_security(L, True)
    seen(L, "Claude")
    assert sent == [] and column(L, "ai_alert_at") is None


def test_a_send_that_fails_is_logged_by_type_and_swallowed(L, mail, monkeypatch, caplog):
    def fail(to, subject, text):
        raise RuntimeError(f"could not reach {to}")

    monkeypatch.setattr(signin, "_send", fail)
    confirm_list(L)
    lists.set_enhanced_security(L, True)
    seen(L, "Claude")
    assert "New-AI mail failed: RuntimeError" in caplog.text and "me@example.com" not in caplog.text
    assert [name for (name,) in db.get_db().execute("SELECT name FROM ai_tools WHERE list_id = ?", (L,))] == ["Claude"]


async def test_a_keys_first_call_sends_the_same_words_which_do_not_blame_the_agent_link(http, made, monkeypatch):
    # The mail fixture's stub, without its client: two app lifespans in one test never end.
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Todo GTD <signin@todo.example>")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    mail = []
    monkeypatch.setattr(signin, "_send", lambda to, subject, text: mail.append((to, text)))
    lid = made["list_id"]
    confirm_list(lid)
    lists.set_enhanced_security(lid, True)
    key = keys.create(lid, "Night robot", days=30)["key"]
    assert (await http.post("/mcp", json=INIT, headers=bearer(key))).status_code == 200
    for thread in threading.enumerate():
        if thread.name == "new-ai-mail":
            thread.join()
    assert [to for to, _ in mail] == ["me@example.com"]
    text = mail[0][1]
    assert "new AI tools connected to your account" in text and "revoke any program key or staff link" in text
    assert "used your agent link" not in text and "Night robot" not in text
