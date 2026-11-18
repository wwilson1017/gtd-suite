"""Device connection consent, account binding and single-use delivery."""

from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from backend import cleanup, common, connect, db, lists, main, ratelimit
from scripts import admin


@pytest.fixture(autouse=True)
def served(client, monkeypatch):
    monkeypatch.setenv("SITES_BASE_URL", "http://testserver")


def start(client):
    response = client.post("/api/connect", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["url"] == f"http://testserver/connect?code={result['user_code']}"
    assert result["interval"] == 3 and result["expires_in"] == 900
    assert len(result["user_code"]) == 9
    return result


def poll(client, code):
    return client.post("/api/connect/poll", json={"device_token": code["device_token"]})


def create(client, code):
    response = client.post("/api/lists", json={"connect": code["user_code"]})
    assert response.status_code == 200
    lid = client.get("/api/app/session").json()["list_id"]
    client.headers["X-List"] = str(lid)
    return lid


def approve(client, code, **body):
    return client.post(f"/api/app/connect/{code['user_code']}", json=body)


def test_create_approve_rotate_and_poll_once(client):
    code = start(client)
    row = db.get_db().execute("SELECT * FROM connect_codes").fetchone()
    assert row["device_hash"] == lists.hash_token(code["device_token"])
    assert code["device_token"] not in str(dict(row))
    assert poll(client, code).json() == {"status": "pending"}
    lid = create(client, code)
    with db.transaction() as conn:
        lists.set_app_in(conn, lid, "sites", False)
    assert "sites" not in lists.apps_on(lid)
    assert client.post(f"/api/app/connect/{code['user_code']}").status_code == 200
    assert "sites" in lists.apps_on(lid)
    rotated = lists.rotate_agent(lid)
    result = poll(client, code)
    assert result.json() == {"status": "approved", "agent_url": f"http://testserver/link/{rotated}"}
    assert result.headers["cache-control"] == "no-store"
    assert poll(client, code).status_code == 404
    assert approve(client, code).status_code == 404


def test_existing_account_requires_terminal_code_and_browser_guards(client):
    code = start(client)
    client.post("/api/lists", json={})
    lid = client.get("/api/app/session").json()["list_id"]
    assert approve(client, code).status_code == 409  # missing X-List
    client.headers["X-List"] = str(lid)
    assert approve(client, code).status_code == 400
    assert approve(client, code, typed_code="WRNG-2345").status_code == 400
    cross = client.post(
        f"/api/app/connect/{code['user_code']}",
        json={"typed_code": code["user_code"]},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert cross.status_code == 403
    assert poll(client, code).json() == {"status": "pending"}
    # Typed as people type it: lowercase, no hyphen.
    assert approve(client, code, typed_code=code["user_code"].lower().replace("-", " ")).status_code == 200
    assert approve(client, code, typed_code=code["user_code"]).status_code == 404
    assert poll(client, code).json()["status"] == "approved"


def test_other_creation_code_does_not_allow_one_click(client):
    first, second = start(client), start(client)
    create(client, first)
    assert approve(client, second).status_code == 400
    assert approve(client, second, typed_code=second["user_code"]).status_code == 200


def test_wrong_poll_and_valid_poll_with_exhausted_miss_bucket(client, monkeypatch):
    code = start(client)
    wrong = poll(client, {"device_token": "wrong"})
    assert wrong.status_code == 404 and "www-authenticate" not in wrong.headers
    assert wrong.headers["cache-control"] == "no-store"
    assert (
        client.post(
            "/api/connect/poll",
            content=json.dumps({"device_token": "\ud800"}),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 404
    )
    assert poll(client, {"device_token": "a" * 43}).status_code == 404
    assert poll(client, {"device_token": "a" * 129}).status_code == 404
    monkeypatch.setattr(ratelimit.bad_token_limiter, "allow", lambda _: False)
    assert poll(client, {"device_token": "wrong"}).status_code == 429
    assert poll(client, code).json() == {"status": "pending"}
    assert client.get("/api/connect/poll", params={"device_token": code["device_token"]}).status_code == 405
    assert client.post("/api/connect/poll", params={"device_token": code["device_token"]}).status_code == 422


@pytest.mark.parametrize("approved", [False, True])
def test_expiry_and_daily_sweep(client, freeze, approved):
    freeze("2026-11-15T12:00:00Z")
    code = start(client)
    if approved:
        create(client, code)
        assert approve(client, code).status_code == 200
    freeze("2026-11-15T12:15:00Z")
    assert poll(client, code).status_code == 404
    if approved:
        assert approve(client, code).status_code == 404
    else:
        assert client.post("/api/lists", json={"connect": code["user_code"]}).status_code == 404
        assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0
    main._expire()
    assert db.get_db().execute("SELECT COUNT(*) FROM connect_codes").fetchone()[0] == 0


def test_start_rate_limit(client):
    for _ in range(10):
        start(client)
    response = client.post("/api/connect")
    assert response.status_code == 429 and response.headers["retry-after"] == "3600"


@pytest.mark.parametrize("approved", [False, True])
def test_disabled_list_is_a_miss(client, approved):
    code = start(client)
    lid = create(client, code)
    if approved:
        assert approve(client, code).status_code == 200
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET disabled_at = ? WHERE id = ?", (common.now_iso(), lid))
    response = poll(client, code)
    assert response.status_code == 404 and "www-authenticate" not in response.headers


def test_removed_account_is_a_miss(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("RESEND_API_KEY", "test")
    monkeypatch.setenv("MAIL_FROM", "test@example.com")
    code = start(client)
    lid = create(client, code)
    assert approve(client, code).status_code == 200
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET created_at = '2000-01-01T00:00:00.000Z', last_used_at = NULL WHERE id = ?", (lid,)
        )
    assert poll(client, code).status_code == 404


def test_two_polls_cannot_deliver_twice(client):
    code = start(client)
    create(client, code)
    assert approve(client, code).status_code == 200

    def collect():
        try:
            return connect.poll(code["device_token"])
        finally:
            db.close_db()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: collect(), range(2)))
    assert sum(result is not None for result in results) == 1


@pytest.mark.parametrize("operation", ["cleanup", "admin"])
def test_delete_removes_codes_by_either_list_column(client, operation):
    approved, created, keep = start(client), start(client), start(client)
    lid = create(client, created)
    assert approve(client, approved, typed_code=approved["user_code"]).status_code == 200
    with db.transaction() as conn:
        conn.execute("UPDATE lists SET created_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (lid,))
    if operation == "cleanup":
        assert cleanup.delete_unused_lists() == 1
    else:
        assert admin.main(["delete", str(lid), "--no-snapshot", f"--yes-delete-list-{lid}"]) == 0
    assert poll(client, approved).status_code == 404
    assert poll(client, created).status_code == 404
    assert poll(client, keep).json() == {"status": "pending"}


def test_a_code_cannot_create_two_accounts(client):
    code = start(client)
    lid = create(client, code)
    client.cookies.clear()
    assert client.post("/api/lists", json={"connect": code["user_code"]}).status_code == 400
    assert db.get_db().execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
    assert db.get_db().execute("SELECT created_list_id FROM connect_codes").fetchone()[0] == lid


def test_connection_codes_never_reach_a_log():
    from backend import logscrub

    for line in (
        '"GET /connect?code=ABCD-2345 HTTP/1.1" 200',
        '"POST /api/app/connect/ABCD-2345 HTTP/1.1" 200',
        "https://sites.example/connect?x=1&code=ABCD-2345",
    ):
        assert "ABCD-2345" not in logscrub.scrub(line)
