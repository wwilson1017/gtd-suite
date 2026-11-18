"""Pure logic: recurrence math, validators, the per-list clock."""

import datetime

import pytest

from backend import common
from backend.common import ValidationError, next_due

TODAY = datetime.date(2026, 8, 7)  # a Friday


def _future(days: int) -> datetime.date:
    return TODAY + datetime.timedelta(days=days)


# ── next_due ──────────────────────────────────────────────────────────────────


def test_next_due_advances_from_the_old_due_date():
    base = _future(10)
    assert next_due("weekly", base.isoformat(), TODAY) == (base + datetime.timedelta(days=7)).isoformat()
    assert next_due("daily", base.isoformat(), TODAY) == (base + datetime.timedelta(days=1)).isoformat()
    assert next_due("every:3", base.isoformat(), TODAY) == (base + datetime.timedelta(days=3)).isoformat()


def test_next_due_reanchors_to_today_when_advanced_date_is_past():
    # Completing years late must not spawn an already-overdue copy.
    assert next_due("weekly", "2020-01-06", TODAY) == _future(7).isoformat()
    assert next_due("daily", "2020-01-01", TODAY) == _future(1).isoformat()


def test_next_due_advances_from_due_date_not_today():
    # One day late: advancing from the due date gives today — NOT tomorrow,
    # which clamping the base to today first would produce, skipping a day.
    assert next_due("daily", _future(-1).isoformat(), TODAY) == TODAY.isoformat()
    # Weekly overdue by 3 days keeps its anchor: due+7, not today+7.
    assert next_due("weekly", _future(-3).isoformat(), TODAY) == _future(4).isoformat()


def test_next_due_weekdays_skips_weekends():
    assert TODAY.weekday() == 4
    assert next_due("weekdays", TODAY.isoformat(), TODAY) == "2026-08-10"  # Monday


def test_next_due_monthly_clamps_month_end():
    assert next_due("monthly", "2030-01-31", TODAY) == "2030-02-28"
    assert next_due("monthly", "2030-03-31", TODAY) == "2030-04-30"
    assert next_due("monthly", "2099-12-15", TODAY) == "2100-01-15"  # year rollover


def test_next_due_yearly_clamps_feb_29():
    assert next_due("yearly", "2032-02-29", TODAY) == "2033-02-28"


def test_next_due_with_no_prior_due_date_anchors_on_today():
    assert next_due("weekly", None, TODAY) == _future(7).isoformat()
    assert next_due("daily", "not-a-date", TODAY) == _future(1).isoformat()


def test_next_due_accepts_a_raw_date_object():
    base = _future(10)
    assert next_due("daily", base, TODAY) == (base + datetime.timedelta(days=1)).isoformat()


def test_next_due_invalid_repeat_raises():
    # Empty/unknown values must never silently fall through to yearly math.
    for bad in ("", "bogus"):
        with pytest.raises(ValidationError, match="Invalid repeat"):
            next_due(bad, "2099-01-01", TODAY)


# ── validators ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", ""),
        ("none", ""),
        ("None", ""),
        (None, ""),
        ("DAILY", "daily"),
        ("weekdays", "weekdays"),
        ("every:14", "every:14"),
    ],
)
def test_validate_repeat_accepts(value, expected):
    assert common.validate_repeat(value) == expected


@pytest.mark.parametrize("value", ["hourly", "every:0", "every:10000", "every:", "weekly-ish"])
def test_validate_repeat_rejects(value):
    with pytest.raises(ValidationError):
        common.validate_repeat(value)


def test_validate_due_accepts_real_dates_and_none():
    assert common.validate_due("2026-08-15") == "2026-08-15"
    assert common.validate_due(None) is None
    assert common.validate_due("") is None


@pytest.mark.parametrize(
    "value",
    [
        "tomorrow",
        "08/15/2026",
        "2026-8-5",  # wrong shape
        "2026-13-01",
        "2026-02-30",
        "2026-00-10",  # right shape, impossible date
    ],
)
def test_validate_due_rejects(value):
    with pytest.raises(ValidationError):
        common.validate_due(value)


