"""Plan cases moved from test_brain.py."""

from backend.paid import caps as paid_caps
from backend import brain, common, db
from backend.tests.conftest import confirm_list as confirm_list, turn_on as turn_on
from backend.tests.test_mcp import (
    anyio_backend as anyio_backend,
    app as app,
    call as call,
    connect as connect,
    http as http,
    link as link,
    made as made,
)
from backend.tests.test_brain import B as B


def test_the_tiers_caps():
    assert common.brain_caps_for(False, True) == (1, 50, 10)
    assert common.brain_caps_for(True, True) == (None, 2_000, 2_000)
    assert common.brain_caps_for(True, True, "pro") == (None, 10_000, 25_000)
    assert common.brain_caps_for(True, True, "max") == paid_caps.BRAIN_MAX_CAPS == common.BRAIN_SELF_HOST_CAPS
    assert common.brain_caps_for(False, False)[1] >= 1_000_000


def test_a_max_account_gets_the_max_caps(B):
    confirm_list(B)
    assert brain._plan(db.get_db(), brain.first_brain(B))["memories"] == 2_000
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '9999-12-31T00:00:00.000Z', comp_plan = 'max' WHERE id = ?", (B,)
        )
    plan = brain._plan(db.get_db(), brain.first_brain(B))
    assert plan["memories"] == plan["pages"] == 1_000_000 and not plan["upsell"]
