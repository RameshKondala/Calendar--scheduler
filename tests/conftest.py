import pytest

from app import create_app
from config import TestingConfig
from app.gateways.outlook import FakeOutlookGateway


@pytest.fixture
def outlook_gateway():
    return FakeOutlookGateway()


@pytest.fixture
def app(outlook_gateway):
    application = create_app(config_object=TestingConfig, outlook_gateway=outlook_gateway)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def owner_headers(app):
    return {"Authorization": f"Bearer {app.config['OWNER_ACCESS_TOKEN']}"}
