import pytest

from app.config_store.appointment_types import AppointmentTypeStore
from app.errors.handlers import ValidationError
from app.services.intent import FakeIntentInterpreter, IntentInterpreter, IntentService


@pytest.fixture
def intent_service():
    interpreter = FakeIntentInterpreter(AppointmentTypeStore())
    return IntentService(interpreter)


def test_interpret_recognizes_appointment_type_and_date(intent_service):
    intent = intent_service.interpret("I need a fitting next Friday at 5 pm", actor="customer", timezone="UTC")
    assert intent.action == "find_availability"
    assert intent.appointment_type == "initial_fitting"
    assert intent.date_start is not None


def test_interpret_asks_for_clarification_when_type_unknown(intent_service):
    intent = intent_service.interpret("I need something next Friday", actor="customer", timezone="UTC")
    assert intent.action == "clarify"
    assert intent.needs_clarification is True
    assert intent.clarification_question


def test_interpret_validates_untrusted_interpreter_output():
    class BadInterpreter(IntentInterpreter):
        def raw_interpret(self, text, actor, timezone):
            return {"action": "not_a_real_action"}

    service = IntentService(BadInterpreter())
    with pytest.raises(ValidationError):
        service.interpret("anything", actor="customer", timezone="UTC")
