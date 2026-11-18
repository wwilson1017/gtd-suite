"""Plan cases moved from test_admin.py."""

import json
import re
import sqlite3
import pytest
from backend import db, lists, sites
from backend.tests.test_mcp import INIT as INIT, MCP_HEADERS as MCP_HEADERS
from backend.tests.test_admin import _log as _log, made as made, run as run


def test_an_older_database_gains_account_numbers_and_comp_plan(todo_db):
    first, second = lists.create_list()["list_id"], lists.create_list()["list_id"]
    conn = db.get_db()
    conn.execute("DROP INDEX idx_lists_account_no")
    conn.execute("ALTER TABLE lists DROP COLUMN account_no")
    conn.execute("ALTER TABLE lists DROP COLUMN comp_plan")
    db.init_db()
    number = lists.get_list(first)["account_no"]
    assert re.fullmatch(r"[1-9]\d{3}-\d{4}", number) and number != lists.get_list(second)["account_no"]
    assert lists.get_list(first)["comp_plan"] == "pro"
    db.init_db()  # and again: a number, once given, stays
    assert lists.get_list(first)["account_no"] == number
    with pytest.raises(sqlite3.IntegrityError):
        db.get_db().execute("UPDATE lists SET account_no = ? WHERE id = ?", (number, second))


def test_comp_plan_max_shows_in_show_stats_and_the_session(new_list, run):
    made = new_list()
    lid, client = made["list_id"], made["client"]
    number = lists.get_list(lid)["account_no"]
    trial = sites.publish(lid, "Trial")
    assert trial["expires_at"] is not None
    code, out = run("comp", number, "--plan", "max", "--until", "2099-01-01")
    assert code == 0 and "on Max for free until 2099-01-01" in out
    assert sites.get_site(lid, trial["id"])["expires_at"] is None  # the grant keeps the trial page
    assert _log() == [("comp", lid)]
    data = json.loads(run("show", lid, "--json")[1])
    assert data["tier"] == "max" and data["pro"] and data["plan"]["comp_plan"] == "max"
    text = run("show", lid)[1]
    assert "Plan: max" in text and "Free Max granted until 2099-01-01" in text
    assert json.loads(run("stats", "--json")[1])["max_now"] == 1
    assert "(1 free, 1 on Max)" in run("stats")[1]
    plan = client.get("/api/app/session").json()["plan"]
    assert plan["tier"] == "max" and plan["pro"] and plan["source"] == "comp"
    assert "on Pro for free for good" in run("comp", number.replace("-", ""))[1]  # plain comp grants Pro
    assert json.loads(run("show", lid, "--json")[1])["tier"] == "pro"
    assert run("comp", lid, "--off")[0] == 0
    assert json.loads(run("show", lid, "--json")[1])["tier"] is None
