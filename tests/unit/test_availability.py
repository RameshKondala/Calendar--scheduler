from datetime import date, datetime, time

import pytest

from app.config_store.appointment_types import AppointmentTypeStore
from app.config_store.business_hours import BusinessHours
from app.gateways.outlook import FakeOutlookGateway
from app.services.availability import AvailabilityService
from app.services.business_rules import BusinessRulesService


@pytest.fixture
def setup():
    type_store = AppointmentTypeStore()
    business_rules = BusinessRulesService(type_store, BusinessHours())
    gateway = FakeOutlookGateway()
    availability = AvailabilityService(gateway, business_rules)
    appointment_type = type_store.get_by_code("initial_fitting")
    return availability, business_rules, gateway, appointment_type


def test_find_options_returns_free_slots(setup):
    availability, business_rules, gateway, appointment_type = setup
    monday = date(2026, 9, 21)
    windows = business_rules.build_candidate_windows(monday, monday, time(9, 0), time(11, 0))

    options = availability.find_options(appointment_type, windows, max_options=3)

    assert len(options) > 0
    assert options[0].start.startswith("2026-09-21T09:00")


def test_find_options_skips_busy_slots(setup):
    availability, business_rules, gateway, appointment_type = setup
    monday = date(2026, 9, 21)
    gateway.seed_busy(datetime(2026, 9, 21, 9, 0), datetime(2026, 9, 21, 9, 45))

    windows = business_rules.build_candidate_windows(monday, monday, time(9, 0), time(11, 0))
    options = availability.find_options(appointment_type, windows, max_options=3)

    assert all(not o.start.startswith("2026-09-21T09:00:00") for o in options)


def test_find_options_respects_max_options(setup):
    availability, business_rules, gateway, appointment_type = setup
    monday = date(2026, 9, 21)
    windows = business_rules.build_candidate_windows(monday, monday, time(9, 0), time(18, 0))

    options = availability.find_options(appointment_type, windows, max_options=2)

    assert len(options) == 2


def test_find_options_empty_windows_returns_empty(setup):
    availability, _business_rules, _gateway, appointment_type = setup
    assert availability.find_options(appointment_type, [], max_options=3) == []
