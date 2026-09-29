# Calendar--scheduler

AI-Assisted Tuxedo Rental Scheduling System — Flask application layer.

This repository implements the Flask/application side of the system described
in the Week 3 architecture and Week 4 detailed design documents. Microsoft
Outlook Calendar (via Microsoft Graph) is the authoritative scheduling data
store; this app never maintains a second appointment database (ADR-006).
Outlook integration lives entirely behind the `OutlookGateway` interface in
`app/gateways/outlook.py`. Two implementations exist: `FakeOutlookGateway`
(in-memory, the default) and `GraphOutlookGateway`
(`app/gateways/graph_outlook.py`, Microsoft Graph, added by Jose). The Graph
gateway is implemented and tested but **not yet wired into the running app**
(see "Known gaps").
`app/gateways/outlook.py`. Two implementations exist: `FakeOutlookGateway`
(in-memory, the default) and `GraphOutlookGateway`
(`app/gateways/graph_outlook.py`, Microsoft Graph, added by Jose). The Graph
gateway is implemented and tested but **not yet wired into the running app**
(see "Known gaps").

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

| Variable                                                                                     | Purpose                                                        | Notes                                                                                                                                                             |
| -------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FLASK_ENV`                                                                                  | `development` / `testing` / `production`                       | selects the config class in `config.py`                                                                                                                           |
| `BUSINESS_TIMEZONE`                                                                          | the shop's timezone; all scheduling and displayed times use it | IANA name, e.g. `America/Chicago`. Validated at startup. Needs the `tzdata` package on Windows (already in `requirements.txt`)                                    |
| `BUSINESS_TIMEZONE`                                                                          | the shop's timezone; all scheduling and displayed times use it | IANA name, e.g. `America/Chicago`. Validated at startup. Needs the `tzdata` package on Windows (already in `requirements.txt`)                                    |
| `OWNER_ACCESS_TOKEN`                                                                         | bearer token owner endpoints check for                         | placeholder until real Microsoft identity/role auth is wired in                                                                                                   |
| `OPENAI_API_KEY`                                                                             | enables the real OpenAI intent interpreter                     | leave blank to use `FakeIntentInterpreter` locally, no key required                                                                                               |
| `OPENAI_MODEL`, `AI_TIMEOUT_SECONDS`                                                         | OpenAI adapter tuning                                          |                                                                                                                                                                   |
| `OUTLOOK_GATEWAY`                                                                            | `fake` (default) or `graph`                                    | `graph` is reserved for `GraphOutlookGateway`, but selecting it currently fails at startup: it still needs an access-token provider and wiring (see "Known gaps") |
| `OUTLOOK_GATEWAY`                                                                            | `fake` (default) or `graph`                                    | `graph` is reserved for `GraphOutlookGateway`, but selecting it currently fails at startup: it still needs an access-token provider and wiring (see "Known gaps") |
| `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`, `MS_GRAPH_TENANT_ID`, `MS_GRAPH_CALENDAR_ID` | Microsoft Graph credentials                                    | used only once a real gateway is registered                                                                                                                       |
| `RATE_LIMIT_AI_PER_MINUTE`, `RATE_LIMIT_BOOKING_PER_MINUTE`                                  | rate-limit config                                              | present but **not yet enforced** in code (see "Known gaps")                                                                                                       |

**Never commit your real `.env` file.** `.gitignore` already excludes `.env`,
`.venv/`, `__pycache__/`, coverage artifacts, and common editor files.

## Database setup

None required. Per ADR-006, Outlook Calendar is the sole persistent
scheduling data store. Appointment types and business hours are
version-controlled application configuration (`app/config_store/`), not
database tables — there is no migration or seed step to run.

## Running the app (step by step, up to the browser)

This walks through everything from a fresh clone to a working page open in
your browser. If you already did Installation/Environment variables above,
skip to step 4.

1. **Clone and install** (skip if already done):
   ```bash
   git clone https://github.com/RameshKondala/Calendar--scheduler.git
   cd Calendar--scheduler
   python3 -m venv .venv
   source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. **Set up your environment file** (skip if already done):
   ```bash
   cp .env.example .env
   ```
   The defaults work as-is for local use: no `OPENAI_API_KEY` and
   `OUTLOOK_GATEWAY=fake` mean the app runs entirely locally, with a
   keyword-based fake intent interpreter and an in-memory fake Outlook
   calendar — no external accounts or credentials needed to try it out.
