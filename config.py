"""Application configuration, loaded from environment variables (section 5.2,
section 7.7). No secrets are hard-coded; ``.env`` is only ever read locally
via python-dotenv and is never committed.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    """Shared defaults. Subclasses override per environment."""

    BUSINESS_TIMEZONE = os.environ.get("BUSINESS_TIMEZONE", "America/Chicago")
    OWNER_ACCESS_TOKEN = os.environ.get("OWNER_ACCESS_TOKEN")

    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "8"))

    MS_GRAPH_CLIENT_ID = os.environ.get("MS_GRAPH_CLIENT_ID")
    MS_GRAPH_CLIENT_SECRET = os.environ.get("MS_GRAPH_CLIENT_SECRET")
    MS_GRAPH_TENANT_ID = os.environ.get("MS_GRAPH_TENANT_ID")
    MS_GRAPH_CALENDAR_ID = os.environ.get("MS_GRAPH_CALENDAR_ID")
    GRAPH_TIMEOUT_SECONDS = float(os.environ.get("GRAPH_TIMEOUT_SECONDS", "8"))

    RATE_LIMIT_AI_PER_MINUTE = int(os.environ.get("RATE_LIMIT_AI_PER_MINUTE", "30"))
    RATE_LIMIT_BOOKING_PER_MINUTE = int(os.environ.get("RATE_LIMIT_BOOKING_PER_MINUTE", "10"))

    # Which OutlookGateway implementation to use. "fake" is safe for local
    # dev and CI; Jose's real implementation will register under "graph".
    OUTLOOK_GATEWAY = os.environ.get("OUTLOOK_GATEWAY", "fake")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    TESTING = False


class TestingConfig(BaseConfig):
    DEBUG = False
    TESTING = True
    OUTLOOK_GATEWAY = "fake"
    OWNER_ACCESS_TOKEN = "test-owner-token"


class ProductionConfig(BaseConfig):
    DEBUG = False
    TESTING = False


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(env_name: str | None = None):
    env_name = env_name or os.environ.get("FLASK_ENV", "development")
    return CONFIG_BY_NAME.get(env_name, DevelopmentConfig)