def test_validate_tags():
    assert common.validate_tags(["  home ", "", "energy:low"]) == ["home", "energy:low"]
    assert common.validate_tags(None) == []
    with pytest.raises(ValidationError, match="list of strings"):
        common.validate_tags("home")
    with pytest.raises(ValidationError, match="too many tags"):
        common.validate_tags([str(i) for i in range(51)])
    with pytest.raises(ValidationError, match="tag too long"):
        common.validate_tags(["x" * 501])


def test_validate_people_shares_the_tag_rules_and_names_its_own_field():
    assert common.validate_people(["  Ana ", "", "Bo"]) == ["Ana", "Bo"]
    assert common.validate_people(None) == []
    with pytest.raises(ValidationError, match="people must be a list of strings"):
        common.validate_people("Ana")
    with pytest.raises(ValidationError, match="too many people"):
        common.validate_people([str(i) for i in range(51)])
    with pytest.raises(ValidationError, match="person too long"):
        common.validate_people(["x" * 501])


def test_tickle_cutoff_is_local_midnight_four_days_back(monkeypatch):
    instant = datetime.datetime(2026, 8, 8, 1, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(common, "utcnow", lambda: instant)
    # Aug 7 in Chicago: resting covers Aug 3–7, so the cutoff is Aug 3 00:00 CDT.
    assert common.tickle_cutoff("America/Chicago") == "2026-08-03T05:00:00.000Z"
    # Aug 8 in Auckland: Aug 4 00:00 NZST.
    assert common.tickle_cutoff("Pacific/Auckland") == "2026-08-03T12:00:00.000Z"
    assert common.tickle_cutoff("Mars/Olympus") == "2026-08-04T00:00:00.000Z"  # falls back to UTC


def test_validate_short_and_notes_caps():
    with pytest.raises(ValidationError, match="context too long"):
        common.validate_short("x" * 501, "context")
    with pytest.raises(ValidationError, match="notes too long"):
        common.validate_notes("x" * 20_001)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("  Me@Example.COM ", "me@example.com"),
        ("", None),
        (None, None),
    ],
)
def test_validate_email_accepts(value, expected):
    assert common.validate_email(value) == expected


@pytest.mark.parametrize("value", ["nope", "a@b", "a b@c.com", "a@@b.com", "x" * 250 + "@b.com"])
def test_validate_email_rejects(value):
    with pytest.raises(ValidationError):
        common.validate_email(value)


def test_source_client_is_truncated_not_rejected():
    assert common.clean_source_client("  Claude  ") == "Claude"
    assert common.clean_source_client("x" * 500) == "x" * 100
    assert common.clean_source_client("") is None
    assert common.clean_source_client(None) is None


# ── time zones ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "Not/AZone",
        "",
        None,
        42,
        "../../etc/passwd",
        "America",
        "x" * 100,
    ],
)
def test_validate_tz_falls_back_to_utc(value):
    assert common.validate_tz(value) == "UTC"


def test_validate_tz_accepts_real_zones():
    assert common.validate_tz("America/Chicago") == "America/Chicago"
    assert common.validate_tz("Pacific/Auckland") == "Pacific/Auckland"


def test_business_today_is_the_zone_date_not_utc(freeze):
    freeze("2026-08-08T01:00:00")  # 8pm Aug 7 in Chicago, 1pm Aug 8 in Auckland
    assert common.business_today("UTC") == datetime.date(2026, 8, 8)
    assert common.business_today("America/Chicago") == datetime.date(2026, 8, 7)
    assert common.business_today("Pacific/Auckland") == datetime.date(2026, 8, 8)
    assert common.business_today("Not/AZone") == datetime.date(2026, 8, 8)


def test_business_today_follows_dst(freeze):
    # 05:30 UTC is 00:30 in Chicago on daylight time (UTC-5) but 23:30 the day
    # before on standard time (UTC-6). US clocks fall back on 2026-11-01.
    freeze("2026-10-31T05:30:00")
    assert common.business_today("America/Chicago") == datetime.date(2026, 10, 31)
    freeze("2026-11-02T05:30:00")
    assert common.business_today("America/Chicago") == datetime.date(2026, 11, 1)


def test_now_iso_shape(freeze):
    freeze("2026-08-08T01:02:03.456789")
    assert common.now_iso() == "2026-08-08T01:02:03.456Z"
