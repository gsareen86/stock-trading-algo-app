"""What a skill is.

A skill is a *declared* capability: a manifest describing its contract plus a handler that
fulfils it. Declaring rather than exporting a function is what lets the same definition become
both an LLM tool and an entry in an A2A agent card, and what lets the contract be enforced
instead of documented.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.data.protocols import MarketCalendar, PriceSource


class FailureReason(StrEnum):
    """Why an invocation did not produce data.

    Distinct values because they have different owners: invalid input is the caller's problem,
    invalid output is the source's, and a handler error is ours. Collapsing them into a
    boolean would mean triaging every failure from scratch.
    """

    UNKNOWN_SKILL = "unknown_skill"
    INVALID_INPUT = "invalid_input"
    INVALID_OUTPUT = "invalid_output"
    HANDLER_ERROR = "handler_error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class SkillContext:
    """Collaborators handed to a handler.

    Injected rather than imported so a skill is testable against a fake source, and so no skill
    quietly acquires its own database connection or HTTP client.
    """

    price_source: PriceSource | None = None
    calendar: MarketCalendar | None = None
    #: Overridable for tests that need a fixed "now".
    now: Callable[[], Any] | None = None
    #: Per-skill overrides — e.g. a recorded feed fetcher in place of the live one.
    fetchers: dict[str, Any] = field(default_factory=dict)


#: A handler receives validated arguments and the context, and returns output to be validated.
SkillHandler = Callable[[dict[str, Any], SkillContext], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """A skill's full declaration."""

    name: str
    version: str
    #: One line. This is what a model reads when choosing between tools, competing for
    #: attention with every other tool in the prompt — so it stays short.
    summary: str
    #: Longer prose, for a human or an external agent reading the card. Separate from
    #: ``summary`` because collapsing them gives one audience the wrong length of text.
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: SkillHandler
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError(f"skill name must be alphanumeric/underscore, got {self.name!r}")
        if not self.summary:
            raise ValueError(f"skill {self.name} must declare a summary")


@dataclass(frozen=True, slots=True)
class SkillResult:
    """The outcome of one invocation. Never an exception."""

    skill: str
    ok: bool
    data: dict[str, Any] | None = None
    reason: FailureReason | None = None
    error: str | None = None

    @classmethod
    def success(cls, skill: str, data: dict[str, Any]) -> SkillResult:
        return cls(skill=skill, ok=True, data=data)

    @classmethod
    def failure(cls, skill: str, reason: FailureReason, error: str) -> SkillResult:
        return cls(skill=skill, ok=False, reason=reason, error=error)

    @property
    def items(self) -> list[dict[str, Any]]:
        """Convenience for the common `{"items": [...]}` output shape."""
        if not self.ok or not self.data:
            return []
        found = self.data.get("items")
        return found if isinstance(found, list) else []


@dataclass(frozen=True, slots=True)
class SkillLoadFailure:
    """A skill directory that could not be imported.

    Recorded rather than swallowed: a capability that vanished because of a typo should not
    look like one that was never written.
    """

    module: str
    error: str
