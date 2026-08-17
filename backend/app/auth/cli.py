"""Creating the first user.

A system that requires a login and has no users is a locked room, so there has to be a way in
— and it is deliberately an explicit command rather than an account created at startup from
environment variables. A default admin conjured silently on first boot is the classic way an
unlocked door reaches production, because nobody remembers it exists to remove it.

    python -m app.auth.cli create-user <username>
    python -m app.auth.cli set-password <username>
    python -m app.auth.cli list-users
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.auth.passwords import MIN_PASSWORD_LENGTH, WeakPassword
from app.auth.service import AuthService
from app.core.settings import Settings
from app.persistence.session import make_engine, make_session_factory

#: Read when a prompt is not available — CI, a container, a scripted first run.
BOOTSTRAP_ENV = "AUTH_BOOTSTRAP_PASSWORD"


def _service() -> AuthService:
    settings = Settings()
    return AuthService(make_session_factory(make_engine(settings)), settings)


def _read_password(confirm: bool = True) -> str:
    from_env = os.environ.get(BOOTSTRAP_ENV)
    if from_env:
        return from_env

    if not sys.stdin.isatty():
        raise SystemExit(
            f"no terminal for a prompt; set {BOOTSTRAP_ENV} instead (it is read once and "
            "never stored)"
        )

    password = getpass.getpass("Password: ")
    if confirm and password != getpass.getpass("Confirm: "):
        raise SystemExit("passwords did not match")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.auth.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="create a user")
    create.add_argument("username")

    reset = sub.add_parser("set-password", help="change a user's password")
    reset.add_argument("username")

    sub.add_parser("list-users", help="list usernames")

    args = parser.parse_args(argv)
    service = _service()

    try:
        if args.command == "create-user":
            service.create_user(args.username, _read_password())
            print(f"created {args.username.strip().lower()}")
        elif args.command == "set-password":
            if not service.set_password(args.username, _read_password()):
                raise SystemExit(f"no user named {args.username!r}")
            # Changing a password is usually a response to it being compromised, so every
            # existing session is revoked rather than left running.
            print(f"password updated for {args.username}; all sessions revoked")
        else:
            print(f"{service.user_count()} user(s)")
    except WeakPassword:
        raise SystemExit(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        ) from None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
