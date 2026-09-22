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
| `OUTLOOK_GATEWAY` | `fake` (default) or `graph` | `graph` is the integration point for Jose's real Microsoft Graph gateway |
| `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`, `MS_GRAPH_TENANT_ID`, `MS_GRAPH_CALENDAR_ID` | Microsoft Graph credentials | used only once a real gateway is registered |
| `RATE_LIMIT_AI_PER_MINUTE`, `RATE_LIMIT_BOOKING_PER_MINUTE` | rate-limit config | not yet enforced in code (see "Known gaps" below) |

**Never commit your real `.env` file.**

## Database setup

None required. Per ADR-006, Outlook Calendar is the sole persistent
scheduling data store. Appointment types and business hours are
version-controlled application configuration (`app/config_store/`), not
database tables.

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

- `tests/unit/` — business rules, availability slot generation, intent
  validation, the scheduling orchestrator, and the fake Outlook gateway's
  error-mapping behavior.
- `tests/integration/` — Flask test-client coverage of the customer and
  owner API endpoints, including validation failures, 404s, 409 slot
  conflicts, and owner authorization.

## What's implemented (Week 5, Flask/application side)

- Flask application factory (`app/__init__.py`) with dependency injection
  for the Outlook gateway and intent interpreter — no global mutable state.
- Environment-variable configuration with separate `Development` /
  `Testing` / `Production` config classes.
- Standard API error contract (`app/errors/handlers.py`) covering
  `VALIDATION_ERROR`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`,
  `SLOT_CONFLICT`, `RATE_LIMITED`, `AI_UNAVAILABLE`, `OUTLOOK_UNAVAILABLE`,
  `INTERNAL_ERROR`.
- All endpoints from Week 4 §3.3: `/health`, `/intent`, `/availability`,
  `/appointments` (POST + GET by id), `/appointment-types`,
  `/owner/appointments`, `/owner/blocks`, `/owner/appointment-types/{id}`.
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
- Owner-route authorization via a bearer-token check
  (`app/routes/auth.py`), stubbed pending real Microsoft identity/role auth.
- 42 unit + integration tests, all passing.

## Known gaps / remaining integration work

These are explicitly **not** complete — do not treat them as done:

- **Real Microsoft Graph gateway.** `OutlookGateway` is only implemented by
  `FakeOutlookGateway`. Jose's real implementation should be added as
  (e.g.) `app/gateways/graph_outlook.py`, implementing the same interface,
  and registered in `app/__init__.py::_build_outlook_gateway` under
  `OUTLOOK_GATEWAY=graph`. No route or service code should need to change.
- **Real Microsoft identity/role-based owner auth.** The current
  `require_owner` check is a bearer-token placeholder, not MSAL/Entra.
- **Idempotency-Key enforcement.** The header is accepted and passed
  through `BookingCommand`, but nothing currently de-duplicates retried
  writes — there's no local database to store idempotency records against
  (see ADR-006), so this needs a decision (e.g. an Outlook extension
  property, or a small key-value store) before it's production-ready.
- **Rate limiting.** Config values exist (`RATE_LIMIT_*`) but are not yet
  enforced by the routes.
- **Contract/E2E test tiers.** Only unit and integration tests exist so far;
  the `contract/` and `e2e/` tiers from Week 4 §8.4 are not yet built out
  (they depend on the real Graph/OpenAI integrations to be meaningful).
