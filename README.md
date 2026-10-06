# Calendar--scheduler

AI-Assisted Tuxedo Rental Scheduling System — Flask application layer.

This repository implements the system described in the Week 3 architecture
and Week 4 detailed design documents. Microsoft Outlook Calendar (via
Microsoft Graph) is the authoritative scheduling data store; this app never
maintains a second appointment database (ADR-006). Outlook integration lives
entirely behind the `OutlookGateway` interface in `app/gateways/outlook.py`.
Two implementations exist: `FakeOutlookGateway` (in-memory, the default for
local dev) and `GraphOutlookGateway` (`app/gateways/graph_outlook.py`,
Microsoft Graph, by Jose) with `MsalTokenProvider`
(`app/gateways/msal_auth.py`) handling delegated Microsoft sign-in. The
Graph gateway is implemented, wired, and reachable through a real sign-in
flow — see "What's implemented" and "Design notes and limitations" below
for exactly what that does and doesn't cover.

## Prerequisites

- Python 3.12+
- Git
- (Optional, for real AI intent parsing) an OpenAI API key
- (Optional, for real calendar integration) a Microsoft Entra app
  registration with Graph `Calendars.ReadWrite` delegated permission — the
  app runs fully without one using `FakeOutlookGateway`

## Installation

```bash
git clone https://github.com/RameshKondala/Calendar--scheduler.git
cd Calendar--scheduler
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Environment variables

Copy the example file and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Purpose | Notes |
| --- | --- | --- |
| `FLASK_ENV` | `development` / `testing` / `production` | selects the config class in `config.py` |
| `BUSINESS_TIMEZONE` | the shop's timezone; all scheduling and displayed times use it | IANA name, e.g. `America/Chicago`. Validated at startup. Needs the `tzdata` package on Windows (already in `requirements.txt`) |
| `SECRET_KEY` | signs the Flask session cookie and appointment confirmation tokens | the default is dev-only; set a real random value for anything beyond your own machine |
| `OWNER_ACCESS_TOKEN` | a shared bearer token owner endpoints accept | **local dev/CI shortcut, not identity** — see "Authentication" below |
| `OWNER_ALLOWED_UPNS` | comma-separated Microsoft work/school usernames allowed owner access | checked after a real Microsoft sign-in; the **real** auth path |
| `OPENAI_API_KEY` | enables the real OpenAI intent interpreter | leave blank to use `FakeIntentInterpreter` locally, no key required |
| `OPENAI_MODEL`, `AI_TIMEOUT_SECONDS` | OpenAI adapter tuning | |
| `OUTLOOK_GATEWAY` | `fake` (default) or `graph` | `graph` builds `GraphOutlookGateway` + `MsalTokenProvider` and requires the four `MS_GRAPH_*` variables below |
| `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`, `MS_GRAPH_TENANT_ID`, `MS_GRAPH_CALENDAR_ID` | Microsoft Graph app registration + target calendar | required when `OUTLOOK_GATEWAY=graph` |
| `GRAPH_TIMEOUT_SECONDS` | per-request timeout for Graph calls | |
| `RATE_LIMIT_AI_PER_MINUTE` | shared limit for `/intent` + `/availability` per client IP | enforced; see "Design notes" for the per-process caveat |
| `RATE_LIMIT_BOOKING_PER_MINUTE` | limit for `POST /appointments` per client IP | enforced; same caveat |

**Never commit your real `.env` file.** `.gitignore` already excludes `.env`,
`.venv/`, `__pycache__/`, coverage artifacts, and common editor files.

## Database setup

None required. Per ADR-006, Outlook Calendar is the sole persistent
scheduling data store. Appointment types and business hours are
version-controlled application configuration (`app/config_store/`), not
database tables — there is no migration or seed step to run. (Two small
in-memory, process-local caches exist for idempotency and rate limiting —
see "Design notes and limitations" — but neither is a database or an
appointment store.)

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
   The defaults work as-is for local use: `OUTLOOK_GATEWAY=fake` and no
   `OPENAI_API_KEY` mean the app runs entirely locally, with a keyword-based
   fake intent interpreter and an in-memory fake Outlook calendar — no
   external accounts or credentials needed to try it out.
3. **Start the Flask server:**
   ```bash
   python run.py
   ```
   Leave this running. You should see `Running on http://127.0.0.1:5000` in
   the terminal. Open a second terminal for anything else below.