3. **Start the Flask server:**
   ```bash
   python run.py
   ```
   Leave this running. You should see `Running on http://127.0.0.1:5000` in
   the terminal. Open a second terminal for anything else below.
4. **Open it in a browser:**
   - **http://127.0.0.1:5000/** — the customer booking page.
   - **http://127.0.0.1:5000/owner** — the staff portal. Enter the
     `OWNER_ACCESS_TOKEN` value from your `.env` file (the default is
     `change-me-local-dev-token`) into the "Access token" field and click
     "Save token" before using the schedule/block/type sections — it's
     stored only in that browser tab's `sessionStorage`.
5. **Try the customer flow:** on `/`, pick an appointment type and a date
   (or describe it in the text box, e.g. "a fitting next Monday at 9am",
   and click "Fill in the fields below"), click "Find available times",
   pick one of the proposed slots, fill in your name and email, and click
   "Confirm booking". You should land on a confirmation screen with a
   calendar reference.
6. **Try the staff flow:** on `/owner`, after saving the token, set a
   from/to date-time range and click "Load appointments" to see the
   booking from step 5; try "Create block" to reserve time without a
   booking; try editing an appointment type's duration/buffer/active
   status and clicking "Save".
7. **Stop the server** when done with `Ctrl+C` in the terminal running
   `python run.py`.

The API is still reachable directly if you prefer scripting over the
browser — both pages call the same endpoints documented in "API
Reference" below:

```bash
curl http://127.0.0.1:5000/api/v1/health
curl http://127.0.0.1:5000/api/v1/appointment-types
```

No `curl`, PowerShell, or Postman is needed for normal use, though — the
two pages in step 4 are the primary interface. The frontend is plain
HTML/CSS/vanilla JavaScript (`app/templates/`, `app/static/`) with no
build step and no framework, per Week 4's technology stack, and contains
no scheduling logic of its own: every page action calls the existing
`/api/v1/...` endpoints, so `SchedulingOrchestrator`,
`BusinessRulesService`, `AvailabilityService`, and `OutlookGateway` remain
the only place booking decisions are made.

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
  Outlook gateway's behavior, plus `test_graph_outlook.py` — Jose's unit
  tests for `GraphOutlookGateway` (HTTP mocked).
  Outlook gateway's behavior, plus `test_graph_outlook.py` — Jose's unit
  tests for `GraphOutlookGateway` (HTTP mocked).
- `tests/integration/` — Flask test-client coverage of the customer and
  owner API endpoints: happy paths, validation failures, 404s, 405s, 409
  slot conflicts, a forced 503 `OUTLOOK_UNAVAILABLE`, owner authorization,
  the generic catch-all 500 handler, and the frontend page/static-asset
  routes (`test_frontend_routes.py`). `test_graph_gateway_integration.py`
  drives the real API through the real `GraphOutlookGateway` (only the HTTP
  call is mocked) to verify the two fit together: timezone handling,
  conflict detection, outage mapping, and Graph's UTC responses coming back
  as shop time.
  the generic catch-all 500 handler, and the frontend page/static-asset
  routes (`test_frontend_routes.py`). `test_graph_gateway_integration.py`
  drives the real API through the real `GraphOutlookGateway` (only the HTTP
  call is mocked) to verify the two fit together: timezone handling,
  conflict detection, outage mapping, and Graph's UTC responses coming back
  as shop time.

As of this pass: **104 tests, 104 passed, 0 failed, 0 skipped, 95% line
coverage** on `app/` (verified locally in a clean virtual environment).
As of this pass: **104 tests, 104 passed, 0 failed, 0 skipped, 95% line
coverage** on `app/` (verified locally in a clean virtual environment).

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request: checks out
the repo, installs Python 3.12 and pinned dependencies, runs `flake8`, then
runs `pytest` with coverage. The workflow fails if linting or any test
fails.

## API Reference

