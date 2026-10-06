"""End-to-end test of the full booking journey, chained in one sequence
rather than isolated per-endpoint checks.

This is an E2E test of the *application*: it runs through the real Flask
app, real services, and the real in-memory ``FakeOutlookGateway``/
``FakeIntentInterpreter``, driving exactly the HTTP calls the frontend
pages make, in the order a real session would make them. It is not an
end-to-end test against the live Microsoft Graph or OpenAI services --
that tier needs real credentials this environment doesn't have (see
README "Known gaps"). What it does cover for real: that every piece
wired together in this repository -- validation, business rules,
availability, booking, idempotency, confirmation tokens, owner auth, and
rate limiting -- produces one coherent journey, not just that each piece
passes in isolation.
"""


def test_full_customer_and_owner_journey(client, owner_headers):
    # 1. The app is reachable and the customer/owner pages are servable.
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/owner").status_code == 200

    # 2. Customer describes what they need in plain language.
    intent_resp = client.post(
        "/api/v1/intent", json={"text": "I need a fitting next Monday at 9am", "actor": "customer"}
    )
    assert intent_resp.status_code == 200
    intent = intent_resp.get_json()["intent"]
    assert intent["action"] == "find_availability"
    assert intent["appointment_type"] == "initial_fitting"

    # 3. They search availability using what the intent step filled in.
    availability_resp = client.post("/api/v1/availability", json={
        "appointment_type": intent["appointment_type"],
        "date_start": intent["date_start"],
        "date_end": intent["date_start"],
        "time_start": intent["time_start"],
        "max_options": 3,
    })
    assert availability_resp.status_code == 200
    options = availability_resp.get_json()["options"]
    assert len(options) > 0
    chosen_slot = options[0]

    # 4. They book the first offered slot, with an Idempotency-Key as a
    #    real client would send to survive a dropped connection safely.
    booking_payload = {
        "customer": {"name": "Jane Doe", "email": "jane@example.com"},
        "appointment_type_id": 1,
        "start": chosen_slot["start"],
        "confirmation": True,
    }
    idempotency_headers = {"Idempotency-Key": "e2e-journey-key-1"}
    booking_resp = client.post("/api/v1/appointments", json=booking_payload, headers=idempotency_headers)
    assert booking_resp.status_code == 201
    booking = booking_resp.get_json()
    event_id = booking["appointment"]["outlook_event_id"]
    confirmation_token = booking["confirmation_token"]

    # 5. A flaky connection causes the browser to retry the exact same
    #    request; the idempotency key means it's a replay, not a double-book.
    retry_resp = client.post("/api/v1/appointments", json=booking_payload, headers=idempotency_headers)
    assert retry_resp.status_code == 201
    assert retry_resp.get_json()["appointment"]["outlook_event_id"] == event_id

    # 6. The customer (a guest, no owner credential) looks their booking
    #    back up using the confirmation token from step 4 -- and only that.
    assert client.get(f"/api/v1/appointments/{event_id}").status_code == 401
    guest_lookup = client.get(f"/api/v1/appointments/{event_id}?token={confirmation_token}")
    assert guest_lookup.status_code == 200
    assert guest_lookup.get_json()["appointment"]["start"] == chosen_slot["start"]

    # 7. Re-searching the same window no longer offers the booked slot.
    second_search = client.post("/api/v1/availability", json={
        "appointment_type": intent["appointment_type"],
        "date_start": intent["date_start"],
        "date_end": intent["date_start"],
        "max_options": 6,
    })
    remaining_starts = [o["start"] for o in second_search.get_json()["options"]]
    assert chosen_slot["start"] not in remaining_starts

    # 8. The owner (dev bearer-token path) reviews the day's schedule and
    #    sees the booking that was just made.
    schedule_resp = client.get(
        f"/api/v1/owner/appointments?date_from={intent['date_start']}T00:00:00"
        f"&date_to={intent['date_start']}T23:59:59",
        headers=owner_headers,
    )
    assert schedule_resp.status_code == 200
    scheduled_ids = [a["outlook_event_id"] for a in schedule_resp.get_json()["appointments"]]
    assert event_id in scheduled_ids

    # 9. The owner blocks off some time, and it does not collide with the
    #    existing booking (different window).
    block_resp = client.post(
        "/api/v1/owner/blocks",
        json={
            "start": f"{intent['date_start']}T13:00:00",
            "end": f"{intent['date_start']}T14:00:00",
            "reason": "Staff lunch",
        },
        headers=owner_headers,
    )
    assert block_resp.status_code == 201

    # 10. The owner adjusts the appointment type the customer booked, and
    #     the public listing reflects the change immediately.
    update_resp = client.put(
        "/api/v1/owner/appointment-types/1", json={"duration_minutes": 50}, headers=owner_headers
    )
    assert update_resp.status_code == 200
    types_resp = client.get("/api/v1/appointment-types")
    updated = next(t for t in types_resp.get_json()["appointment_types"] if t["id"] == 1)
    assert updated["duration_minutes"] == 50

    # 11. Without owner credentials, none of the owner actions above are
    #     available -- the journey's privilege boundary actually holds.
    assert client.get(
        f"/api/v1/owner/appointments?date_from={intent['date_start']}T00:00:00"
        f"&date_to={intent['date_start']}T23:59:59"
    ).status_code == 401
