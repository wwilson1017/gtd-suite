"""Plan cases moved from test_files.py."""

import datetime
import pytest
from backend import brain, common, db, files, lists
from backend.common import ValidationError
from backend.tests.conftest import confirm_list as confirm_list
from backend.tests.test_keys import acct as acct, bearer as bearer, new_key as new_key, rest as rest
from backend.tests.test_mcp import anyio_backend as anyio_backend, app as app, browser as browser, http as http
from backend.tests.test_files import L as L, MB as MB, big as big, item as item, store as store


def test_quota_counts_pending_rows_and_follows_the_tier(store, L, monkeypatch):
    unconfirmed = lists.create_list("UTC")["list_id"]
    with pytest.raises(ValidationError, match="Files need a confirmed email"):
        files.reserve(brain.first_brain(unconfirmed), [item("a.txt", b"a")])
    files.reserve(brain.first_brain(L), [big("a.bin", 300 * MB)])  # pending, never uploaded: still charged
    with pytest.raises(ValidationError, match=r"That needs 250 MB, and 200 MB of the brain's 500 MB"):
        files.reserve(brain.first_brain(L), [big("b.bin", 250 * MB)])
    until = common.to_iso(common.utcnow() + datetime.timedelta(days=30))
    for plan, quota in (("pro", 10_000_000_000), ("max", 100_000_000_000)):
        with db.transaction() as conn:
            conn.execute("UPDATE lists SET pro_comp_until = ?, comp_plan = ? WHERE id = ?", (until, plan, L))
        assert files.overview(brain.first_brain(L))["quota"] == quota
    monkeypatch.setenv("OPEN_SIGNUP", "false")  # a self-hosted server
    assert files.overview(brain.first_brain(unconfirmed))["quota"] == 100_000_000_000


def test_five_gb_in_one_put_and_500_mb_from_the_browser(store, L):
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lists SET pro_comp_until = '2999-01-01T00:00:00.000Z', comp_plan = 'max' WHERE id = ?", (L,)
        )
    files.reserve(brain.first_brain(L), [big("video.mp4", 600 * MB)])
    with pytest.raises(ValidationError, match="at most 500 MB from the browser"):
        files.reserve(brain.first_brain(L), [big("video.mp4", 600 * MB)], browser=True)
    with pytest.raises(ValidationError, match="at most 5 GB"):
        files.reserve(brain.first_brain(L), [big("huge.mp4", 5_000_000_001)])
