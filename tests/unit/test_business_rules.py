from datetime import date, datetime, time, timezone

import pytest

from app.config_store.appointment_types import AppointmentTypeStore
from app.config_store.business_hours import BusinessHours
from app.errors.handlers import ValidationError
from app.services.business_rules import BusinessRulesService


@pytest.fixture
def business_rules():
    return BusinessRulesService(AppointmentTypeStore(), BusinessHours())


def test_get_active_appointment_type_by_code(business_rules):
    appointment_type = business_rules.get_active_appointment_type("initial_fitting")
    assert appointment_type.code == "initial_fitting"
    assert appointment_type.duration_minutes == 45


def test_get_active_appointment_type_unknown_code_raises(business_rules):
    with pytest.raises(ValidationError):
        business_rules.get_active_appointment_type("does_not_exist")


def test_get_active_appointment_type_inactive_raises(business_rules):
    store = AppointmentTypeStore()
    store.update(1, active=False)
    rules = BusinessRulesService(store, BusinessHours())
    with pytest.raises(ValidationError):
        rules.get_active_appointment_type("initial_fitting")


def test_build_candidate_windows_skips_closed_days(business_rules):
    # 2026-09-19 is a Saturday (business is open Mon-Sat by default, so use Sunday).
    sunday = date(2026, 9, 20)
    windows = business_rules.build_candidate_windows(sunday, sunday, None, None)
    assert windows == []


def test_build_candidate_windows_clamps_to_business_hours(business_rules):
    monday = date(2026, 9, 21)
    windows = business_rules.build_candidate_windows(monday, monday, time(7, 0), time(20, 0))
    assert len(windows) == 1
    assert windows[0].window_start == time(9, 0)
    assert windows[0].window_end == time(18, 0)


def test_build_candidate_windows_rejects_end_before_start(business_rules):
    with pytest.raises(ValidationError):
        business_rules.build_candidate_windows(date(2026, 9, 22), date(2026, 9, 21), None, None)


def test_build_candidate_windows_rejects_overly_wide_range(business_rules):
    with pytest.raises(ValidationError):
        business_rules.build_candidate_windows(date(2026, 1, 1), date(2026, 3, 1), None, None)


def test_to_business_time_treats_naive_input_as_business_local(business_rules):
    result = business_rules.to_business_time(datetime(2026, 9, 29, 9, 0))
    assert result.isoformat() == "2026-09-29T09:00:00-05:00"


def test_to_business_time_converts_aware_input_to_the_same_instant(business_rules):
    utc_moment = datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc)
    result = business_rules.to_business_time(utc_moment)
    assert result.isoformat() == "2026-09-29T09:00:00-05:00"
    assert result == utc_moment


def test_to_business_time_follows_daylight_saving_offsets(business_rules):
    winter = business_rules.to_business_time(datetime(2026, 12, 15, 9, 0))
    assert winter.isoformat() == "2026-12-15T09:00:00-06:00"


def test_ensure_within_business_hours_accepts_a_valid_slot(business_rules):
    appointment_type = business_rules.get_active_appointment_type("initial_fitting")
    start = business_rules.to_business_time(datetime(2026, 9, 21, 9, 0))  # Monday, within hours
    business_rules.ensure_within_business_hours(appointment_type, start)  # does not raise


def test_ensure_within_business_hours_rejects_closed_day(business_rules):
    appointment_type = business_rules.get_active_appointment_type("initial_fitting")
    start = business_rules.to_business_time(datetime(2026, 9, 20, 9, 0))  # Sunday
    with pytest.raises(ValidationError):
        business_rules.ensure_within_business_hours(appointment_type, start)


def test_ensure_within_business_hours_rejects_before_opening(business_rules):
    appointment_type = business_rules.get_active_appointment_type("initial_fitting")
    start = business_rules.to_business_time(datetime(2026, 9, 21, 7, 0))  # before 9am
    with pytest.raises(ValidationError):
        business_rules.ensure_within_business_hours(appointment_type, start)


def test_ensure_within_business_hours_rejects_when_duration_runs_past_closing(business_rules):
    appointment_type = business_rules.get_active_appointment_type("initial_fitting")
    start = business_rules.to_business_time(datetime(2026, 9, 21, 17, 45))  # 45-min type, closes at 18:00
    with pytest.raises(ValidationError):
        business_rules.ensure_within_business_hours(appointment_type, start)


def test_ensure_within_business_hours_accepts_slot_ending_exactly_at_closing(business_rules):
    appointment_type = business_rules.get_active_appointment_type("pickup")  # 15 min
    start = business_rules.to_business_time(datetime(2026, 9, 21, 17, 45))
    business_rules.ensure_within_business_hours(appointment_type, start)  # does not raise