Base path: `/api/v1`. Content type: `application/json` for all request and
response bodies. Timestamps are ISO 8601. Datetimes you send **without** a UTC
offset (for example `2026-09-29T09:00:00`, or the value of an HTML
`datetime-local` input) are read as shop time (`BUSINESS_TIMEZONE`); datetimes
with an offset are honored as the same instant. Datetimes in responses always
carry the shop's offset (for example `2026-09-29T09:00:00-05:00`).
response bodies. Timestamps are ISO 8601. Datetimes you send **without** a UTC
offset (for example `2026-09-29T09:00:00`, or the value of an HTML
`datetime-local` input) are read as shop time (`BUSINESS_TIMEZONE`); datetimes
with an offset are honored as the same instant. Datetimes in responses always
carry the shop's offset (for example `2026-09-29T09:00:00-05:00`).

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

| Code                  | HTTP status | Retryable | Meaning                                                         |
| --------------------- | ----------- | --------- | --------------------------------------------------------------- |
| `VALIDATION_ERROR`    | 400         | No        | Request body/query failed validation, or wrong HTTP method used |
| `UNAUTHORIZED`        | 401         | No        | Missing/invalid owner bearer token                              |
| `NOT_FOUND`           | 404         | No        | Appointment/appointment-type/route not found                    |
| `SLOT_CONFLICT`       | 409         | Yes       | Selected slot became busy before the write                      |
| `AI_UNAVAILABLE`      | 503         | Yes       | Intent interpreter (OpenAI) failed or timed out                 |
| `OUTLOOK_UNAVAILABLE` | 503         | Yes       | Outlook gateway failed or timed out                             |
| `INTERNAL_ERROR`      | 500         | Usually   | Unexpected server error; no internal details are exposed        |

`FORBIDDEN` (403) and `RATE_LIMITED` (429) are defined in
`app/errors/handlers.py` for future use but are **not currently raised
anywhere** in the implementation — there is no role beyond "owner"/"not
owner" yet, and rate limiting is not enforced.

### Endpoints

#### `GET /api/v1/health`

No auth. Returns application liveness.

Response `200`:

```json
{ "status": "ok" }
```

#### `GET /api/v1/appointment-types`

No auth. Lists active appointment types from the configuration store.

Response `200`:

```json
{
  "appointment_types": [
    {
      "id": 1,
      "code": "initial_fitting",
      "display_name": "Initial Fitting",
      "duration_minutes": 45,
      "buffer_minutes": 15
    }
  ]
}
```

#### `POST /api/v1/intent`

No auth. Converts natural language into a structured scheduling intent.
Does **not** check availability or create appointments.

Request body:

```json
{
  "text": "I need a tuxedo fitting next Friday after 5 PM",
  "actor": "customer",
  "timezone": "America/Chicago"
}
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
    {
      "slot_id": "20260921T0900",
      "start": "2026-09-21T09:00:00",
      "end": "2026-09-21T09:45:00"
    }
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
  "customer": {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "555-0100"
  },
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
  "appointment": {
    "id": 389877385,
    "status": "confirmed",
    "start": "2026-09-21T09:00:00",
    "end": "2026-09-21T09:45:00",
    "outlook_event_id": "fake_41652b253c684a0e"
  },
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
    {
      "outlook_event_id": "fake_...",
      "subject": "Initial Fitting - Jane Doe",
      "start": "2026-09-21T09:00:00",
      "end": "2026-09-21T09:45:00",
      "categories": ["tuxedo_appointment", "initial_fitting"]
    }
  ]
}
```

`401 UNAUTHORIZED` if the bearer token is missing/wrong. `400
VALIDATION_ERROR` if `date_from`/`date_to` are missing or not valid ISO 8601.

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
- 51 unit + integration tests, all passing, 95% line coverage on `app/`
  (before the Week 6 frontend additions below).

## What's implemented (Week 6, frontend)

- Customer booking page (`GET /`) and staff portal (`GET /owner`), served
  by a new `frontend_bp` blueprint (`app/routes/frontend.py`) that only
  calls `render_template` — no validation, service, or gateway calls live
  in it.
- Plain HTML/CSS/vanilla JavaScript in `app/templates/` and
  `app/static/`, no build step, no frontend framework, per Week 4's
  technology stack. Every user action calls the existing
  `/api/v1/...` endpoints; no scheduling/business logic was duplicated
  into JavaScript.
