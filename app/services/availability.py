"""Availability service: turns business-rule candidate windows into concrete
slot proposals by checking Outlook free/busy (section 3.5, section 7.1).

Slots returned here are proposals, never reservations -- the selected slot
is rechecked immediately before event creation in the orchestrator.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.config_store.appointment_types import AppointmentType
from app.gateways.outlook import OutlookGateway
from app.models.schemas import SlotOption
from app.services.business_rules import BusinessRulesService, CandidateWindow


class AvailabilityService:
    def __init__(self, outlook_gateway: OutlookGateway, business_rules: BusinessRulesService) -> None:
        self._outlook_gateway = outlook_gateway
        self._business_rules = business_rules

    def find_options(
        self,
        appointment_type: AppointmentType,
        windows: list[CandidateWindow],
        max_options: int = 3,
        tz=None,
    ) -> list[SlotOption]:
        if not windows:
            return []

        overall_start = datetime.combine(windows[0].date, windows[0].window_start, tzinfo=tz)
        overall_end = datetime.combine(windows[-1].date, windows[-1].window_end, tzinfo=tz)

        busy = self._outlook_gateway.get_schedule(overall_start, overall_end)
        slot_length = self._business_rules.appointment_duration(appointment_type)
        step = self._business_rules.slot_duration(appointment_type)

        options: list[SlotOption] = []
        for window in windows:
            cursor = datetime.combine(window.date, window.window_start, tzinfo=tz)
            window_end_dt = datetime.combine(window.date, window.window_end, tzinfo=tz)

            while cursor + slot_length <= window_end_dt:
                candidate_end = cursor + slot_length
                if self._is_free(cursor, candidate_end, busy):
                    options.append(
                        SlotOption(
                            slot_id=cursor.strftime("%Y%m%dT%H%M"),
                            start=cursor.isoformat(),
                            end=candidate_end.isoformat(),
                        )
                    )
                    if len(options) >= max_options:
                        return options
                cursor += step
        return options

    @staticmethod
    def _is_free(start: datetime, end: datetime, busy_windows) -> bool:
        for busy in busy_windows:
            if busy.start < end and busy.end > start:
                return False
        return True
