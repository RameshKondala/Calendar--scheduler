"""Frontend page routes (Week 6).

This blueprint exists only to render the two HTML pages. It contains no
business logic, no validation, and no calls to any service/gateway --
everything the pages do happens client-side in JavaScript by calling the
existing ``/api/v1/...`` endpoints. That keeps ``SchedulingOrchestrator``,
``BusinessRulesService``, ``AvailabilityService``, and ``OutlookGateway``
as the sole owners of scheduling behavior, unchanged from Week 5.
"""
from __future__ import annotations

from flask import Blueprint, render_template

frontend_bp = Blueprint("frontend", __name__)


@frontend_bp.get("/")
def customer_page():
    return render_template("index.html")


@frontend_bp.get("/owner")
def owner_page():
    return render_template("owner.html")
