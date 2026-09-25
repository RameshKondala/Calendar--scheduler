"""Microsoft Graph implementation of the Outlook calendar gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

import requests

from app.errors.handlers import OutlookUnavailableError, SlotConflictError
from app.gateways.outlook import (
    FreeBusyWindow,
    OutlookEvent,
    OutlookGateway,
)


class GraphOutlookGateway(OutlookGateway):
    """Microsoft Graph gateway using a delegated access token."""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        *,
        calendar_id: str,
        access_token_provider: Callable[[], str],
        timeout_seconds: float = 8,
    ) -> None:
        self.calendar_id = calendar_id
        self.access_token_provider = access_token_provider
        self.timeout_seconds = timeout_seconds

    @property
    def _calendar_path(self) -> str:
        encoded_id = quote(self.calendar_id, safe="")
        return f"/me/calendars/{encoded_id}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        allow_not_found: bool = False,
    ) -> requests.Response:
        """Send an authenticated Microsoft Graph request."""

        try:
            access_token = self.access_token_provider()

            if not isinstance(access_token, str) or not access_token.strip():
                raise ValueError("Missing Microsoft Graph access token")

            response = requests.request(
                method=method,
                url=f"{self.GRAPH_BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Prefer": 'outlook.timezone="UTC"',
                },
                params=params,
                json=json,
                timeout=self.timeout_seconds,
            )

            if allow_not_found and response.status_code == 404:
                return response

            response.raise_for_status()
            return response

        except (requests.RequestException, ValueError, TypeError) as exc:
            raise OutlookUnavailableError() from exc

    @staticmethod
    def _validate_window(start: datetime, end: datetime) -> None:
        """Require valid timezone-aware appointment boundaries."""

        if (
            not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is None
            or end.tzinfo is None
            or start.utcoffset() is None
            or end.utcoffset() is None
            or start >= end
        ):
            raise OutlookUnavailableError()

    @staticmethod
    def _parse_datetime(value: dict) -> datetime:
        """Parse a Graph dateTimeTimeZone value safely."""

        if not isinstance(value, dict):
            raise ValueError("Invalid Outlook datetime")

        raw = value["dateTime"]

        if not isinstance(raw, str):
            raise ValueError("Invalid Outlook datetime")

        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))

        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)

        # The request explicitly asks Graph to return UTC.
        # Never guess another timezone for an offset-free value.
        if value.get("timeZone", "UTC").upper() != "UTC":
            raise ValueError("Unexpected Outlook timezone")

        return parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _graph_datetime(value: datetime) -> dict:
        """Format an aware datetime for a Graph event payload."""

        utc_value = value.astimezone(timezone.utc)

        return {
            "dateTime": utc_value.replace(tzinfo=None).isoformat(),
            "timeZone": "UTC",
        }

    @classmethod
    def _parse_event(cls, item: dict) -> OutlookEvent:
        """Convert a Graph event into the application's event model."""

        if not isinstance(item, dict):
            raise ValueError("Invalid Outlook event")

        event_id = item["id"]
        subject = item["subject"]
        categories = item.get("categories") or []

        if not isinstance(event_id, str) or not event_id:
            raise ValueError("Missing Outlook event ID")

        if not isinstance(subject, str):
            raise ValueError("Invalid Outlook subject")

        if not isinstance(categories, list) or not all(
            isinstance(category, str) for category in categories
        ):
            raise ValueError("Invalid Outlook categories")

        start = cls._parse_datetime(item["start"])
        end = cls._parse_datetime(item["end"])

        if start >= end:
            raise ValueError("Invalid Outlook event duration")

        body_data = item.get("body")
        body = None

        if body_data is not None:
            if not isinstance(body_data, dict):
                raise ValueError("Invalid Outlook event body")

            body = body_data.get("content")

            if body is not None and not isinstance(body, str):
                raise ValueError("Invalid Outlook event body")

        return OutlookEvent(
            event_id=event_id,
            subject=subject,
            start=start,
            end=end,
            categories=categories,
            body=body,
        )

    @staticmethod
    def _read_event_page(response: requests.Response) -> list[dict]:
        """Read one complete Graph page or fail safely."""

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("Invalid Outlook response")

        if not isinstance(data.get("value"), list):
            raise ValueError("Missing Outlook event list")

        # Never silently treat a partial calendar as complete.
        if data.get("@odata.nextLink"):
            raise ValueError("Additional Outlook pages require retrieval")

        return data["value"]

    def get_schedule(
        self,
        window_start: datetime,
        window_end: datetime,
    ) -> list[FreeBusyWindow]:
        """Return busy Outlook windows overlapping the requested range."""

        self._validate_window(window_start, window_end)

        try:
            response = self._request(
                "GET",
                f"{self._calendar_path}/calendarView",
                params={
                    "startDateTime": window_start.isoformat(),
                    "endDateTime": window_end.isoformat(),
                    "$select": "start,end,showAs",
                },
            )

            items = self._read_event_page(response)
            busy_windows = []

            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Invalid Outlook event")

                if item.get("showAs") == "free":
                    continue

                start = self._parse_datetime(item["start"])
                end = self._parse_datetime(item["end"])

                if start >= end:
                    raise ValueError("Invalid Outlook event duration")

                busy_windows.append(
                    FreeBusyWindow(
                        start=start,
                        end=end,
                        is_free=False,
                    )
                )

            return busy_windows

        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            requests.RequestException,
        ) as exc:
            raise OutlookUnavailableError() from exc

    def create_event(
        self,
        *,
        subject: str,
        start: datetime,
        end: datetime,
        body: str | None,
        categories: list[str] | None = None,
    ) -> OutlookEvent:
        """Recheck availability and create an Outlook appointment."""

        self._validate_window(start, end)

        if not isinstance(subject, str) or not subject.strip():
            raise OutlookUnavailableError()

        if body is not None and not isinstance(body, str):
            raise OutlookUnavailableError()

        if categories is not None and (
            not isinstance(categories, list)
            or not all(isinstance(item, str) for item in categories)
        ):
            raise OutlookUnavailableError()

        busy_windows = self.get_schedule(start, end)

        for window in busy_windows:
            if window.start < end and window.end > start:
                raise SlotConflictError()

        payload = {
            "subject": subject,
            "start": self._graph_datetime(start),
            "end": self._graph_datetime(end),
            "body": {
                "contentType": "text",
                "content": body or "",
            },
            "categories": categories or [],
            "showAs": "busy",
        }

        response = self._request(
            "POST",
            f"{self._calendar_path}/events",
            json=payload,
        )

        try:
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError("Invalid Outlook creation response")

            event_id = data["id"]

            if not isinstance(event_id, str) or not event_id:
                raise ValueError("Missing Outlook event ID")

            return OutlookEvent(
                event_id=event_id,
                subject=subject,
                start=start,
                end=end,
                categories=categories or [],
                body=body,
            )

        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            requests.RequestException,
        ) as exc:
            raise OutlookUnavailableError() from exc

    def list_events(
        self,
        window_start: datetime,
        window_end: datetime,
        categories: list[str] | None = None,
    ) -> list[OutlookEvent]:
        """Retrieve Outlook events, optionally filtering by category."""

        self._validate_window(window_start, window_end)

        if categories is not None and (
            not isinstance(categories, list)
            or not all(isinstance(item, str) for item in categories)
        ):
            raise OutlookUnavailableError()

        try:
            response = self._request(
                "GET",
                f"{self._calendar_path}/calendarView",
                params={
                    "startDateTime": window_start.isoformat(),
                    "endDateTime": window_end.isoformat(),
                    "$select": "id,subject,start,end,categories,body",
                },
            )

            items = self._read_event_page(response)
            events = []

            for item in items:
                event = self._parse_event(item)

                if categories and not any(
                    category in event.categories for category in categories
                ):
                    continue

                events.append(event)

            return events

        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            requests.RequestException,
        ) as exc:
            raise OutlookUnavailableError() from exc

    def get_event(self, event_id: str) -> OutlookEvent | None:
        """Retrieve one Outlook event; return None if it does not exist."""

        if not isinstance(event_id, str) or not event_id.strip():
            raise OutlookUnavailableError()

        encoded_id = quote(event_id, safe="")

        response = self._request(
            "GET",
            f"{self._calendar_path}/events/{encoded_id}",
            params={
                "$select": "id,subject,start,end,categories,body",
            },
            allow_not_found=True,
        )

        if response.status_code == 404:
            return None

        try:
            return self._parse_event(response.json())

        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            requests.RequestException,
        ) as exc:
            raise OutlookUnavailableError() from exc

    def create_block(
        self,
        *,
        start: datetime,
        end: datetime,
        reason: str | None,
    ) -> OutlookEvent:
        """Create a busy Outlook event for owner unavailability."""

        if reason is not None and not isinstance(reason, str):
            raise OutlookUnavailableError()

        return self.create_event(
            subject="Owner unavailable",
            start=start,
            end=end,
            body=reason,
            categories=["owner_block"],
        )