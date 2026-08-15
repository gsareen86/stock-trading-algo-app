"""Volatility Contraction Pattern analysis.

Minervini's VCP is successive pullbacks of decreasing depth on declining volume — supply
drying up as weak holders are shaken out. Measured here, not judged: the strategy decides what
a two-contraction base is worth.

**A weak base lowers quality; it does not disqualify.** "Not yet a VCP" is a legitimate
`WATCH` — a stock building its first contraction is exactly what a watchlist is for.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.prices import PriceSeries
from app.domain.verdict import Evidence, Operator
from app.strategies.indicators import (
    Contraction,
    find_contractions,
    is_tightening,
    volume_dry_up_ratio,
)

#: Minervini typically wants 2–4 contractions before a breakout is worth acting on.
IDEAL_CONTRACTIONS = 2
#: Below this, recent volume counts as dried up against the base average.
DRY_UP_THRESHOLD = 1.0

MAX_VCP_POINTS = 25
MAX_VOLUME_POINTS = 5


@dataclass(frozen=True, slots=True)
class VcpReading:
    contractions: list[Contraction]
    tightening: bool
    dry_up_ratio: float | None

    @property
    def count(self) -> int:
        return len(self.contractions)

    @property
    def latest_depth_pct(self) -> float | None:
        return self.contractions[-1].depth_pct if self.contractions else None


def analyse(series: PriceSeries) -> VcpReading:
    contractions = find_contractions(series.frame)
    return VcpReading(
        contractions=contractions,
        tightening=is_tightening(contractions),
        dry_up_ratio=volume_dry_up_ratio(series.frame),
    )


def to_evidence(series: PriceSeries, reading: VcpReading) -> list[Evidence]:
    ref = f"price://{series.instrument.symbol}?interval={series.interval}&analysis=vcp"

    rows = [
        Evidence(
            id="vcp_contraction_count",
            label="Successive contractions detected in the base",
            value=reading.count,
            threshold=IDEAL_CONTRACTIONS,
            operator=Operator.GTE,
            passed=reading.count >= IDEAL_CONTRACTIONS,
            source_ref=ref,
        ),
        Evidence(
            id="vcp_tightening",
            label="Each contraction shallower than the one before",
            value=reading.tightening,
            threshold=True,
            operator=Operator.EQ,
            passed=reading.tightening,
            source_ref=ref,
        ),
    ]

    if reading.latest_depth_pct is not None:
        # Informational: there is no universal threshold for a final contraction's depth, and
        # inventing one would put a fabricated test into the evidence.
        rows.append(
            Evidence(
                id="vcp_latest_depth",
                label="Depth of the most recent contraction",
                value=reading.latest_depth_pct,
                operator=Operator.INFO,
                unit="%",
                source_ref=ref,
            )
        )

    rows.append(
        Evidence(
            id="vcp_volume_dry_up",
            label="Recent volume relative to the base average",
            value=reading.dry_up_ratio,
            threshold=DRY_UP_THRESHOLD,
            operator=Operator.LT,
            passed=bool(
                reading.dry_up_ratio is not None and reading.dry_up_ratio < DRY_UP_THRESHOLD
            ),
            unit="x",
            source_ref=f"price://{series.instrument.symbol}?analysis=volume_dry_up",
        )
    )

    return rows


def quality_points(reading: VcpReading) -> tuple[int, int]:
    """-> (vcp points out of 25, volume points out of 5).

    Split so a reader can see which half of the bonus a stock earned — a tight base with heavy
    volume is a different situation from a loose base going quiet.
    """
    if reading.count == 0:
        vcp_points = 0
    else:
        # Depth counts as much as count: three shallow contractions beat three deep ones.
        depth_credit = 0.0
        if reading.latest_depth_pct is not None:
            depth_credit = max(0.0, min(1.0, (20.0 - reading.latest_depth_pct) / 15.0))
        count_credit = min(1.0, reading.count / IDEAL_CONTRACTIONS)
        tighten_credit = 1.0 if reading.tightening else 0.4
        vcp_points = round(
            MAX_VCP_POINTS * count_credit * tighten_credit * (0.5 + 0.5 * depth_credit)
        )

    volume_points = (
        MAX_VOLUME_POINTS
        if reading.dry_up_ratio is not None and reading.dry_up_ratio < DRY_UP_THRESHOLD
        else 0
    )
    return int(vcp_points), int(volume_points)
