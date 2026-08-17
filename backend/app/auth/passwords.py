"""Password hashing.

Argon2id: memory-hard, the current recommendation, and it encodes its own parameters into the
hash so they can be raised later without a migration or a flag day.

The dummy verification below is the part worth reading. Returning early when a username is
unknown makes login measurably faster for non-existent users than for real ones, which turns a
login form into a username directory. So an unknown user still pays for a hash verification
against a fixed dummy hash, and the caller cannot tell the two cases apart by timing or by
response.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

#: Defaults from `argon2-cffi`, which tracks the RFC 9106 recommendations.
_hasher = PasswordHasher()

#: A real Argon2id hash of a value nobody can log in with. Verified against when the username
#: does not exist, purely so that path costs the same as the real one.
_DUMMY_HASH = _hasher.hash("not-a-real-password-this-is-a-timing-equaliser")

#: Short enough to type, long enough not to be trivially guessed. Not a policy engine — one
#: person owns this book, and a complexity ruleset is how people end up with `Passw0rd!`.
MIN_PASSWORD_LENGTH = 12


class WeakPassword(ValueError):
    """The password does not meet the minimum length."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters, got {len(password)}"
        )
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Whether the password matches. A missing hash still costs a verification."""
    target = stored_hash or _DUMMY_HASH
    try:
        _hasher.verify(target, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:  # pragma: no cover - argon2 raising anything else is a bug, not a login
        return False
    return stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current defaults."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:  # pragma: no cover
        return False
