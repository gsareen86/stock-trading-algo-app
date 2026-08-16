"""What a tool is.

A tool is a *declared* capability: a manifest describing its contract plus a handler that
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

    UNKNOWN_TOOL = "unknown_tool"
    INVALID_INPUT = "invalid_input"
    INVALID_OUTPUT = "invalid_output"
    HANDLER_ERROR = "handler_error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Collaborators handed to a handler.

    Injected rather than imported so a tool is testable against a fake source, and so no tool
    quietly acquires its own database connection or HTTP client.
    """

    price_source: PriceSource | None = None
    calendar: MarketCalendar | None = None
    #: Overridable for tests that need a fixed "now".
    now: Callable[[], Any] | None = None
    #: Per-tool overrides — e.g. a recorded feed fetcher in place of the live one.
    fetchers: dict[str, Any] = field(default_factory=dict)


#: A handler receives validated arguments and the context, and returns output to be validated.
ToolHandler = Callable[[dict[str, Any], ToolContext], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolManifest:
    """A tool's full declaration."""

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
    handler: ToolHandler
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError(f"tool name must be alphanumeric/underscore, got {self.name!r}")
        if not self.summary:
            raise ValueError(f"tool {self.name} must declare a summary")


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The outcome of one invocation. Never an exception."""

    tool: str
    ok: bool
    data: dict[str, Any] | None = None
    reason: FailureReason | None = None
    error: str | None = None

    @classmethod
    def success(cls, tool: str, data: dict[str, Any]) -> ToolResult:
        return cls(tool=tool, ok=True, data=data)

    @classmethod
    def failure(cls, tool: str, reason: FailureReason, error: str) -> ToolResult:
        return cls(tool=tool, ok=False, reason=reason, error=error)

    @property
    def items(self) -> list[dict[str, Any]]:
        """Convenience for the common `{"items": [...]}` output shape."""
        if not self.ok or not self.data:
            return []
        found = self.data.get("items")
        return found if isinstance(found, list) else []


@dataclass(frozen=True, slots=True)
class ToolLoadFailure:
    """A tool directory that could not be imported.

    Recorded rather than swallowed: a capability that vanished because of a typo should not
    look like one that was never written.
    """

    module: str
    error: str
