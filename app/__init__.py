"""Flask application factory (section 6.4, Dependency Injection).

Services and gateways are constructed once here and stashed on
``app.extensions`` rather than as module-level globals, so tests can build
a fresh app with different fakes and nothing leaks mutable state between
app instances.
"""
from __future__ import annotations

import logging

from flask import Flask

from app.config_store.appointment_types import AppointmentTypeStore
from app.config_store.business_hours import BusinessHours
from app.errors.handlers import register_error_handlers
from app.gateways.openai_intent import OpenAIIntentAdapter
from app.gateways.outlook import FakeOutlookGateway, OutlookGateway
from app.routes.booking import booking_bp
from app.routes.health import health_bp
from app.routes.owner import owner_bp
from app.services.availability import AvailabilityService
from app.services.business_rules import BusinessRulesService
from app.services.intent import FakeIntentInterpreter, IntentService, OpenAIIntentInterpreter
from app.services.scheduling import SchedulingOrchestrator


def _build_outlook_gateway(app: Flask) -> OutlookGateway:
    """Select the Outlook gateway implementation.

    "fake" (default) is safe for local dev/CI. "graph" is a placeholder for
    Jose's real Microsoft Graph implementation -- once it exists it should
    be imported and returned here instead of raising, without any route or
    service code needing to change.
    """
    gateway_choice = app.config["OUTLOOK_GATEWAY"]
    if gateway_choice == "fake":
        return FakeOutlookGateway()
    raise RuntimeError(
        f"Outlook gateway '{gateway_choice}' is not yet implemented. "
        "This is the integration point for Jose's Microsoft Graph gateway."
    )


def _build_intent_service(app: Flask, appointment_type_store: AppointmentTypeStore) -> IntentService:
    if app.config.get("OPENAI_API_KEY"):
        adapter = OpenAIIntentAdapter(
            api_key=app.config["OPENAI_API_KEY"],
            model=app.config["OPENAI_MODEL"],
            timeout_seconds=app.config["AI_TIMEOUT_SECONDS"],
        )
        interpreter = OpenAIIntentInterpreter(adapter)
    else:
        interpreter = FakeIntentInterpreter(appointment_type_store)
    return IntentService(interpreter)


def create_app(config_object=None, outlook_gateway: OutlookGateway | None = None) -> Flask:
    """Application factory.

    ``outlook_gateway`` can be injected directly (e.g. by tests), bypassing
    the config-driven selection in ``_build_outlook_gateway``.
    """
    app = Flask(__name__)

    if config_object is None:
        from config import get_config

        config_object = get_config()
    app.config.from_object(config_object)

    logging.basicConfig(level=logging.INFO)

    appointment_type_store = AppointmentTypeStore()
    business_hours = BusinessHours(timezone=app.config["BUSINESS_TIMEZONE"])
    gateway = outlook_gateway or _build_outlook_gateway(app)

    business_rules_service = BusinessRulesService(appointment_type_store, business_hours)
    availability_service = AvailabilityService(gateway, business_rules_service)
    intent_service = _build_intent_service(app, appointment_type_store)

    orchestrator = SchedulingOrchestrator(
        intent_service=intent_service,
        business_rules=business_rules_service,
        availability_service=availability_service,
        outlook_gateway=gateway,
    )

    app.extensions["appointment_type_store"] = appointment_type_store
    app.extensions["outlook_gateway"] = gateway
    app.extensions["scheduling_orchestrator"] = orchestrator

    app.register_blueprint(health_bp, url_prefix="/api/v1")
    app.register_blueprint(booking_bp, url_prefix="/api/v1")
    app.register_blueprint(owner_bp, url_prefix="/api/v1")

    register_error_handlers(app)

    return app
