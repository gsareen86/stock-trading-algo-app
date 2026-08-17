# authentication

## Intent

Put a login in front of the platform, so the API is not an open door to a portfolio, a broker
connection and a spend budget.

## Why

Every endpoint is currently unauthenticated. That was fine while the platform was a research
toy on localhost, and it stopped being fine three increments ago:

- `POST /books/{book}/fill` and `POST /insights/{id}/act` **write trades**
- `POST /cycles/run` spends money on LLM calls against a configured budget
- `GET /books/*` exposes an entire position book
- Kite MCP is configured with a broker session

Anything that can reach port 8000 can do all of that. On a laptop bound to `127.0.0.1` that is
one misconfiguration away from being a problem, and it is a hard blocker on ever running this
anywhere else.

## In scope

- **`trading.users`** — username, Argon2id password hash, active flag
- **`trading.refresh_tokens`** — so logging out actually invalidates something
- **JWT access tokens** (short-lived, `Bearer`) and **refresh tokens** (long-lived, revocable)
- **`POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me`**
- **Every endpoint protected by default** — the exceptions are named in code, not the rule
- **A bootstrap path** for the first user that does not involve editing the database by hand
- **Web**: a login page, token handling in the API client, redirect on 401

## Out of scope

- **Multi-user roles and permissions.** One person owns this book. Roles without a second kind
  of user is a permission system with nothing to permit, and it would need a spec of its own.
- **OAuth / social login.** Username and password was the ask, and a third-party identity
  provider for a single-user local app is more moving parts than it removes.
- **Password reset by email.** There is no mail channel and `insights-feed` deliberately did not
  add one. Rotation is a CLI concern for a single-user system.
- **Rate limiting as infrastructure.** A login attempt counter is in scope; a general-purpose
  limiter belongs with a deployment story that does not exist yet.

## Risks

- **A default signing secret is the classic way to ship an unlocked door.** There is no usable
  default: production refuses to start without one, and development generates an ephemeral
  secret per process, which invalidates tokens on restart — inconvenient, and safe.
- **JWTs cannot be un-issued.** Access tokens are therefore short-lived, and refresh tokens are
  checked against a stored record on every use so that logout revokes rather than merely
  forgets. A logout that invalidates nothing is theatre.
- **Adding auth to 20 existing endpoints invites missing one.** So the dependency is applied at
  the application level and exemptions are an explicit allowlist, with a test that walks the
  live route table and fails on any unlisted unprotected path.
