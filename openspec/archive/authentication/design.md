# Design: authentication

## 1. Protected by default, exempt by allowlist

The dangerous way to add auth to an existing API is to decorate the endpoints that need it,
because the failure mode is silent: a new router added later is simply open, and nothing says
so.

So the dependency is applied to the **application**, and the exemptions are a named list:

```python
PUBLIC_PATHS = {"/", "/health", "/auth/login", "/auth/refresh", "/docs", "/openapi.json", ...}
```

A test walks the *live* route table and fails on any path that is neither protected nor listed.
That turns "someone added an endpoint and forgot" from an invisible hole into a red test — and
it is the only mechanism here that keeps working without anyone remembering it.

`/health` stays public deliberately: a health check that requires a credential cannot tell a
monitor the difference between "down" and "misconfigured".

## 2. Two tokens, because one cannot be both short-lived and convenient

| | Access | Refresh |
|---|---|---|
| Lifetime | 30 minutes | 14 days |
| Carried in | `Authorization: Bearer` | httpOnly cookie |
| Revocable | no | yes — checked against a stored row |
| Contains | subject, expiry, type | subject, expiry, type, `jti` |

A JWT cannot be un-issued, which is the honest constraint to design around rather than ignore.
Access tokens are short enough that the window after a logout is small; refresh tokens carry a
`jti` matched against `trading.refresh_tokens` on every use, so logout deletes a row and the
token stops working immediately.

**The `type` claim is checked.** Without it, a refresh token is a valid signature over a valid
subject and would be accepted as an access token — a long-lived credential where a short-lived
one was intended. That is a real vulnerability class, not a hypothetical.

Refresh lives in an httpOnly cookie so script running on the page cannot read it; the access
token is held in memory by the client and never written to `localStorage`, which is readable by
any injected script.

## 3. Argon2id, and no user enumeration

Argon2id via `argon2-cffi` — memory-hard, the current recommendation, and it carries its own
parameters in the hash so they can be raised later without a migration.

Login returns the same error and takes comparable time whether the username is unknown or the
password is wrong. A missing user still runs a hash verification against a dummy hash, because
returning early on "no such user" is a timing oracle that turns a login form into a username
directory.

## 4. There is no default secret

`AUTH_SECRET_KEY` has no usable default:

- **prod**: refuses to start without it. A platform that boots with a well-known signing key is
  one where every token is forgeable by anyone who has read this repository.
- **dev/test**: generates a random secret per process. Tokens do not survive a restart, which is
  mildly annoying and cannot be mistaken for a production configuration.

## 5. Bootstrapping the first user

A system that requires a user to log in and has no users is a locked room. The first user is
created by an explicit command:

```
python -m app.auth.cli create-user <username>
```

reading the password from a prompt or `AUTH_BOOTSTRAP_PASSWORD`. Not auto-created on startup
from environment variables alone: a default admin account created silently is the other classic
way to ship an unlocked door, and it tends to survive into production.

## 6. What the web does

The API client attaches the access token, and on a 401 tries `/auth/refresh` **once** before
redirecting to the login page. Once, because a refresh loop against an expired session is how a
login page becomes an infinite redirect.
