"""Attributable discovery ranking — never blended, never averaged.

Ordering key is strictly one named strategy's unmodified ``conviction``:

* Every entry records ``ranked_by`` (that strategy's id) and ``ranked_conviction`` (its own
  0-100 figure, unchanged).
* Ties break strictly by ``universe_index`` (universe order).
* Agreement (``min_buy_count``) is a **filter** only — selecting rows without altering the
  ordering rule or creating a cross-strategy rating.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.discovery.quality import QualityReport
from app.domain.verdict import Stance, Verdict

_STANCE_PRIORITY = {Stance.BUY: 0, Stance.WATCH: 1, Stance.AVOID: 2}


def select_ranking_verdict(verdicts: tuple[Verdict, ...] | list[Verdict]) -> Verdict:
    """Pick the single highest-conviction verdict for one instrument.

    Never computes across verdicts — simply identifies which single named strategy owns the
    strongest reading on this stock (preferring BUY over WATCH over AVOID if convictions tie,
    then alphabetical strategy_id for determinism).
    """
    if not verdicts:
        raise ValueError("cannot rank an instrument with zero verdicts")
    return min(
        verdicts,
        key=lambda v: (-v.conviction, _STANCE_PRIORITY.get(v.stance, 9), v.strategy_id),
    )


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    symbol: str
    name: str | None
    sector: str | None
    sector_key: str | None
    universe_index: int
    ranked_by: str
    ranked_conviction: int
    ranked_stance: str
    verdicts: tuple[Verdict, ...]
    quality: QualityReport | None = None
    themes: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_verdicts(
        cls,
        *,
        symbol: str,
        name: str | None,
        sector: str | None,
        sector_key: str | None,
        universe_index: int,
        verdicts: list[Verdict] | tuple[Verdict, ...],
        quality: QualityReport | None = None,
        themes: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    ) -> CandidateEntry:
        champion = select_ranking_verdict(verdicts)
        return cls(
            symbol=symbol,
            name=name,
            sector=sector,
            sector_key=sector_key,
            universe_index=universe_index,
            ranked_by=champion.strategy_id,
            ranked_conviction=champion.conviction,
            ranked_stance=champion.stance.value,
            verdicts=tuple(sorted(verdicts, key=lambda v: v.strategy_id)),
            quality=quality,
            themes=tuple(themes),
        )

    @property
    def buy_stances(self) -> int:
        """Display/filter helper only: number of strategies currently at BUY."""
        return sum(1 for v in self.verdicts if v.stance is Stance.BUY)

    def verdict_for(self, strategy_id: str) -> Verdict | None:
        return next((v for v in self.verdicts if v.strategy_id == strategy_id), None)

    def with_verdicts(self, verdicts: tuple[Verdict, ...]) -> CandidateEntry:
        champion = select_ranking_verdict(verdicts)
        return CandidateEntry(
            symbol=self.symbol,
            name=self.name,
            sector=self.sector,
            sector_key=self.sector_key,
            universe_index=self.universe_index,
            ranked_by=champion.strategy_id,
            ranked_conviction=champion.conviction,
            ranked_stance=champion.stance.value,
            verdicts=verdicts,
            quality=self.quality,
            themes=self.themes,
        )


def rank_candidates(entries: list[CandidateEntry]) -> list[CandidateEntry]:
    """Order candidates strictly by single-strategy ``ranked_conviction``, ties by universe."""
    stance_rank = {"BUY": 0, "WATCH": 1, "AVOID": 2}
    return sorted(
        entries,
        key=lambda e: (
            stance_rank.get(e.ranked_stance, 9),
            -e.ranked_conviction,
            e.universe_index,
        ),
    )


def filter_candidates(
    entries: list[CandidateEntry],
    *,
    sector_key: str | None = None,
    strategy_id: str | None = None,
    stance: str | None = None,
    min_buy_count: int | None = None,
    roe_min: float | None = None,
    sales_yoy_min: float | None = None,
    low_debt: bool = False,
    theme_backed_only: bool = False,
) -> list[CandidateEntry]:
    """Filter ranked candidates without changing the ordering rule.

    When ``strategy_id`` is supplied without ``stance``, candidates are still ordered by that
    named strategy's own conviction (and ``ranked_by`` names it explicitly), never by a cross-
    strategy formula.
    """
    filtered: list[CandidateEntry] = []
    target_stance = stance.upper() if stance else None

    for entry in entries:
        if sector_key and entry.sector_key != sector_key:
            continue
        if min_buy_count is not None and entry.buy_stances < min_buy_count:
            continue
        if theme_backed_only and not entry.themes:
            continue
        if strategy_id:
            v = entry.verdict_for(strategy_id)
            if v is None:
                continue
            if target_stance and v.stance.value != target_stance:
                continue
        elif target_stance and not any(
            v.stance.value == target_stance for v in entry.verdicts
        ):
            continue

        if roe_min is not None:
            roe = entry.quality.summary.get("roe") if entry.quality else None
            if roe is None or roe < roe_min:
                continue
        if sales_yoy_min is not None:
            sales = entry.quality.summary.get("sales_yoy") if entry.quality else None
            if sales is None or sales < sales_yoy_min:
                continue
        if low_debt and entry.quality is not None:
            de_facet = entry.quality.facet("debt_to_equity")
            if de_facet is None or de_facet.status == "fail" or de_facet.status == "unavailable":
                continue
            # Banks / FinancialServices marked not_applicable stay eligible.

        if strategy_id:
            v = entry.verdict_for(strategy_id)
            assert v is not None
            entry = CandidateEntry(
                symbol=entry.symbol,
                name=entry.name,
                sector=entry.sector,
                sector_key=entry.sector_key,
                universe_index=entry.universe_index,
                ranked_by=v.strategy_id,
                ranked_conviction=v.conviction,
                ranked_stance=v.stance.value,
                verdicts=entry.verdicts,
                quality=entry.quality,
                themes=entry.themes,
            )

        filtered.append(entry)

    return rank_candidates(filtered)
