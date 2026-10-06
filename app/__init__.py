"""Flask application factory (section 6.4, Dependency Injection)."""

from __future__ import annotations

import logging

from flask import Flask

from app.config_store.appointment_types import AppointmentTypeStore
from app.config_store.business_hours import BusinessHours
from app.errors.handlers import register_error_handlers
from app.gateways.graph_outlook import GraphOutlookGateway
from app.gateways.msal_auth import MsalTokenProvider
from app.gateways.openai_intent import OpenAIIntentAdapter
from app.gateways.outlook import FakeOutlookGateway, OutlookGateway
from app.routes.booking import booking_bp
from app.routes.frontend import frontend_bp
from app.routes.health import health_bp
from app.routes.microsoft_auth import microsoft_auth_bp
from app.routes.owner import owner_bp
from app.services.availability import AvailabilityService
from app.services.business_rules import BusinessRulesService
from app.services.idempotency import IdempotencyStore
from app.services.intent import (
    FakeIntentInterpreter,
    IntentService,
    OpenAIIntentInterpreter,
)
from app.services.rate_limit import RateLimiter
from app.services.scheduling import SchedulingOrchestrator


def _build_outlook_gateway(app: Flask) -> OutlookGateway:
    """Select and configure the Outlook gateway implementation."""

    gateway_choice = app.config["OUTLOOK_GATEWAY"]

    if gateway_choice == "fake":
        return FakeOutlookGateway()

    if gateway_choice == "graph":
        token_store: dict[str, str] = {}

        token_provider = MsalTokenProvider(
            client_id=app.config["MS_GRAPH_CLIENT_ID"],
            client_secret=app.config["MS_GRAPH_CLIENT_SECRET"],
            tenant_id=app.config["MS_GRAPH_TENANT_ID"],
            token_cache=token_store,
        )

        gateway = GraphOutlookGateway(
            calendar_id=app.config["MS_GRAPH_CALENDAR_ID"],
            access_token_provider=token_provider.get_access_token,
            timeout_seconds=app.config["GRAPH_TIMEOUT_SECONDS"],
        )

        app.extensions["msal_token_provider"] = token_provider
        app.extensions["msal_token_store"] = token_store

        return gateway

    raise RuntimeError(
        f"Unsupported Outlook gateway configuration: {gateway_choice}"
    )


def _build_intent_service(
    app: Flask,
    appointment_type_store: AppointmentTypeStore,
) -> IntentService:
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


def create_app(
    config_object=None,
    outlook_gateway: OutlookGateway | None = None,
) -> Flask:
    app = Flask(__name__)

    if config_object is None:
        from config import get_config

        config_object = get_config()

    app.config.from_object(config_object)
    logging.basicConfig(level=logging.INFO)

    appointment_type_store = AppointmentTypeStore()
    business_hours = BusinessHours(
        timezone=app.config["BUSINESS_TIMEZONE"]
    )

    gateway = outlook_gateway or _build_outlook_gateway(app)

    business_rules_service = BusinessRulesService(
        appointment_type_store,
        business_hours,
    )
    availability_service = AvailabilityService(
        gateway,
        business_rules_service,
    )
    intent_service = _build_intent_service(
        app,
        appointment_type_store,
    )

    idempotency_store = IdempotencyStore()

    orchestrator = SchedulingOrchestrator(
        intent_service=intent_service,
        business_rules=business_rules_service,
        availability_service=availability_service,
        outlook_gateway=gateway,
        idempotency_store=idempotency_store,
    )

    app.extensions["appointment_type_store"] = appointment_type_store
    app.extensions["idempotency_store"] = idempotency_store
    app.extensions["outlook_gateway"] = gateway
    app.extensions["scheduling_orchestrator"] = orchestrator
    app.extensions["rate_limiters"] = {
        "ai": RateLimiter(limit=app.config["RATE_LIMIT_AI_PER_MINUTE"], window_seconds=60),
        "booking": RateLimiter(limit=app.config["RATE_LIMIT_BOOKING_PER_MINUTE"], window_seconds=60),
    }

    app.register_blueprint(health_bp, url_prefix="/api/v1")
    app.register_blueprint(booking_bp, url_prefix="/api/v1")
    app.register_blueprint(owner_bp, url_prefix="/api/v1")
    app.register_blueprint(frontend_bp)
    app.register_blueprint(microsoft_auth_bp)

    register_error_handlers(app)

    return app
