# Calendar--scheduler

AI-Assisted Tuxedo Rental Scheduling System — Flask application layer.

This repository implements the Flask/application side of the system described
in the Week 3 architecture and Week 4 detailed design documents. Microsoft
Outlook Calendar (via Microsoft Graph) is the authoritative scheduling data
store; this app never maintains a second appointment database (ADR-006).
Outlook integration lives entirely behind the `OutlookGateway` interface in
`app/gateways/outlook.py` so it can be swapped for a real Microsoft Graph
implementation without touching routes or services.

## Prerequisites

- Python 3.12+
- Git
- (Optional, for real AI intent parsing) an OpenAI API key
- (Optional, for real calendar integration) Microsoft Graph / Entra app
  registration — this is Jose's integration; the app runs fully without it
  using `FakeOutlookGateway`.

## Installation

```bash
git clone https://github.com/RameshKondala/Calendar--scheduler.git
cd Calendar--scheduler
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Environment variables

Copy the example file and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Purpose | Notes |
|---|---|---|
| `FLASK_ENV` | `development` / `testing` / `production` | selects the config class in `config.py` |
| `BUSINESS_TIMEZONE` | default timezone for scheduling | e.g. `America/Chicago` |
| `OWNER_ACCESS_TOKEN` | bearer token owner endpoints check for | placeholder until real Microsoft identity/role auth is wired in |
| `OPENAI_API_KEY` | enables the real OpenAI intent interpreter | leave blank to use `FakeIntentInterpreter` locally, no key required |
| `OPENAI_MODEL`, `AI_TIMEOUT_SECONDS` | OpenAI adapter tuning | |
| `OUTLOOK_GATEWAY` | `fake` (default) or `graph` | `graph` is the integration point for Jose's real Microsoft Graph gateway; not yet implemented |
| `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`, `MS_GRAPH_TENANT_ID`, `MS_GRAPH_CALENDAR_ID` | Microsoft Graph credentials | used only once a real gateway is registered |
| `RATE_LIMIT_AI_PER_MINUTE`, `RATE_LIMIT_BOOKING_PER_MINUTE` | rate-limit config | present but **not yet enforced** in code (see "Known gaps") |

**Never commit your real `.env` file.** `.gitignore` already excludes `.env`,
`.venv/`, `__pycache__/`, coverage artifacts, and common editor files.

## Database setup

None required. Per ADR-006, Outlook Calendar is the sole persistent
scheduling data store. Appointment types and business hours are
version-controlled application configuration (`app/config_store/`), not
database tables — there is no migration or seed step to run.

## Running the app

```bash
python run.py
```

Then, in another terminal:

```bash
curl http://127.0.0.1:5000/api/v1/health
curl http://127.0.0.1:5000/api/v1/appointment-types
```

With no `OPENAI_API_KEY` and `OUTLOOK_GATEWAY=fake` (the defaults), the app
runs fully locally: intent parsing uses a simple keyword-based fake
interpreter, and calendar operations use an in-memory fake Outlook gateway.

## Running tests

```bash
pytest
```

Coverage is on by default (configured in `setup.cfg`) and prints a
per-file report. Lint with:

```bash
flake8 app config.py run.py tests
```

- `tests/unit/` — business rules, availability slot generation, intent
  validation/interpretation (including the OpenAI adapter's error mapping,
  mocked — no API key needed), the scheduling orchestrator, and the fake
  Outlook gateway's behavior.
- `tests/integration/` — Flask test-client coverage of the customer and
  owner API endpoints: happy paths, validation failures, 404s, 405s, 409
  slot conflicts, a forced 503 `OUTLOOK_UNAVAILABLE`, owner authorization,
  and the generic catch-all 500 handler.

As of this pass: **51 tests, 51 passed, 0 failed, 0 skipped, 95% line
coverage** on `app/` (verified locally in a clean virtual environment; see
the PR summary at the bottom of this document for the exact run).

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request: checks out
the repo, installs Python 3.12 and pinned dependencies, runs `flake8`, then
runs `pytest` with coverage. The workflow fails if linting or any test
fails.

## API Reference

Base path: `/api/v1`. Content type: `application/json` for all request and
response bodies. Timestamps are ISO 8601.

### Authentication

- Customer-facing endpoints (`/intent`, `/availability`, `/appointments`,
  `/appointment-types`) require no authentication.
- Owner endpoints (`/owner/*`) require `Authorization: Bearer <OWNER_ACCESS_TOKEN>`,
  matched against the `OWNER_ACCESS_TOKEN` environment variable using a
  constant-time comparison. **This is a placeholder** for the real
  Microsoft identity/role-based auth described in Week 4 §4.2 — see "Known
  gaps."

### Standard error format

Every non-2xx response has this shape:

```json
{
  "error": {
    "code": "SLOT_CONFLICT",
    "message": "The selected slot is no longer available. Please choose another time.",
    "retryable": true,
    "request_id": "req_8f21a0c3d4e5"
  }
}
```

| Code | HTTP status | Retryable | Meaning |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | No | Request body/query failed validation, or wrong HTTP method used |
| `UNAUTHORIZED` | 401 | No | Missing/invalid owner bearer token |
| `NOT_FOUND` | 404 | No | Appointment/appointment-type/route not found |
| `SLOT_CONFLICT` | 409 | Yes | Selected slot became busy before the write |
| `AI_UNAVAILABLE` | 503 | Yes | Intent interpreter (OpenAI) failed or timed out |
| `OUTLOOK_UNAVAILABLE` | 503 | Yes | Outlook gateway failed or timed out |
| `INTERNAL_ERROR` | 500 | Usually | Unexpected server error; no internal details are exposed |

`FORBIDDEN` (403) and `RATE_LIMITED` (429) are defined in
`app/errors/handlers.py` for future use but are **not currently raised
anywhere** in the implementation — there is no role beyond "owner"/"not
owner" yet, and rate limiting is not enforced.

### Endpoints

#### `GET /api/v1/health`
No auth. Returns application liveness.

Response `200`:
```json
{"status": "ok"}
```

#### `GET /api/v1/appointment-types`
No auth. Lists active appointment types from the configuration store.

Response `200`:
```json
{
  "appointment_types": [
    {"id": 1, "code": "initial_fitting", "display_name": "Initial Fitting", "duration_minutes": 45, "buffer_minutes": 15}
  ]
}
```

#### `POST /api/v1/intent`
No auth. Converts natural language into a structured scheduling intent.
Does **not** check availability or create appointments.

Request body:
```json
{"text": "I need a tuxedo fitting next Friday after 5 PM", "actor": "customer", "timezone": "America/Chicago"}
```
`text` (string, 1–500 chars, required), `actor` (`customer` | `owner`, required),
`timezone` (string, optional — defaults to `BUSINESS_TIMEZONE`).

Response `200`:
```json
{
  "intent": {
    "action": "find_availability",
    "appointment_type": "initial_fitting",
    "date_start": "2026-09-25",
    "date_end": "2026-09-25",
    "time_start": "17:00:00",
    "time_end": null,
    "confidence": 0.6
  },
  "needs_clarification": false,
  "clarification_question": null
}
```
`400 VALIDATION_ERROR` on empty text or an unsupported `actor`.
`503 AI_UNAVAILABLE` if the real OpenAI interpreter is configured and the
call fails/times out.

#### `POST /api/v1/availability`
No auth. Validates the request against business rules and returns
candidate slots checked against Outlook free/busy. **Options are proposals,
not reservations** — they are rechecked at booking time.

Request body:
```json
{
  "appointment_type": "initial_fitting",
  "date_start": "2026-09-21",
  "date_end": "2026-09-21",
  "time_start": "09:00:00",
  "time_end": "12:00:00",
  "max_options": 3
}
```
`appointment_type` (string, required, must be an active type code),
`date_start`/`date_end` (dates, required, range ≤ 30 days), `time_start`/
`time_end` (times, optional — default to business hours), `max_options`
(1–10, default 3).

Response `200`:
```json
{
  "options": [
    {"slot_id": "20260921T0900", "start": "2026-09-21T09:00:00", "end": "2026-09-21T09:45:00"}
  ],
  "source": "outlook",
  "expires_in_seconds": 120
}
```
`400 VALIDATION_ERROR` for an unknown/inactive appointment type or an
invalid date range. `503 OUTLOOK_UNAVAILABLE` if the Outlook gateway fails.

#### `POST /api/v1/appointments`
No auth (customer flow). Confirms and creates an appointment.

Request body:
```json
{
  "customer": {"name": "Jane Doe", "email": "jane@example.com", "phone": "555-0100"},
  "appointment_type_id": 1,
  "start": "2026-09-21T09:00:00",
  "confirmation": true,
  "notes": "Prefers grey vest"
}
```
`customer.name` (1–100 chars, required), `customer.email` (valid email,
required), `customer.phone` (optional, ≤30 chars), `appointment_type_id`
(int, required, must be active), `start` (datetime, required),
`confirmation` (boolean, required, **must be `true`**), `notes` (optional,
≤500 chars). An optional `Idempotency-Key` header is accepted (see "Known
gaps" — not yet enforced).

Response `201`:
```json
{
  "appointment": {"id": 389877385, "status": "confirmed", "start": "2026-09-21T09:00:00", "end": "2026-09-21T09:45:00", "outlook_event_id": "fake_41652b253c684a0e"},
  "message": "Your appointment is confirmed."
}
```
`400 VALIDATION_ERROR` for invalid input, an inactive/unknown
`appointment_type_id`, or `confirmation: false`. `409 SLOT_CONFLICT` if the
slot became busy between availability and booking. `503
OUTLOOK_UNAVAILABLE` on gateway failure.

#### `GET /api/v1/appointments/{event_id}`
No auth (a real deployment would scope this to a guest token or owner
session — see "Known gaps"). Looks up a confirmed appointment by its
persistent Outlook event id.

Response `200`: same `appointment` shape as above.
`404 NOT_FOUND` if no such event exists.

#### `GET /api/v1/owner/appointments`
Owner auth required. Query params `date_from`, `date_to` (both required,
ISO 8601 datetimes).

Response `200`:
```json
{
  "appointments": [
    {"outlook_event_id": "fake_...", "subject": "Initial Fitting - Jane Doe", "start": "2026-09-21T09:00:00", "end": "2026-09-21T09:45:00", "categories": ["tuxedo_appointment", "initial_fitting"]}
  ]
}
```
`401 UNAUTHORIZED` if the bearer token is missing/wrong. `400
VALIDATION_ERROR` if `date_from`/`date_to` are missing or not valid ISO
8601.

#### `POST /api/v1/owner/blocks`
Owner auth required. Creates an Outlook busy block.

Request body: `{"start": "...", "end": "...", "reason": "Staff lunch"}`
(`reason` optional, ≤200 chars).

Response `201`: `{"block": {"outlook_event_id": "...", "start": "...", "end": "..."}}`.
`400 VALIDATION_ERROR` if `end` is not after `start`, or the body fails
schema validation.

#### `PUT /api/v1/owner/appointment-types/{id}`
Owner auth required. Updates `duration_minutes` (5–480), `buffer_minutes`
(0–120), and/or `active`, any subset of which may be supplied.

Response `200`: the updated appointment-type object.
`404 NOT_FOUND` if the id doesn't exist. `400 VALIDATION_ERROR` if a
supplied value is out of range.

## What's implemented (Week 5, Flask/application side)

- Flask application factory (`app/__init__.py`) with dependency injection
  for the Outlook gateway and intent interpreter — no global mutable state.
- Environment-variable configuration with separate `Development` /
  `Testing` / `Production` config classes.
- Standard API error contract (`app/errors/handlers.py`), including the
  404 and 405 framework-level handlers and a catch-all 500 handler that
  never leaks exception details.
- All endpoints from Week 4 §3.3 (see API Reference above).
- Request validation via Marshmallow schemas for every endpoint.
- `BusinessRulesService` (appointment-type + business-hours policy) and
  `AvailabilityService` (candidate-slot generation against Outlook
  free/busy).
- `SchedulingOrchestrator` coordinating interpret → find options → confirm
  → create, with a recheck-before-write step and no confirmed status until
  the Outlook gateway reports success.
- `OutlookGateway` interface + `FakeOutlookGateway` — the integration
  boundary Jose's real Microsoft Graph implementation will satisfy.
- `IntentService` interface + `FakeIntentInterpreter` (default, no API key
  needed) + `OpenAIIntentInterpreter` (used automatically when
  `OPENAI_API_KEY` is set), both validated through the same
  `SchedulingIntentSchema` before being trusted.
- Owner-route authorization via a constant-time bearer-token check
  (`app/routes/auth.py`), stubbed pending real Microsoft identity/role auth.
- CI pipeline (`.github/workflows/ci.yml`): lint + test on every push/PR.
- 51 unit + integration tests, all passing, 95% line coverage on `app/`.

## Known gaps / remaining integration work

These are explicitly **not** complete — do not treat them as done:

- **Real Microsoft Graph gateway.** `OutlookGateway` is only implemented by
  `FakeOutlookGateway`. Jose's real implementation should be added as
  (e.g.) `app/gateways/graph_outlook.py`, implementing the same interface,
  and registered in `app/__init__.py::_build_outlook_gateway` under
  `OUTLOOK_GATEWAY=graph`. No route or service code should need to change.
- **Real Microsoft identity/role-based owner auth.** The current
  `require_owner` check is a bearer-token placeholder, not MSAL/Entra.
- **Guest-scoped `GET /appointments/{id}`.** Currently open to anyone who
  knows the Outlook event id; Week 4 §3.3 calls for "guest token or owner"
  auth, which depends on how Jose's identity layer represents a guest.
- **Idempotency-Key enforcement.** The header is accepted and passed
  through `BookingCommand`, but nothing currently de-duplicates retried
  writes — there's no local database to store idempotency records against
  (see ADR-006), so this needs a decision (e.g. an Outlook extension
  property, or a small key-value store) before it's production-ready.
- **Rate limiting.** Config values exist (`RATE_LIMIT_*`) but are not yet
  enforced by the routes; `429 RATE_LIMITED` and `403 FORBIDDEN` are
  defined in the error contract but never raised.
- **Contract/E2E test tiers.** Only unit and integration tests exist so far;
  the `contract/` and `e2e/` tiers from Week 4 §8.4 are not yet built out
  (they depend on the real Graph/OpenAI integrations to be meaningful).
