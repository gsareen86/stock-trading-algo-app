# Dashboard & API

Status: baseline — not yet exercised through a change under `openspec/changes/`.

The FastAPI backend (~101 routes, `api/server.py`) and the React dashboard it serves
(`frontend/`, 12 pages). Scoped to what's true of this layer itself — request handling,
auth posture, page inventory — not a second description of other capabilities' business
logic, which each route mostly just calls into.

## Requirements

### Requirement: No authentication, CORS open to any origin
The system MUST be understood as having no login, API key check, session, or JWT
anywhere in `api/server.py`, and CORS configured with `allow_origins=["*"]`. This is
documented, intentional current behavior for a single-user, local-trust-boundary app —
not an oversight to silently patch.

#### Scenario: Any origin can call the API
- GIVEN the server is reachable on the network (not just `localhost`)
- WHEN a request arrives from any origin with any credentials
- THEN it is served — there is no per-request identity or origin check anywhere in the
  API layer

### Requirement: Twelve dashboard pages, grouped into four sidebar sections
The system MUST present exactly these pages, matching `frontend/src/nav.ts`: **Portfolio**
(Overview, Performance), **Trading Books** (Intraday, Swing, Long-Term), **Research**
(Research & Guidance, News & Alerts, Fundamentals), **Engine** (Control Center, Engine
Room, LLM Usage, System Logs). This list is current and accurate as of this spec (unlike
some of the README's older strategy tables — see `openspec/project.md`).

#### Scenario: A capability's spec changes its data shape
- GIVEN a capability (e.g. `specs/positional-swing-trading`) changes what a field means
  or adds a new one
- WHEN the corresponding page (Swing) is expected to reflect it
- THEN the page inventory here doesn't change — only the owning capability's spec and the
  route(s) it exposes change; this list only drifts if a page is added, removed, or moved
  between sidebar groups

### Requirement: Long-running operations are triggered, not synchronous
The system MUST expose manual triggers for long-running operations (run cycle, run scan,
refresh research, sync universe, refresh event/surveillance calendars, compute outcomes,
run the LT book pass) as POST endpoints that kick off background work, consistent with
the Control Center UI presenting them as fire-and-forget buttons rather than
request/response actions with an immediate result.

#### Scenario: User clicks "Run Scan" in Control Center
- GIVEN the positional EOD scan takes longer than a typical HTTP request/response cycle
- WHEN the user clicks the "Run Scan" button
- THEN the API returns promptly (scan kicked off in the background) rather than holding
  the HTTP connection open until the scan finishes

## Known gaps / gotchas

- No versioning scheme on the ~101 `/api/*` routes — a breaking change to any endpoint's
  shape is a breaking change for the frontend immediately, with no compatibility window.
- This spec intentionally does not enumerate all ~101 routes — most are thin
  pass-throughs into the capability that owns the underlying logic (e.g. `/api/positional/*`
  routes belong conceptually to `specs/positional-swing-trading`). Route-by-route detail
  belongs in the owning capability's spec if/when that capability is touched, not
  duplicated here.

## Source modules

`api/server.py` (2,630 lines), `frontend/src/` (App.tsx, nav.ts, api.ts, `pages/*`,
`components/ui.tsx`).
