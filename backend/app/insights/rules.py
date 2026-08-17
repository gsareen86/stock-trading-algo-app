"""Generating insights from a cycle.

An insight is something that **changes what a person might do**. That test excludes most of
what a cycle produces: four AVOID verdicts on a name nobody holds is a complete, correct and
entirely unremarkable result, and putting it in a feed teaches people to ignore the feed.

Portfolio insights come first because they are the ones with a cost attached. `thesis_broken`
is the reason this module exists: a stock bought on a Minervini setup whose Minervini verdict
is now AVOID is the most actionable thing the platform can notice, and it can only be noticed
by joining verdicts to positions — which nothing did until now.

Nothing here fills, alters a verdict or changes a position. An insight links to what would act
and leaves the acting to `Ledger.fill()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.position import Position
from app.domain.verdict import Stance, Verdict
from app.insights.kinds import Kind, Severity, spec


@dataclass(frozen=True, slots=True)
class Candidate:
    """An insight before it is written. Deduplication happens on the way in."""

    kind: Kind
    title: str
    body: str
    dedupe_key: str
    ticker: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> Severity:
        return spec(self.kind).severity


def _pct(value: float) -> str:
    return f"{value:.1f}%"


# ── portfolio ─────────────────────────────────────────────────────────────────
def thesis_broken(
    positions: list[Position],
    verdicts: list[Verdict],
    bought_by: dict[str, tuple[str, ...]],
) -> list[Candidate]:
    """A held name whose own strategy now says AVOID.

    `bought_by` maps ticker to the strategies whose verdicts actually prompted the buys, taken
    from trade history. Matching on it is the point: the question is whether *the reason this
    was bought* still holds, not whether some other strategy dislikes it. A Minervini position
    is not invalidated by the long-term strategy's opinion, and treating any AVOID as a break
    would be exactly the cross-strategy blending this platform removed.

    Positions bought with no recorded strategy are skipped rather than matched against all four
    — there is no thesis on record to have broken.
    """
    held = {p.ticker: p for p in positions if p.is_open}
    out: list[Candidate] = []

    for verdict in verdicts:
        position = held.get(verdict.ticker)
        if position is None or verdict.stance is not Stance.AVOID:
            continue
        if verdict.strategy_id not in bought_by.get(verdict.ticker, ()):
            continue

        failed = ", ".join(g.label for g in verdict.failed_gates) or "criteria no longer met"
        out.append(
            Candidate(
                kind=Kind.THESIS_BROKEN,
                ticker=verdict.ticker,
                title=f"{verdict.ticker}: {verdict.strategy_id} now says AVOID",
                body=(
                    f"You hold {position.quantity} at ₹{position.average_cost:,.2f}, bought on "
                    f"a {verdict.strategy_id} setup. That strategy now rates it AVOID "
                    f"(conviction {verdict.conviction}). Reason: {failed}."
                ),
                dedupe_key=f"{Kind.THESIS_BROKEN}:{verdict.ticker}:{verdict.strategy_id}",
                payload={
                    "strategy_id": verdict.strategy_id,
                    "conviction": verdict.conviction,
                    "quantity": position.quantity,
                    "average_cost": position.average_cost,
                    "failed_gates": [g.id for g in verdict.failed_gates],
                },
            )
        )
    return out


def strategies_by_ticker(trades) -> dict[str, tuple[str, ...]]:
    """Which strategies prompted the buys for each ticker, from trade history.

    Derived rather than stored on the position: a position is a fold over trades, and adding a
    field to it that trades do not support would be the same mistake as an independently
    writable quantity.
    """
    out: dict[str, set[str]] = {}
    for trade in trades:
        if trade.side.value != "buy" or not trade.strategy_id:
            continue
        out.setdefault(trade.ticker, set()).add(trade.strategy_id)
    return {ticker: tuple(sorted(names)) for ticker, names in out.items()}


def concentration(positions: list[Position], cap_pct: float) -> list[Candidate]:
    """A holding above the concentration cap, measured on cost basis."""
    open_positions = [p for p in positions if p.is_open]
    total = sum(p.cost_basis for p in open_positions)
    if total <= 0:
        return []

    out: list[Candidate] = []
    for position in open_positions:
        weight = position.cost_basis / total * 100
        if weight <= cap_pct:
            continue
        out.append(
            Candidate(
                kind=Kind.CONCENTRATION,
                ticker=position.ticker,
                title=f"{position.ticker} is {_pct(weight)} of the book",
                body=(
                    f"₹{position.cost_basis:,.0f} of ₹{total:,.0f} committed sits in "
                    f"{position.ticker}, above the {_pct(cap_pct)} cap."
                ),
                # Banded so a position drifting from 31% to 32% does not re-raise daily.
                dedupe_key=f"{Kind.CONCENTRATION}:{position.ticker}:{int(weight // 5) * 5}",
                payload={
                    "weight_pct": round(weight, 2),
                    "cap_pct": cap_pct,
                    "cost_basis": position.cost_basis,
                },
            )
        )
    return out


def position_research(
    positions: list[Position], research: dict[str, list]
) -> list[Candidate]:
    """News, filings and events on things that are owned.

    **Quoted, never asserted.** A verdict's evidence is a measurement this platform made with a
    threshold and a comparison; a headline is something a model found. Anyone deciding whether
    to sell needs to know which of the two they are looking at, so these name the tool and carry
    its source reference.
    """
    held = {p.ticker for p in positions if p.is_open}
    out: list[Candidate] = []

    for ticker, findings in (research or {}).items():
        if ticker not in held:
            continue
        for finding in findings:
            tool = getattr(finding, "tool", "") or ""
            summary = (getattr(finding, "summary", "") or "").strip()
            if not summary or summary.startswith("unavailable"):
                continue

            kind = Kind.EVENT_DUE if "event" in tool else Kind.POSITION_NEWS
            out.append(
                Candidate(
                    kind=kind,
                    ticker=ticker,
                    title=f"{ticker}: {tool.replace('_', ' ')} reported something",
                    body=f"Reported by {tool}: {summary[:400]}",
                    dedupe_key=f"{kind}:{ticker}:{tool}",
                    payload={
                        "tool": tool,
                        # Named so a reader can tell a read headline from a measured break.
                        "source_ref": getattr(finding, "source_ref", None),
                        "measured_by_platform": False,
                    },
                )
            )
    return out


# ── opportunity ───────────────────────────────────────────────────────────────
def opportunities(risk_decisions: list[dict]) -> list[Candidate]:
    """A verdict risk assessed as actionable. Links to the decision; never acts on it."""
    out: list[Candidate] = []
    for decision in risk_decisions or []:
        if decision.get("outcome") != "proceed":
            continue
        ticker = decision.get("ticker", "")
        out.append(
            Candidate(
                kind=Kind.OPPORTUNITY,
                ticker=ticker,
                title=f"{ticker}: {decision.get('strategy_id')} is actionable",
                body=(
                    f"{decision.get('reason')}. Nothing has been bought — recording a fill is "
                    "a separate, deliberate step."
                ),
                dedupe_key=f"{Kind.OPPORTUNITY}:{ticker}:{decision.get('strategy_id')}",
                payload={
                    "strategy_id": decision.get("strategy_id"),
                    "quantity": decision.get("quantity"),
                    "notional": decision.get("notional"),
                },
            )
        )
    return out


# ── book level ────────────────────────────────────────────────────────────────
def book_full(
    positions: list[Position], max_positions: int, blocked: int
) -> list[Candidate]:
    open_count = len([p for p in positions if p.is_open])
    if open_count < max_positions or blocked == 0:
        return []
    return [
        Candidate(
            kind=Kind.BOOK_FULL,
            title=f"Book is full at {open_count} positions",
            body=(
                f"{blocked} actionable verdict(s) could not be sized because the book holds "
                f"{open_count} of {max_positions} allowed."
            ),
            dedupe_key=f"{Kind.BOOK_FULL}:{open_count}",
            payload={"open_positions": open_count, "max_positions": max_positions},
        )
    ]


def regime_change(regime: dict | None, previous_label: str | None) -> list[Candidate]:
    """Raised only when the label actually changed — the dedupe key carries the label."""
    if not regime:
        return []
    label = regime.get("label")
    if not label or label == previous_label:
        return []
    return [
        Candidate(
            kind=Kind.REGIME_CHANGE,
            title=f"Market regime is {label}",
            body=regime.get("detail", ""),
            dedupe_key=f"{Kind.REGIME_CHANGE}:{label}",
            payload={"label": label, "previous": previous_label},
        )
    ]
