from datetime import date, time

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
