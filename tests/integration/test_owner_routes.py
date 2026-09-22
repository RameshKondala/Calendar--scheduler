def test_owner_appointments_requires_auth(client):
    resp = client.get("/api/v1/owner/appointments?date_from=2026-09-21T00:00:00&date_to=2026-09-22T00:00:00")
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_owner_appointments_with_valid_token(client, owner_headers):
    resp = client.get(
        "/api/v1/owner/appointments?date_from=2026-09-21T00:00:00&date_to=2026-09-22T00:00:00",
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert "appointments" in resp.get_json()


def test_owner_appointments_missing_query_params(client, owner_headers):
    resp = client.get("/api/v1/owner/appointments", headers=owner_headers)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_owner_create_block(client, owner_headers):
    resp = client.post(
        "/api/v1/owner/blocks",
        json={"start": "2026-09-21T13:00:00", "end": "2026-09-21T14:00:00", "reason": "Staff lunch"},
        headers=owner_headers,
    )
    assert resp.status_code == 201
    assert resp.get_json()["block"]["outlook_event_id"].startswith("fake_")


def test_owner_create_block_without_auth_rejected(client):
    resp = client.post(
        "/api/v1/owner/blocks",
        json={"start": "2026-09-21T13:00:00", "end": "2026-09-21T14:00:00"},
    )
    assert resp.status_code == 401


def test_owner_update_appointment_type(client, owner_headers):
    resp = client.put(
        "/api/v1/owner/appointment-types/1",
        json={"duration_minutes": 60},
        headers=owner_headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()["appointment_type"]["duration_minutes"] == 60


def test_owner_update_unknown_appointment_type_404(client, owner_headers):
    resp = client.put(
        "/api/v1/owner/appointment-types/9999",
        json={"duration_minutes": 60},
        headers=owner_headers,
    )
    assert resp.status_code == 404
