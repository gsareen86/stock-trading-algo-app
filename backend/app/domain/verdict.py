"""The decision model.

One strategy's independent opinion about one instrument, and the evidence behind it.

The rules this module enforces are the reason the platform is shaped as it is. Running four
strategies and collapsing them into a single blended score lets a strong score outvote a
failed hard gate, and leaves nobody able to say which strategy liked a name or why.
Both failures are prevented here by the *shape of the types* rather than by discipline:

* a failed hard gate forces ``AVOID`` inside the constructor, so no code path produces a
  ``BUY`` with a failing gate;
* a verdict with no evidence, or a gate citing evidence that does not exist, will not build.

There is deliberately **no function anywhere that combines verdicts**. Cross-strategy agreement
may be displayed; it is never computed into a decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.core.clock import now_utc

#: Bare numbers inside free text — used to read a metric's own name ("200-day", "52-week").
_NUMBER_IN_TEXT = re.compile(r"\d+(?:\.\d+)?")


def _numbers_in(text: str | None) -> set[float]:
    if not text:
        return set()
    return {float(match) for match in _NUMBER_IN_TEXT.findall(text)}


class Stance(StrEnum):
    """What a strategy would do. Never a number, never blended."""

    BUY = "BUY"
    WATCH = "WATCH"
    AVOID = "AVOID"


class Operator(StrEnum):
    """How an observed value was compared to its threshold.

    ``INFO`` exists so contextual measurements — the last close, a contraction count — can be
    recorded without inventing a threshold for them. Forcing every row into pass/fail would
    either drop that context or fabricate a test that was never applied.
    """

    GTE = ">="
    LTE = "<="
    GT = ">"
    LT = "<"
    EQ = "=="
    IN = "in"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One measured fact, with the comparison that was made to it.

    Carrying ``threshold`` and ``operator`` alongside ``value`` is what makes a row
    self-explaining. "RS was 12.4%" is a number; "RS 12.4% >= 0% required — passed" is an
    argument, and the narrative layer can render the second without inventing anything.
    """

    id: str
    label: str
    value: float | int | str | None
    source_ref: str
    operator: Operator = Operator.INFO
    threshold: float | int | str | None = None
    #: ``None`` for informational rows that assert nothing.
    passed: bool | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("evidence id must be non-empty")
        if not self.source_ref.strip():
            # Without this the traceability chain breaks silently: a narrative could cite a
            # row that leads nowhere, which is worse than no citation.
            raise ValueError(f"evidence {self.id!r} must carry a source_ref")
        if self.operator is Operator.INFO and self.passed is not None:
            raise ValueError(
                f"evidence {self.id!r} is informational but claims a pass state; "
                "give it a real operator or leave passed as None"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "operator": self.operator.value,
            "threshold": self.threshold,
            "passed": self.passed,
            "unit": self.unit,
            "source_ref": self.source_ref,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Evidence:
        return cls(
            id=payload["id"],
            label=payload.get("label", payload["id"]),
            value=payload.get("value"),
            source_ref=payload["source_ref"],
            operator=Operator(payload.get("operator", "info")),
            threshold=payload.get("threshold"),
            passed=payload.get("passed"),
            unit=payload.get("unit"),
        )


@dataclass(frozen=True, slots=True)
class GateResult:
    """A hard pass/fail check, recorded separately from any score.

    Gates answer *may we*; conviction answers *how much*. One number answering both is how a
    failed gate gets averaged away.
    """

    id: str
    label: str
    passed: bool
    reason: str
    #: Evidence rows backing this outcome. A gate citing nothing is a claim with no support.
    evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "passed": self.passed,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GateResult:
        return cls(
            id=payload["id"],
            label=payload.get("label", payload["id"]),
            passed=bool(payload["passed"]),
            reason=payload.get("reason", ""),
            evidence_ids=tuple(payload.get("evidence_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class Verdict:
    """One strategy's independent opinion on one instrument at one point in time."""

    strategy_id: str
    ticker: str
    as_of: datetime
    stance: Stance
    #: 0–100, meaningful **only within this strategy**. Not comparable across strategies —
    #: ranking on it across strategies would silently rebuild a blended scorecard.
    conviction: int
    evidence: tuple[Evidence, ...]
    gates: tuple[GateResult, ...] = ()
    #: Filled by `verdict-narratives`. A verdict is complete and reproducible without it.
    narrative: str | None = None
    trace_id: str | None = None
    created_at: datetime = field(default_factory=now_utc)

    def __post_init__(self) -> None:
        if not 0 <= self.conviction <= 100:
            raise ValueError(f"conviction must be 0-100, got {self.conviction}")

        if not self.evidence:
            # Nothing was measured. That is not a judgement — it is a bug that would otherwise
            # surface as a confident, unexplainable stance.
            raise ValueError(f"verdict for {self.ticker} by {self.strategy_id} carries no evidence")

        ids = [row.id for row in self.evidence]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            # A duplicated id makes a narrative citation ambiguous, and an ambiguous citation
            # is not a citation.
            raise ValueError(f"duplicate evidence ids: {sorted(duplicates)}")

        known = set(ids)
        for gate in self.gates:
            missing = [ref for ref in gate.evidence_ids if ref not in known]
            if missing:
                raise ValueError(f"gate {gate.id!r} cites evidence that does not exist: {missing}")

        if self.failed_gates and self.stance is not Stance.AVOID:
            # The rule this rebuild exists for. Not a warning, not a convention — a strong
            # score cannot outvote a failed hard gate, because such a verdict will not build.
            failed = ", ".join(g.id for g in self.failed_gates)
            raise ValueError(
                f"verdict for {self.ticker} has failing gate(s) [{failed}] so its stance must "
                f"be AVOID, not {self.stance.value}"
            )

    # ── derived ───────────────────────────────────────────────────────────────
    @property
    def failed_gates(self) -> tuple[GateResult, ...]:
        return tuple(gate for gate in self.gates if not gate.passed)

    @property
    def gates_passed(self) -> bool:
        return not self.failed_gates

    def evidence_by_id(self, evidence_id: str) -> Evidence | None:
        return next((row for row in self.evidence if row.id == evidence_id), None)

    @property
    def numeric_values(self) -> set[float]:
        """Every number this verdict actually measured.

        `verdict-narratives` checks generated prose against this set, so a narrative cannot
        contain a figure the verdict never established.
        """
        found: set[float] = set()
        for row in self.evidence:
            for candidate in (row.value, row.threshold):
                if isinstance(candidate, int | float) and not isinstance(candidate, bool):
                    found.add(float(candidate))
        return found

    @property
    def citable_numbers(self) -> set[float]:
        """Every number a narrative about this verdict is allowed to state.

        Wider than `numeric_values` by exactly the numbers the verdict already puts on the
        page without measuring them: those inside a metric's own name, and the conviction.
        "Price is above its 200-day moving average" cites a real row and is correct, but 200
        is in that row's *label*, not its value — rejecting it would fail well-written prose.

        Derived rather than kept as an allowlist of idiomatic constants: an allowlist is a
        guess about which numbers are legitimate, needs editing whenever a strategy adds a
        lookback, and would permit `50` in a narrative about a strategy that never mentions
        it. This permits exactly the numbers *this* verdict names.
        """
        allowed = self.numeric_values | {float(self.conviction)}
        for row in self.evidence:
            allowed |= _numbers_in(row.label)
            allowed |= _numbers_in(row.id)
            if isinstance(row.value, str):
                allowed |= _numbers_in(row.value)
        return allowed

    # ── narration ─────────────────────────────────────────────────────────────
    def with_narrative(self, narrative: str, trace_id: str | None = None) -> Verdict:
        """A copy carrying generated prose.

        Deliberately the only mutator, and deliberately unable to touch anything else. The
        LLM explains and never decides (principle 5) — that holds structurally because no code
        path exists by which narrating a verdict can alter a stance, a conviction, a gate or
        an evidence row.
        """
        return replace(self, narrative=narrative, trace_id=trace_id or self.trace_id)

    # ── serialisation ─────────────────────────────────────────────────────────
    def evidence_as_json(self) -> list[dict[str, Any]]:
        return [row.as_dict() for row in self.evidence]

    def gates_as_json(self) -> list[dict[str, Any]]:
        return [gate.as_dict() for gate in self.gates]