- Customer flow: optional natural-language intent box
  (`POST /intent`) → appointment-type/date/time search
  (`POST /availability`) → slot picker → contact form → confirm
  (`POST /appointments`) → confirmation screen, with a 409 conflict
  routing the user back to re-pick a slot rather than just showing an
  error.
- Staff portal: session-scoped access-token entry (stored in that
  browser tab's `sessionStorage` only, never persisted server-side or
  committed) → schedule view (`GET /owner/appointments`) → block-time
  form (`POST /owner/blocks`) → inline appointment-type editing
  (`PUT /owner/appointment-types/{id}`).
- One shared JS helper (`app/static/js/api.js`) renders the existing
  `{"error": {code, message, retryable, request_id}}` contract into an
  error banner on both pages — no new error format was introduced.
- 7 new integration tests confirming both pages and all static assets
  render/serve correctly, and that adding page routes didn't change the
  API's error contract or routing.
- End-to-end verified against the real running server (not just tests):
  searched availability, booked a slot, confirmed the booked slot
  disappeared from a re-search, created an owner block, and updated an
  appointment type — all via the exact JSON payload shapes the frontend
  JS sends.

## What's implemented (Outlook integration, Jose)

- `GraphOutlookGateway` (`app/gateways/graph_outlook.py`) implements every
  `OutlookGateway` method against Microsoft Graph: free/busy via
  `calendarView`, event create/read/list, and owner blocks. All `requests`
  and parsing failures are mapped to `OutlookUnavailableError`, a slot that
  became busy raises `SlotConflictError`, event and calendar ids are
  URL-quoted, and a response it cannot read completely fails safe instead
  of being treated as an empty calendar.
- 25 unit tests with the HTTP layer mocked.
- **Not wired in yet.** Nothing constructs it: `OUTLOOK_GATEWAY=graph` still
  fails at startup (see "Known gaps").

## Time handling

The Graph gateway (like any `OutlookGateway`) requires timezone-aware
datetimes. `BusinessRulesService.to_business_time` is the single place that
converts input to shop time, and `SchedulingOrchestrator` applies it to
everything it sends to the gateway and to every event it reads back (Graph
returns UTC). `FakeOutlookGateway` enforces the same rule, so a service that
forgets fails in tests instead of only against the real calendar. The pages
display times exactly as the API returns them (shop time), regardless of the
viewer's own timezone.

- Total after this pass: **104 tests, 104 passed, 0 failed, 0 skipped, 95%
  line coverage** on `app/`.
- 51 unit + integration tests, all passing, 95% line coverage on `app/`
  (before the Week 6 frontend additions below).

## What's implemented (Week 6, frontend)

- Customer booking page (`GET /`) and staff portal (`GET /owner`), served
  by a new `frontend_bp` blueprint (`app/routes/frontend.py`) that only
  calls `render_template` — no validation, service, or gateway calls live
  in it.
- Plain HTML/CSS/vanilla JavaScript in `app/templates/` and
  `app/static/`, no build step, no frontend framework, per Week 4's
  technology stack. Every user action calls the existing
  `/api/v1/...` endpoints; no scheduling/business logic was duplicated
  into JavaScript.
- Customer flow: optional natural-language intent box
  (`POST /intent`) → appointment-type/date/time search
  (`POST /availability`) → slot picker → contact form → confirm
  (`POST /appointments`) → confirmation screen, with a 409 conflict
  routing the user back to re-pick a slot rather than just showing an
  error.
- Staff portal: session-scoped access-token entry (stored in that
  browser tab's `sessionStorage` only, never persisted server-side or
  committed) → schedule view (`GET /owner/appointments`) → block-time
  form (`POST /owner/blocks`) → inline appointment-type editing
  (`PUT /owner/appointment-types/{id}`).
- One shared JS helper (`app/static/js/api.js`) renders the existing
  `{"error": {code, message, retryable, request_id}}` contract into an
  error banner on both pages — no new error format was introduced.
- 7 new integration tests confirming both pages and all static assets
  render/serve correctly, and that adding page routes didn't change the
  API's error contract or routing.