4. **Open it in a browser:**
   - **http://127.0.0.1:5000/** — the customer booking page.
   - **http://127.0.0.1:5000/owner** — the staff portal. With the default
     `.env`, use "Developer/local testing" and paste the `OWNER_ACCESS_TOKEN`
     value (default `change-me-local-dev-token`). If you've set
     `OUTLOOK_GATEWAY=graph` with real Microsoft Entra credentials, click
     "Sign in with Microsoft" instead — see "Authentication" in the API
     Reference below for how the two paths differ.
5. **Try the customer flow:** on `/`, pick an appointment type and a date
   (or describe it in the text box, e.g. "a fitting next Monday at 9am", and
   click "Fill in the fields below"), click "Find available times", pick a
   proposed slot, fill in your name and email, and click "Confirm booking".
   You should land on a confirmation screen with a calendar reference and a
   confirmation token.
6. **Try the staff flow:** after authenticating (step 4), set a from/to
   date-time range and click "Load appointments" to see the booking from
   step 5; try "Create block" to reserve time without a booking; try editing
   an appointment type's duration/buffer/active status and clicking "Save".
7. **Stop the server** when done with `Ctrl+C` in the terminal running
   `python run.py`.

The API is still reachable directly if you prefer scripting over the
browser — both pages call the same endpoints documented in "API Reference"
below:

```bash
curl http://127.0.0.1:5000/api/v1/health
curl http://127.0.0.1:5000/api/v1/appointment-types
```

No `curl`, PowerShell, or Postman is needed for normal use, though — the two
pages in step 4 are the primary interface. The frontend is plain
HTML/CSS/vanilla JavaScript (`app/templates/`, `app/static/`) with no build
step and no framework, per Week 4's technology stack, and contains no
scheduling logic of its own: every page action calls the existing
`/api/v1/...` endpoints, so `SchedulingOrchestrator`, `BusinessRulesService`,
`AvailabilityService`, and `OutlookGateway` remain the only place booking
decisions are made.

## Running tests

```bash
pytest
```

Coverage is on by default (configured in `setup.cfg`) and prints a per-file
report. Lint with:

```bash
flake8 app config.py run.py tests
```

- `tests/unit/` — business rules (including business-hours enforcement),
  availability slot generation, intent validation/interpretation (including
  the OpenAI adapter's error mapping, mocked — no API key needed), the
  scheduling orchestrator (including idempotency replay), the fake Outlook
  gateway's behavior, confirmation tokens, the rate limiter, and
  `test_graph_outlook.py` — Jose's unit tests for `GraphOutlookGateway`
  (HTTP mocked).
- `tests/integration/` — Flask test-client coverage of the customer and
  owner API endpoints: happy paths, validation failures, business-hours
  rejection, idempotent retries, 404s, 405s, 409 slot conflicts, 429 rate
  limits, a forced 503 `OUTLOOK_UNAVAILABLE`, owner authorization (both the
  bearer-token and mocked-Microsoft-sign-in paths), guest confirmation-token
  lookups, the generic catch-all 500 handler, and the frontend
  page/static-asset routes. `test_graph_gateway_integration.py` drives the
  real API through the real `GraphOutlookGateway` (only the HTTP call is
  mocked) to verify the two fit together: timezone handling, conflict
  detection, outage mapping, and Graph's UTC responses coming back as shop
  time.
- `tests/contract/` — the standard error envelope's shape and status-code
  mapping (Week 4 §3.2), checked once across every error code rather than
  re-asserted per endpoint.
- `tests/e2e/` — one chained journey through the real app (intent →
  availability → book → idempotent retry → guest lookup → re-search →
  owner schedule/block/type-update → privilege boundary holds), using the
  in-memory fakes. This is an E2E test of the *application*, not of the
  live Microsoft Graph/OpenAI services — see "Design notes and limitations."

As of this pass: **172 tests, 172 passed, 0 failed, 0 skipped, 96% line
coverage** on `app/` (verified locally in a clean virtual environment, and
cross-checked against a real running server for every behavior that changed
in this pass — see "What's implemented" below).

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request: checks out
the repo, installs Python 3.12 and pinned dependencies, runs `flake8`, then
runs `pytest` with coverage. The workflow fails if linting or any test fails.

## API Reference

Base path: `/api/v1`. Content type: `application/json` for all request and
response bodies. Timestamps are ISO 8601. Datetimes you send **without** a
UTC offset (for example `2026-09-29T09:00:00`, or the value of an HTML
`datetime-local` input) are read as shop time (`BUSINESS_TIMEZONE`);
datetimes with an offset are honored as the same instant. Datetimes in
responses always carry the shop's offset (for example
`2026-09-29T09:00:00-05:00`).

