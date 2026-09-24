def test_health_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_get_appointment_types(client):
    resp = client.get("/api/v1/appointment-types")
    assert resp.status_code == 200
    body = resp.get_json()
    codes = {t["code"] for t in body["appointment_types"]}
    assert "initial_fitting" in codes


def test_post_intent_success(client):
    resp = client.post(
        "/api/v1/intent",
        json={"text": "I need a fitting next Monday at 9am", "actor": "customer"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["intent"]["action"] == "find_availability"


def test_post_intent_rejects_empty_text(client):
    resp = client.post("/api/v1/intent", json={"text": "", "actor": "customer"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_post_intent_rejects_unsupported_actor(client):
    resp = client.post("/api/v1/intent", json={"text": "book a fitting", "actor": "robot"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_post_availability_success(client):
    resp = client.post(
        "/api/v1/availability",
        json={
            "appointment_type": "initial_fitting",
            "date_start": "2026-09-21",
            "date_end": "2026-09-21",
            "time_start": "09:00:00",
            "time_end": "12:00:00",
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "outlook"
    assert len(body["options"]) > 0


def test_post_availability_unknown_type_returns_validation_error(client):
    resp = client.post(
        "/api/v1/availability",
        json={
            "appointment_type": "does_not_exist",
            "date_start": "2026-09-21",
            "date_end": "2026-09-21",
        },
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_full_booking_flow_and_conflict(client):
    booking_payload = {
        "customer": {"name": "Jane Doe", "email": "jane@example.com"},
        "appointment_type_id": 1,
        "start": "2026-09-21T09:00:00",
        "confirmation": True,
    }

    first = client.post("/api/v1/appointments", json=booking_payload)
    assert first.status_code == 201
    body = first.get_json()
    assert body["appointment"]["status"] == "confirmed"
    event_id = body["appointment"]["outlook_event_id"]

    # Re-fetching the same appointment succeeds.
    get_resp = client.get(f"/api/v1/appointments/{event_id}")
    assert get_resp.status_code == 200

    # Booking the exact same slot again conflicts.
    second = client.post("/api/v1/appointments", json=booking_payload)
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "SLOT_CONFLICT"


def test_post_appointments_requires_confirmation_true(client):
    payload = {
        "customer": {"name": "Jane Doe", "email": "jane@example.com"},
        "appointment_type_id": 1,
        "start": "2026-09-21T09:00:00",
        "confirmation": False,
    }
    resp = client.post("/api/v1/appointments", json=payload)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_post_appointments_invalid_email_rejected(client):
    payload = {
        "customer": {"name": "Jane Doe", "email": "not-an-email"},
        "appointment_type_id": 1,
        "start": "2026-09-21T09:00:00",
        "confirmation": True,
    }
    resp = client.post("/api/v1/appointments", json=payload)
    assert resp.status_code == 400


def test_get_unknown_appointment_returns_404(client):
    resp = client.get("/api/v1/appointments/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "NOT_FOUND"


def test_unknown_route_returns_standard_404_contract(client):
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "request_id" in body["error"]