- End-to-end verified against the real running server (not just tests):
  searched availability, booked a slot, confirmed the booked slot
  disappeared from a re-search, created an owner block, and updated an
  appointment type — all via the exact JSON payload shapes the frontend
  JS sends.

## What's implemented (Outlook integration, Jose)

- `GraphOutlookGateway` (`app/gateways/graph_outlook.py`) implements every
  `OutlookGateway` method against Microsoft Graph: free/busy via
  `calendarView`, event create/read/list, and owner blocks. All `requests`
  and parsing failures are mapped to `OutlookUnavailableError`, a slot that
  became busy raises `SlotConflictError`, event and calendar ids are
  URL-quoted, and a response it cannot read completely fails safe instead
  of being treated as an empty calendar.
- 25 unit tests with the HTTP layer mocked.
- **Not wired in yet.** Nothing constructs it: `OUTLOOK_GATEWAY=graph` still
  fails at startup (see "Known gaps").

## Time handling

The Graph gateway (like any `OutlookGateway`) requires timezone-aware
datetimes. `BusinessRulesService.to_business_time` is the single place that
converts input to shop time, and `SchedulingOrchestrator` applies it to
everything it sends to the gateway and to every event it reads back (Graph
returns UTC). `FakeOutlookGateway` enforces the same rule, so a service that
forgets fails in tests instead of only against the real calendar. The pages
display times exactly as the API returns them (shop time), regardless of the
viewer's own timezone.

- Total after this pass: **104 tests, 104 passed, 0 failed, 0 skipped, 95%
  line coverage** on `app/`.

## Known gaps / remaining integration work

These are explicitly **not** complete — do not treat them as done:

- **Wiring `GraphOutlookGateway` into the app.** The gateway exists but
  `_build_outlook_gateway` still raises for `OUTLOOK_GATEWAY=graph`.
  Blocked on a decision: the gateway takes an `access_token_provider`
  callable and calls `/me/calendars/...`, which requires a _delegated_
  (signed-in user) token, while the config carries a client secret and
  tenant id, which is the _app-only_ flow — and `/me` is not valid with an
  app-only token. Someone has to choose the flow and write the provider
  (MSAL). Nothing in this repo invents one.
- **Graph pagination.** Graph returns 10 `calendarView` events per page by
  default. The gateway sets no `$top` and rejects any response that has a
  `nextLink`, so a window with more than 10 events (a busy shop day, or a
  week in the owner view) fails with `503 OUTLOOK_UNAVAILABLE` every time.
  It fails closed rather than truncating, which is the safe choice, but it
  needs to follow `nextLink` (bounded) before real use.
- **Bookings are not checked against business hours.** `POST /appointments`
  accepts any `start` for an active appointment type; only `/availability`
  applies business hours. Week 4 §3.6 says `start` must match a valid
  candidate. The pages only offer valid slots, but a direct API call is not
  stopped.
- **Wiring `GraphOutlookGateway` into the app.** The gateway exists but
  `_build_outlook_gateway` still raises for `OUTLOOK_GATEWAY=graph`.
  Blocked on a decision: the gateway takes an `access_token_provider`
  callable and calls `/me/calendars/...`, which requires a _delegated_
  (signed-in user) token, while the config carries a client secret and
  tenant id, which is the _app-only_ flow — and `/me` is not valid with an
  app-only token. Someone has to choose the flow and write the provider
  (MSAL). Nothing in this repo invents one.
- **Graph pagination.** Graph returns 10 `calendarView` events per page by
  default. The gateway sets no `$top` and rejects any response that has a
  `nextLink`, so a window with more than 10 events (a busy shop day, or a
  week in the owner view) fails with `503 OUTLOOK_UNAVAILABLE` every time.
  It fails closed rather than truncating, which is the safe choice, but it
  needs to follow `nextLink` (bounded) before real use.
- **Bookings are not checked against business hours.** `POST /appointments`
  accepts any `start` for an active appointment type; only `/availability`
  applies business hours. Week 4 §3.6 says `start` must match a valid
  candidate. The pages only offer valid slots, but a direct API call is not
  stopped.
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
- **Owner "login" is a token paste box, not sign-in.** It's wired to the
  same placeholder bearer-token check as the API; it will need to change
  together with the real Microsoft identity/role auth item above.