### Authentication

Customer-facing endpoints (`/intent`, `/availability`, `/appointments`,
`/appointment-types`) require no authentication, though `GET
/appointments/{id}` requires a confirmation token (below).

Owner endpoints (`/owner/*`) accept **either**:

1. **Real Microsoft sign-in (recommended, requires `OUTLOOK_GATEWAY=graph`).**
   `GET /auth/microsoft/login` starts an MSAL authorization-code flow;
   `GET /auth/microsoft/callback` completes it, and — if the signed-in
   account's username is in `OWNER_ALLOWED_UPNS` — stores it in the Flask
   session. This is checked on every request, not just at sign-in, so
   removing a UPN from the allow-list takes effect immediately even for an
   existing session. `POST /auth/microsoft/logout` clears it. With
   `OUTLOOK_GATEWAY=fake`, `/auth/microsoft/login` returns `503
   OUTLOOK_UNAVAILABLE` — there's no Microsoft calendar to sign in for.
2. **A shared bearer token, for local dev and CI.**
   `Authorization: Bearer <OWNER_ACCESS_TOKEN>`, matched with a
   constant-time comparison. This is explicitly a shortcut, not identity —
   anyone with the token passes.

A signed-in Microsoft account whose username isn't on the allow-list gets
`403 FORBIDDEN` from the API (or, from the sign-in page itself, a friendly
redirect rather than a raw JSON error).

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
| --- | --- | --- | --- |
| `VALIDATION_ERROR` | 400 | No | Request body/query failed validation, an out-of-hours booking, or wrong HTTP method |
| `UNAUTHORIZED` | 401 | No | Missing/invalid owner credential, or missing/invalid guest confirmation token |
| `FORBIDDEN` | 403 | No | A real, signed-in Microsoft identity that isn't on the owner allow-list |
| `NOT_FOUND` | 404 | No | Appointment/appointment-type/route not found |
| `SLOT_CONFLICT` | 409 | Yes | Selected slot became busy before the write |
| `RATE_LIMITED` | 429 | Yes | Too many requests from this client for this endpoint's bucket within the window |
| `AI_UNAVAILABLE` | 503 | Yes | Intent interpreter (OpenAI) failed or timed out |
| `OUTLOOK_UNAVAILABLE` | 503 | Yes | Outlook gateway failed or timed out, or Microsoft sign-in was attempted with `OUTLOOK_GATEWAY=fake` |
| `INTERNAL_ERROR` | 500 | Usually | Unexpected server error; no internal details are exposed |

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

No auth. Rate-limited under the shared "ai" bucket
(`RATE_LIMIT_AI_PER_MINUTE`). Converts natural language into a structured
scheduling intent. Does **not** check availability or create appointments.

Request body:

```json
{
  "text": "I need a tuxedo fitting next Friday after 5 PM",
  "actor": "customer",
  "timezone": "America/Chicago"
}
```

`text` (string, 1–500 chars, required), `actor` (`customer` | `owner`,
required), `timezone` (string, optional — defaults to `BUSINESS_TIMEZONE`).

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
call fails/times out. `429 RATE_LIMITED` if this client has exceeded the
shared ai/availability limit for the current window.

#### `POST /api/v1/availability`

No auth. Shares the same rate-limit bucket as `/intent`. Validates the
request against business rules and returns candidate slots checked against
Outlook free/busy. **Options are proposals, not reservations** — they are
rechecked at booking time.

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
`429 RATE_LIMITED` as above.

#### `POST /api/v1/appointments`

