"""A Springform connect: every app on and, on the hosted service, Max for a confirmed account."""

import contextlib
import io
import json

import pytest

from backend import apps, connect, db, lists
from backend.paid import admin as paid_admin, plans
from backend.paid import caps as paid_caps
from backend.tests.conftest import confirm_list
from backend.tests.test_connect import create, poll, start
from scripts import admin


@pytest.fixture(autouse=True)
def served(client, monkeypatch):
    monkeypatch.setenv("SITES_BASE_URL", "http://testserver")


def approve(browser, code, **body):
    return browser.post(f"/api/app/connect/{code['user_code']}", json=body)


def start_springform(client):
    response = client.post("/api/connect", json={"client": "springform"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200
    result = response.json()
    assert result["url"] == f"http://testserver/connect?code={result['user_code']}&client=springform"
    return result


def plan_row(lid):
    return (
        db.get_db().execute(f"SELECT {paid_caps.PLAN_COLUMNS}, comp_source FROM lists WHERE id = ?", (lid,)).fetchone()
    )


def test_springform_connect_turns_every_app_on_and_grants_max(client):
    code = start_springform(client)
    assert poll(client, code).json() == {"status": "pending"}
    lid = create(client, code)
    assert lists.apps_on(lid) == ["sites"]
    # A Springform code is approved only as one: the page named it, so a Sites page cannot.
    assert approve(client, code).status_code == 400
    # Hosted: Max needs a confirmed email first.
    refused = approve(client, code, client="springform")
    assert refused.status_code == 400 and "confirm it first" in refused.json()["detail"]
    confirm_list(lid)
    assert approve(client, code, client="springform").status_code == 200
    assert lists.apps_on(lid) == list(apps.APPS)
    row = plan_row(lid)
    assert plans.of(row) == "max" and row["comp_source"] == "springform" and row["pro_comp_until"] == paid_admin.FOREVER
    rotated = lists.get_list(lid)["agent_token"]
    assert poll(client, code).json() == {"status": "approved", "agent_url": f"http://testserver/link/{rotated}"}
    assert json.loads(admin_output(["stats", "--json"]))["max_springform"] == 1
    assert "Max from Springform: 1" in admin_output(["stats"])


def admin_output(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert admin.main(argv) in (0, None)
    return out.getvalue()


def test_sites_code_refuses_a_springform_page_and_changes_no_plan(client):
    code = start(client)
    lid = create(client, code)
    confirm_list(lid)
    assert approve(client, code, client="springform").status_code == 400
    assert approve(client, code).status_code == 200
    assert lists.apps_on(lid) == ["sites"]
    assert plans.of(plan_row(lid)) is None


def test_springform_grant_once_and_never_over_a_hand_max(client):
    first = start_springform(client)
    lid = create(client, first)
    confirm_list(lid)
    assert approve(client, first, client="springform").status_code == 200
    # The operator takes it back; approving another Springform code does not give it again.
    assert admin.main(["comp", str(lid), "--off"]) == 0
    second = start_springform(client)
    assert approve(client, second, typed_code=second["user_code"], client="springform").status_code == 200
    assert plans.of(plan_row(lid)) is None
    # Nor does a hand grant in between, which takes the label.
    assert admin.main(["comp", str(lid), "--plan", "pro"]) == 0
    assert plan_row(lid)["comp_source"] == ""
    assert admin.main(["comp", str(lid), "--off"]) == 0
    third = start_springform(client)
    assert approve(client, third, typed_code=third["user_code"], client="springform").status_code == 200
    assert plans.of(plan_row(lid)) is None
    # An account already holding a hand grant of Max keeps it, and its label.
    other = lists.create_list()["list_id"]
    confirm_list(other, "other@example.com")
    assert admin.main(["comp", str(other), "--plan", "max", "--until", "2099-01-01"]) == 0
    fourth = start_springform(client)
    connect.approve(other, fourth["user_code"], fourth["user_code"], "springform")
    row = plan_row(other)
    assert row["comp_source"] == "" and row["pro_comp_until"].startswith("2099-01-01")


def test_springform_start_rate_limit_is_its_own(client):
    for _ in range(5):
        start_springform(client)
    response = client.post("/api/connect", json={"client": "springform"})
    assert response.status_code == 429 and response.headers["retry-after"] == "3600"
    start(client)  # Sites connections keep their own allowance
    assert client.post("/api/connect", json={"client": "other"}).status_code == 422


def test_self_host_springform_turns_apps_on_without_a_grant(client, monkeypatch):
    monkeypatch.setenv("OPEN_SIGNUP", "false")
    code = start_springform(client)
    lid = create(client, code)
    assert approve(client, code, client="springform").status_code == 200
    assert lists.apps_on(lid) == list(apps.APPS)
    row = plan_row(lid)
    assert plans.of(row) is None and row["comp_source"] == ""
