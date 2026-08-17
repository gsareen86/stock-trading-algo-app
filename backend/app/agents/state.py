"""The cycle's state.

The reducers here are the isolation guarantee. Four strategy nodes run concurrently and each
contributes to ``verdicts`` through an additive reducer, which means no strategy node is ever
handed another's output — not because the code politely refrains, but because the graph does
not give it one.

That matters more than it looks. The predecessor's confluence scorecard did not start as a
decision to blend verdicts; it started as one function reading another's result for context.
An append-only fan-in makes that impossible to write by accident.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, TypedDict

from app.domain.instrument import Instrument
from app.domain.verdict import Verdict


@dataclass(frozen=True, slots=True)
class RegimeRead:
    """What the broader market is doing, read once and shared by every strategy.

    Shared *input*, not shared judgement: a hostile regime lowers conviction inside a strategy
    that cares about it and is ignored by strategies that do not. It never becomes a gate at
    this level, because a cycle-wide veto is a blended decision wearing a different hat.
    """

    trending: bool
    label: str
    detail: str
    source_ref: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "trending": self.trending,
            "label": self.label,
            "detail": self.detail,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing research turned up. Context for a narrative, never evidence for a gate."""

    tool: str
    ticker: str
    summary: str
    source_ref: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ticker": self.ticker,
            "summary": self.summary,
            "source_ref": self.source_ref,
        }


class CycleState(TypedDict, total=False):
    """State threaded through one cycle.

    ``verdicts`` and ``notes`` carry additive reducers because they are written by nodes running
    in parallel; everything else is written once, before the fan-out, and read-only after.
    """

    cycle_id: str
    as_of: datetime
    instruments: list[Instrument]
    #: Written by `regime`, read by every strategy. Never written by a strategy.
    regime: RegimeRead | None
    #: ticker -> findings. Written by `research`, read as context only.
    research: dict[str, list[Finding]]
    #: Append-only fan-in. The reducer is the isolation guarantee — see the module docstring.
    verdicts: Annotated[list[Verdict], operator.add]
    notes: Annotated[list[str], operator.add]
    narrate: bool
    #: What the screen decided, when one ran. Reported so an empty cycle is diagnosable.
    screen: dict[str, Any]
    #: Per-verdict risk decisions. A decision *about acting*; the verdicts are untouched.
    risk: list[dict[str, Any]]
    #: Written once by `narrate`, after the fan-in has closed. Separate from `verdicts` because
    #: that key's reducer appends: writing narrated copies back into it would duplicate every
    #: verdict rather than replace it. A node that must *replace* cannot share a key with one
    #: that accumulates.
    narrated: list[Verdict]