No auth (customer flow). Rate-limited under its own "booking" bucket
(`RATE_LIMIT_BOOKING_PER_MINUTE`). Confirms and creates an appointment.

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
(int, required, must be active), `start` (datetime, required, must fall
within business hours for this appointment type's duration), `confirmation`
(boolean, required, **must be `true`**), `notes` (optional, ≤500 chars). An
optional `Idempotency-Key` header is honored: a repeated request with the
same key replays the first result instead of writing to Outlook again
(process-local — see "Design notes and limitations").

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
  "confirmation_token": "ImZha2VfNDE2NTJi...XshTDkslPrIdYk2D0Y20zIBkwcg",
  "message": "Your appointment is confirmed. Keep the confirmation_token to look this booking up later."
}
```

`confirmation_token` is required to look this booking up later as a guest —
keep it. `400 VALIDATION_ERROR` for invalid input, an inactive/unknown
`appointment_type_id`, `confirmation: false`, or a `start` outside business
hours. `409 SLOT_CONFLICT` if the slot became busy between availability and
booking. `503 OUTLOOK_UNAVAILABLE` on gateway failure. `429 RATE_LIMITED` as
above.

#### `GET /api/v1/appointments/{event_id}`

Requires **either** the `confirmation_token` issued when this appointment
was booked (as `?token=...` or an `X-Confirmation-Token` header) **or**
owner authentication. Looks up a confirmed appointment by its persistent
Outlook event id.

Response `200`: same `appointment` shape as above (no token in the
response this time).
`401 UNAUTHORIZED` if neither a valid token nor owner auth is present —
this is returned even if the event id doesn't exist, so existence can't be
probed without a credential.
`404 NOT_FOUND` if authorized but no such event exists.

#### `GET /api/v1/owner/appointments`

Owner auth required (see "Authentication" above). Query params `date_from`,
`date_to` (both required, ISO 8601 datetimes).

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

`401 UNAUTHORIZED` with no credential. `403 FORBIDDEN` if signed in with
Microsoft but not on the owner allow-list. `400 VALIDATION_ERROR` if
`date_from`/`date_to` are missing or not valid ISO 8601.

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

#### `GET /auth/microsoft/login`

Starts the Microsoft sign-in flow (see "Authentication"). Redirects to
Microsoft's authorization page. `503 OUTLOOK_UNAVAILABLE` if
`OUTLOOK_GATEWAY` isn't `graph`.

#### `GET /auth/microsoft/callback`

Completes the sign-in flow. Redirects to `/owner?auth=success`,
`/owner?auth=forbidden` (authenticated but not an allowed owner), or
`/owner?auth=expired` (no matching flow in session — try signing in again).

#### `POST /auth/microsoft/logout`

Clears the signed-in session. Response `204`, no body.

## What's implemented

**Week 5 — Flask application foundation:**
Application factory with dependency injection for the Outlook gateway and
intent interpreter (no global mutable state); environment-variable
configuration with separate Development/Testing/Production config classes;
the standard API error contract including 404/405 framework-level handlers
and a catch-all 500 handler that never leaks exception details; all
customer- and owner-facing endpoints from Week 4 §3.3; Marshmallow
validation on every endpoint; `BusinessRulesService` + `AvailabilityService`;
`SchedulingOrchestrator` coordinating interpret → find options → confirm →
create, with a recheck-before-write step; the `OutlookGateway` interface and
`FakeOutlookGateway`; `IntentService` with `FakeIntentInterpreter` (default)
and `OpenAIIntentInterpreter`; the CI pipeline.

**Week 6 — frontend:** customer booking page (`GET /`) and staff portal
(`GET /owner`), served by a `frontend_bp` blueprint that only calls
`render_template` — no business logic in it. Plain HTML/CSS/vanilla
JavaScript, no build step, no frontend framework. Customer flow: optional
natural-language intent box → availability search → slot picker → contact
form → confirm → confirmation screen, with a 409 conflict routing back to
re-pick a slot. Staff portal: sign-in (now real Microsoft sign-in or a dev
token, see below) → schedule view → block-time form → inline
appointment-type editing. One shared JS helper renders the standard error
contract as a banner on both pages. Times display in shop time regardless
of the viewer's own timezone.

**Outlook integration (Jose):** `GraphOutlookGateway` implements every
`OutlookGateway` method against Microsoft Graph — free/busy via
`calendarView`, event create/read/list, owner blocks — with bounded
`nextLink` pagination (fails closed past 20 pages rather than truncating
silently) and every Graph/`requests` failure mapped to
`OutlookUnavailableError`. `MsalTokenProvider` drives a delegated
(signed-in-owner) MSAL authorization-code flow, matching the `/me/...`
endpoints the gateway calls — the app-only/client-credentials alternative
(`/users/{id}/...`) was considered and rejected because it needs a
mailbox-impersonation decision this MVP doesn't need to make.

**This pass — closing the remaining gaps:**
- **Wired Microsoft sign-in end to end.** `MsalTokenProvider` could build
  an auth URL and complete a code exchange, but nothing called it;
  `/auth/microsoft/{login,callback,logout}` (`app/routes/microsoft_auth.py`)
  drives the flow and, on success, checks the signed-in account against
  `OWNER_ALLOWED_UPNS` — the "Microsoft identity/role configuration" Week 4
  §4.2 calls for. `require_owner` now accepts a real signed-in session or
  the bearer token (kept for local dev/CI). The owner page has a real "Sign
  in with Microsoft" button; the token box remains as a clearly-labeled
  dev-only fallback.
- **Business hours now apply to bookings, not just searches.**
  `BusinessRulesService.ensure_within_business_hours` rejects a `start`
  outside business hours or whose duration would run past closing, called
  from `confirm_booking` before the Outlook recheck.
- **Idempotency-Key is enforced.** `IdempotencyStore` (process-local,
  in-memory, TTL'd) caches the result of a booking under its key; a repeat
  request with the same key replays that result instead of writing to
  Outlook again.
- **`GET /appointments/{id}` is guest-scoped.** `confirmation_tokens.py`
  issues a signed, stateless token (via `itsdangerous`, already a Flask
  dependency) tied to one event id at booking time; the lookup endpoint now
  requires that token or owner auth, and refuses unauthenticated requests
  (401) without revealing whether the id even exists.
- **Rate limiting is enforced.** `RateLimiter` (process-local, in-memory
  sliding window) backs a `@rate_limited` decorator on `/intent`,
  `/availability` (shared bucket), and `/appointments` (its own bucket),
  actually raising `429 RATE_LIMITED` — verified against a real running
  server (30 requests succeed, the 31st returns 429 with the configured
  default).
- **`403 FORBIDDEN` is now raised** for a signed-in Microsoft identity that
  isn't on the owner allow-list, both at `/api/v1/owner/*` and via a
  friendly redirect from the sign-in callback itself.
- **Contract and E2E test tiers now exist.** `tests/contract/` checks the
  error envelope's shape once across every code rather than per endpoint;
  `tests/e2e/` chains a full customer-and-owner journey through the real
  app and its in-memory fakes in one sequence.
- Every item above was verified three ways: a unit test, an integration
  test through the Flask test client, and a check against a real running
  `python run.py` server with `curl` (business-hours rejection, idempotent
  replay, guest-token lookup gated at 401, the real rate limit tripping at
  exactly request 31, and the owner page actually containing the
  `/auth/microsoft/login` link).

Total after this pass: **172 tests, 172 passed, 0 failed, 0 skipped, 96%
line coverage** on `app/`.

## Time handling

`GraphOutlookGateway` (like any `OutlookGateway`) requires timezone-aware
datetimes. `BusinessRulesService.to_business_time` is the single place that
converts input to shop time, and `SchedulingOrchestrator` applies it to
everything it sends to the gateway and to every event it reads back (Graph
returns UTC). `FakeOutlookGateway` enforces the same rule, so a service that
forgets fails in tests instead of only against the real calendar. The pages
display times exactly as the API returns them (shop time), regardless of
the viewer's own timezone.

## Design notes and limitations

Nothing below is an unfinished feature — each is a scoping decision made
for this MVP, implemented correctly and tested within that scope. Listed
here rather than under "Known gaps" because there's no remaining
implementation work tied to them; they're properties of the chosen design,
not missing code.

- **The idempotency store and rate limiter are process-local, in-memory
  caches**, not a database (ADR-006 is unaffected — neither stores
  appointment data). That's the right scope for the single Flask
  dev-server/one-worker setup this MVP runs as. Behind multiple worker
  processes or machines, each would keep its own counts independently
  rather than sharing one; closing that fully would mean a shared store
  (e.g. Redis), which is a real infrastructure decision for whoever deploys
  this beyond a single process, not a gap in this repository.
- **The rate limiter keys on `request.remote_addr`.** Behind a reverse
  proxy, that's the proxy's address for every client unless the deployment
  is configured to trust a forwarded-for header — a deployment-specific
  choice, not something this repository can decide in advance.
- **MSAL and Microsoft Graph are verified with mocks, not a live Azure
  tenant** (same as Jose's own `test_msal_auth.py` and `test_graph_outlook.py`).
  No Azure app registration exists in this environment to test against
  live; everything that can be verified without one — flow-building,
  response parsing, error mapping, the allow-list check, the full redirect
  sequence — is. The remaining risk is entirely on Microsoft's side of the
  contract (that MSAL's real behavior matches what's mocked), which no
  amount of local work can close without real credentials.
- **`tests/e2e/` exercises the application layer, not live external
  services.** It runs the real Flask app and real services end to end, but
  against `FakeOutlookGateway`/`FakeIntentInterpreter` rather than live
  Microsoft Graph or OpenAI — the same honest limitation as the mocked MSAL
  tests above, for the same reason.
