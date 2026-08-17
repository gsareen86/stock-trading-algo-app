# Tasks: authentication

## Spec
- [x] `proposal.md`, `design.md`, `tasks.md`
- [x] Deltas: authentication (new), platform-api (ADDED), platform-configuration (ADDED),
      data-persistence (ADDED), web-shell (ADDED)

## Persistence
- [x] `trading.users`, `trading.refresh_tokens` — migration `0005`, RLS + service_role policy
- [x] Argon2id hash column; never a plaintext or reversible field

## Auth core
- [x] `app/auth/passwords.py` — Argon2id hash and verify, dummy verify for unknown users
- [x] `app/auth/tokens.py` — issue and decode; `type` claim checked on every decode
- [x] `app/auth/service.py` — login, refresh with revocation, logout
- [x] `app/auth/deps.py` — `current_user`, applied application-wide
- [x] `AUTH_SECRET_KEY` — no default; prod refuses to start, dev generates per process

## API
- [x] `POST /auth/login`, `/auth/refresh`, `/auth/logout`; `GET /auth/me`
- [x] Refresh token in an httpOnly cookie; access token in the response body
- [x] Public paths as an explicit allowlist

## Bootstrap
- [x] `python -m app.auth.cli create-user` — prompt or `AUTH_BOOTSTRAP_PASSWORD`
- [x] No implicit account creation at startup

## Web
- [x] Login page; token held in memory, never `localStorage`
- [x] API client attaches the token, refreshes once on 401, then redirects

## Tests
- [x] Every route is protected or explicitly public — walked from the live route table
- [x] A refresh token is rejected where an access token is required
- [x] Logout revokes: the same refresh token stops working
- [x] Unknown user and wrong password are indistinguishable
- [x] Tampered and expired tokens are rejected
- [x] Prod without a secret refuses to start
- [x] Passwords are never returned by any endpoint
