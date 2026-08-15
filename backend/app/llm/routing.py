"""Chain resolution.

A task resolves to an ordered list of rungs — primary first, then each configured fallback.
Rungs are pruned before dispatch, so the gateway's dispatch loop stays a plain walk over
whatever survived and every policy decision lives here.

Two things prune a rung, for different reasons:

* an **open circuit breaker** — that provider is known to be rate-limiting, so spending a
  request on it wastes time the whole cycle is waiting for;
* an **exhausted budget** — but only for rungs that actually cost money. A spend cap must not
  disable the free local model that could still answer.

Pruning is not vetoing. A task whose primary is unavailable should be served by its fallback,
not fail — that distinction is the whole point of having a chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.settings import Settings
from app.llm.providers import LOCAL_PROVIDERS, resolve_base_url


class SkipReason(StrEnum):
    BREAKER_OPEN = "breaker_open"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class Rung:
    """One `<provider>/<model>` target in a task's chain."""

    target: str
    provider: str
    model: str
    api_base: str | None
    #: Local providers report no cost and are exempt from the spend cap.
    is_local: bool
    #: Position in the chain; 0 is the primary.
    index: int

    @property
    def is_fallback(self) -> bool:
        return self.index > 0


@dataclass(frozen=True, slots=True)
class Chain:
    task: str
    requested: str
    """The primary target, i.e. what configuration says this task *should* use."""

    rungs: list[Rung]
    """Rungs that survived pruning, in order."""

    skipped: list[tuple[Rung, SkipReason]]
    """Pruned rungs and why — recorded so a silent skip is never invisible."""

    @property
    def is_empty(self) -> bool:
        return not self.rungs

    @property
    def dominant_skip_reason(self) -> SkipReason | None:
        """Why an empty chain is empty.

        Budget wins when both apply: "you hit your spend cap" is the actionable message, and a
        breaker that opened earlier is a side effect the operator can do nothing about.
        """
        reasons = {reason for _, reason in self.skipped}
        if SkipReason.BUDGET_EXCEEDED in reasons:
            return SkipReason.BUDGET_EXCEEDED
        if SkipReason.BREAKER_OPEN in reasons:
            return SkipReason.BREAKER_OPEN
        return None


def _to_rung(settings: Settings, target: str, index: int) -> Rung:
    provider, _, model = target.partition("/")
    return Rung(
        target=target,
        provider=provider,
        model=model,
        api_base=resolve_base_url(settings, provider),
        is_local=provider in LOCAL_PROVIDERS,
        index=index,
    )


def resolve_chain(
    settings: Settings,
    task: str,
    *,
    is_breaker_open,
    budget_exhausted: bool,
) -> Chain:
    """Build a task's chain and prune the rungs that cannot run.

    ``is_breaker_open`` is a callable taking a provider name, so this stays testable without
    constructing a breaker.
    """
    targets = settings.chain_for_task(task)
    all_rungs = [_to_rung(settings, target, index) for index, target in enumerate(targets)]

    usable: list[Rung] = []
    skipped: list[tuple[Rung, SkipReason]] = []

    for rung in all_rungs:
        if budget_exhausted and not rung.is_local:
            skipped.append((rung, SkipReason.BUDGET_EXCEEDED))
            continue
        if is_breaker_open(rung.provider):
            skipped.append((rung, SkipReason.BREAKER_OPEN))
            continue
        usable.append(rung)

    return Chain(
        task=task,
        requested=targets[0] if targets else "",
        rungs=usable,
        skipped=skipped,
    )
