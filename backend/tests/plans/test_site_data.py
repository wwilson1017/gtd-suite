"""Level cases moved from test_site_data.py."""

import pytest
from backend import common
from backend.tests.conftest import confirm_list as confirm_list
from backend.tests import test_mcp as test_mcp, test_sites as test_sites


@pytest.mark.parametrize(
    "verified,hosted,tier,expected",
    [
        (False, False, None, (2_000_000_000, 100_000)),
        (False, False, "pro", (2_000_000_000, 100_000)),
        (False, True, "max", (2_000_000_000, 100_000)),
        (False, True, "pro", (500_000_000, 20_000)),
        (True, True, None, (10_000_000, 2_000)),
        (False, True, None, (0, 0)),
    ],
)
def test_caps(verified, hosted, tier, expected):
    assert common.site_data_caps_for(verified, hosted, tier) == expected
