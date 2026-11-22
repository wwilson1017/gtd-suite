"""Fresh databases and pre-billing databases get identical plan columns."""

from backend import db, lists
from backend.plans import caps


def test_paid_columns_migrate_with_original_types_defaults_and_names(todo_db):
    conn = db.get_db()
    account = lists.create_list()["list_id"]

    def columns():
        return {row["name"]: tuple(row)[1:] for row in db.get_db().execute("PRAGMA table_info(lists)")}

    fresh = columns()
    assert len(caps.COLUMNS) == 11
    for name in caps.COLUMNS:
        conn.execute(f"ALTER TABLE lists DROP COLUMN {name}")
    db.init_db()
    assert columns() == fresh
    db.init_db()
    assert columns() == fresh
    row = db.get_db().execute("SELECT * FROM lists WHERE id = ?", (account,)).fetchone()
    assert {name: row[name] for name in caps.COLUMNS} == {
        "stripe_customer": "",
        "stripe_email": "",
        "stripe_subscription": "",
        "plan_status": "",
        "plan_until": None,
        "plan_cancels": 0,
        "plan_rev": 0,
        "pro_comp_until": None,
        "comp_plan": "pro",
        "comp_source": "",
        "springform_at": None,
    }
