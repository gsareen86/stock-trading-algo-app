"""Generating a verdict's narrative.

Orchestrates build → call → validate → attach. Every failure path produces a verdict with
``narrative=None`` and no exception: an absent narrative is a supported state, and a cycle
must not end because a model was unavailable or wrote a number it could not support.

Nothing here can change a stance, a conviction, a gate or an evidence row. `with_narrative` is
the only mutator and it reaches exactly two fields — which is what makes "the LLM explains, it
never decides" structurally true rather than a convention.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.verdict import Verdict
from app.llm.types import LLMGateway
from app.narratives import guard
from app.narratives.prompts import build_messages

log = logging.getLogger(__name__)

NARRATIVE_TASK = "narrative"


class Outcome:
    """Why a verdict does or does not carry prose. Surfaced per verdict, never raised."""

    OK = "ok"
    UNAVAILABLE = "unavailable"
    EMPTY = "empty"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class NarrationResult:
    """The verdict as it should now be, plus what happened while narrating it."""

    verdict: Verdict
    outcome: str
    detail: str | None = None

    @property
    def narrated(self) -> bool:
        return self.outcome == Outcome.OK

    def as_dict(self) -> dict[str, str | None]:
        return {"outcome": self.outcome, "detail": self.detail}


async def narrate(verdict: Verdict, gateway: LLMGateway) -> NarrationResult:
    """Attach a validated narrative, or return the verdict untouched."""
    result = await gateway.complete(task=NARRATIVE_TASK, messages=build_messages(verdict))

    if result is None:
        # The gateway already failed soft and recorded why; nothing to add here.
        return NarrationResult(verdict, Outcome.UNAVAILABLE, "no model answered")

    text = (result.text or "").strip()
    if not text:
        return NarrationResult(verdict, Outcome.EMPTY, "model returned no text")

    verified = guard.check(text, verdict)
    if not verified.ok:
        # Discarded whole, never repaired: a narrative with a sentence removed is a text
        # nobody wrote, and resampling until something passes hides the very signal that a
        # model is inventing figures on this prompt.
        log.warning(
            "narrative rejected for %s/%s: %s",
            verdict.strategy_id,
            verdict.ticker,
            verified.reason,
        )
        return NarrationResult(verdict, Outcome.REJECTED, verified.reason)

    return NarrationResult(
        verdict.with_narrative(text, trace_id=result.trace_id), Outcome.OK
    )


async def narrate_all(
    verdicts: list[Verdict], gateway: LLMGateway
) -> tuple[list[Verdict], list[dict]]:
    """Narrate a batch, reporting each outcome alongside the verdicts.

    Sequential rather than gathered: these share one gateway, one budget and one circuit
    breaker, and firing a batch concurrently at a local model is the reliable way to make all
    of them slow instead of some of them done.
    """
    narrated: list[Verdict] = []
    report: list[dict] = []
    for verdict in verdicts:
        outcome = await narrate(verdict, gateway)
        narrated.append(outcome.verdict)
        report.append(
            {
                "strategy_id": verdict.strategy_id,
                "ticker": verdict.ticker,
                **outcome.as_dict(),
            }
        )
    return narrated, report
