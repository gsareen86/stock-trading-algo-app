"""Unit tests for discovery funnel: RRG sectors, movers, quality facets, attribution ranking, scanner."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from app.data.fake import FakePriceSource, StaticPriceSource
from app.data.fundamentals import StaticFundamentalsSource
from app.data.protocols import UniverseSnapshot
from app.data.sectors import SectorIndex
from app.data.yfinance_quality import YFinanceQualitySource
from app.discovery.movers import find_movers
from app.discovery.quality import evaluate_quality
from app.discovery.ranking import CandidateEntry, filter_candidates, rank_candidates, select_ranking_verdict
from app.discovery.scanner import DiscoveryScanner, ScanInProgressError
from app.discovery.sectors import MIN_RRG_BARS, place_sector
from app.domain.financials import CompanyFinancials, Metric
from app.domain.instrument import Instrument
from app.domain.verdict import Evidence, Operator, Stance, Verdict
from app.persistence.session import make_engine, make_session_factory
from app.screening.screener import ScreenCriteria
from app.strategies.registry import StrategyRegistry
from tests.conftest import Settings

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _df(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes or [1_000_000.0] * n,
        },
        index=pd.date_range("2025-01-01", periods=n, freq="D"),
    )


def _ev(eid: str = "e1") -> Evidence:
    return Evidence(id=eid, label="x", value=1.0, operator=Operator.INFO, source_ref="price://X")


def _verdict(symbol: str, sid: str, stance: Stance, conviction: int) -> Verdict:
    return Verdict(
        strategy_id=sid,
        ticker=symbol,
        as_of=NOW,
        stance=stance,
        conviction=conviction,
        evidence=(_ev(),),
    )


class TestSectorRRG:
    def test_strong_and_rising_places_in_leading(self) -> None:
        bench = _df([100.0 * (1.001 ** i) for i in range(200)])
        sec = _df([100.0 * (1.003 ** i) for i in range(160)] + [100.0 * (1.003 ** 159) * (1.01 ** j) for j in range(1, 41)])
        placed = place_sector(SectorIndex("IT", "^CNXIT"), sec, bench)

        assert placed.quadrant == "Leading"
        assert placed.rs_pct is not None and placed.rs_pct > 0
        assert placed.rs_momentum_pp is not None and placed.rs_momentum_pp >= 0
        assert len(placed.trail) >= 1

    def test_strong_and_falling_places_in_weakening(self) -> None:
        bench = _df([100.0 * (1.001 ** i) for i in range(200)])
        # Huge early surge, flat/pullback in last 20 bars
        sec_vals = [100.0 * (1.005 ** i) for i in range(175)]
        peak = sec_vals[-1]
        sec_vals += [peak * (0.997 ** j) for j in range(1, 26)]
        placed = place_sector(SectorIndex("Metal", "^CNXMETAL"), _df(sec_vals), bench)

        assert placed.quadrant == "Weakening"
        assert placed.rs_pct is not None and placed.rs_pct > 0
        assert placed.rs_momentum_pp is not None and placed.rs_momentum_pp < 0

    def test_weak_and_rising_places_in_improving(self) -> None:
        bench = _df([100.0 * (1.002 ** i) for i in range(200)])
        # Prolonged early underperformance, rebounding in last 25 bars while blended RS remains <= 0
        early = [140.0 * (0.996 ** i) for i in range(175)]
        trough = early[-1]
        sec_vals = early + [trough * (1.005 ** j) for j in range(1, 26)]
        placed = place_sector(SectorIndex("Pharma", "^CNXPHARMA"), _df(sec_vals), bench)

        assert placed.quadrant == "Improving"
        assert placed.rs_pct is not None and placed.rs_pct <= 0
        assert placed.rs_momentum_pp is not None and placed.rs_momentum_pp >= 0

    def test_insufficient_history_is_unplaced_not_defaulted(self) -> None:
        short = _df([100.0] * (MIN_RRG_BARS - 10))
        bench = _df([100.0] * (MIN_RRG_BARS + 20))
        placed = place_sector(SectorIndex("Auto", "^CNXAUTO"), short, bench)

        assert placed.quadrant == "unplaced"
        assert placed.reason is not None
        assert not hasattr(placed, "stance")
        assert not hasattr(placed, "conviction")


class TestMovers:
    def test_sector_with_no_crossings_returns_empty(self) -> None:
        # Price fell well below 52W high, flat volume, weak RS
        closes = [200.0] * 100 + [120.0] * 50
        src = StaticPriceSource({"TCS": _df(closes), "^CRSLDX": _df([100.0] * 150)})
        movers = find_movers("IT", [Instrument("TCS", sector="Information Technology")], src)

        assert movers == []

    def test_returns_signal_with_measurements(self) -> None:
        closes = [100.0 * (1.002 ** i) for i in range(150)]
        vols = [1_000_000.0] * 149 + [3_500_000.0]
        src = StaticPriceSource({"TCS": _df(closes, vols), "^CRSLDX": _df([100.0] * 150)})
        movers = find_movers("IT", [Instrument("TCS", sector="Information Technology")], src)

        assert len(movers) == 1
        signal_ids = {s.signal_id for s in movers[0].signals}
        assert {"near_52w_high", "volume_expansion"} <= signal_ids


class TestQualityFacets:
    def test_leverage_not_applicable_for_bank_rather_than_failed(self) -> None:
        fin = CompanyFinancials(
            symbol="HDFCBANK",
            metrics={
                "returnonaverageequitytrailing12month": Metric("returnonaverageequitytrailing12month", "ROE", 17.0, "mgmt", "yfinance"),
                "totaldebtpertotalequitymostrecentquarter": Metric("totaldebtpertotalequitymostrecentquarter", "D/E", 6.5, "fin", "yfinance"),
            },
            source="yfinance",
        )
        report = evaluate_quality(fin, symbol="HDFCBANK", sector_key="PrivateBank")
        de = report.facet("debt_to_equity")

        assert de is not None
        assert de.status == "not_applicable"
        assert report.facet("roe").status == "pass"

    def test_unavailable_financials_stays_unavailable_not_failed(self) -> None:
        report = evaluate_quality(None, symbol="XYZ", sector_key="IT")

        assert report.facet("roe").status == "unavailable"
        assert "score" not in report.as_dict()


class TestAttributableRanking:
    def test_ranking_is_attributed_and_ties_keep_universe_order(self) -> None:
        a = CandidateEntry.from_verdicts(
            symbol="AAA", name="AAA", sector="IT", sector_key="IT", universe_index=0,
            verdicts=[_verdict("AAA", "minervini", Stance.BUY, 82), _verdict("AAA", "young_momentum", Stance.WATCH, 40)],
        )
        b = CandidateEntry.from_verdicts(
            symbol="BBB", name="BBB", sector="IT", sector_key="IT", universe_index=1,
            verdicts=[_verdict("BBB", "fun_tech_momentum", Stance.BUY, 82), _verdict("BBB", "minervini", Stance.BUY, 78)],
        )
        c = CandidateEntry.from_verdicts(
            symbol="CCC", name="CCC", sector="Auto", sector_key="Auto", universe_index=2,
            verdicts=[_verdict("CCC", "young_momentum", Stance.BUY, 90)],
        )

        ranked = rank_candidates([b, c, a])
        assert [e.symbol for e in ranked] == ["CCC", "AAA", "BBB"]
        assert ranked[0].ranked_by == "young_momentum"
        assert ranked[1].ranked_by == "minervini"
        assert ranked[2].ranked_by == "fun_tech_momentum"

    def test_min_buy_filter_selects_without_changing_ordering_rule(self) -> None:
        one_buy = CandidateEntry.from_verdicts(
            symbol="ONE", name=None, sector=None, sector_key=None, universe_index=0,
            verdicts=[_verdict("ONE", "minervini", Stance.BUY, 95), _verdict("ONE", "young_momentum", Stance.AVOID, 10)],
        )
        two_buy = CandidateEntry.from_verdicts(
            symbol="TWO", name=None, sector=None, sector_key=None, universe_index=1,
            verdicts=[_verdict("TWO", "minervini", Stance.BUY, 80), _verdict("TWO", "young_momentum", Stance.BUY, 75)],
        )
        three_buy = CandidateEntry.from_verdicts(
            symbol="THREE", name=None, sector=None, sector_key=None, universe_index=2,
            verdicts=[
                _verdict("THREE", "minervini", Stance.BUY, 88),
                _verdict("THREE", "young_momentum", Stance.BUY, 72),
                _verdict("THREE", "brahma_vishnu_mahesh", Stance.BUY, 74),
            ],
        )

        selected = filter_candidates([one_buy, two_buy, three_buy], min_buy_count=2)
        assert [e.symbol for e in selected] == ["THREE", "TWO"]
        assert selected[0].ranked_by == "minervini"
        assert selected[0].ranked_conviction == 88

    def test_no_blending_or_mean_over_verdicts_in_discovery_module(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app" / "discovery"
        banned = ("consensus", "composite_score", "average_conviction", "blended_score", "mean_conviction")
        for path in root.rglob("*.py"):
            text = path.read_text("utf-8").lower()
            for word in banned:
                assert word not in text, f"{word} found in {path.name}"


class TestDiscoveryScanner:
    async def test_append_only_scan_and_concurrent_refusal(self, migrated_url: str, tmp_path: Path) -> None:
        settings = Settings(database_url=migrated_url, llm_cache_dir=str(tmp_path), _env_file=None)
        engine = make_engine(settings)
        sf = make_session_factory(engine)
        snapshot = UniverseSnapshot(
            instruments=(
                Instrument("TCS", "Tata Consultancy Services", "Information Technology"),
                Instrument("LOWBAR", "Too Short", "Information Technology"),
            ),
            origin="live",
            index_name="TEST",
        )

        class U:
            def snapshot(self):
                return snapshot

        prices = StaticPriceSource({
            "TCS": _df([100.0 * (1.002 ** i) for i in range(420)]),
            "LOWBAR": _df([100.0] * 10),
        })
        scanner = DiscoveryScanner(
            session_factory=sf,
            universe_source=U(),
            price_source=prices,
            strategies=StrategyRegistry.discover(),
            fundamentals_source=StaticFundamentalsSource({}),
            company_financials_source=YFinanceQualitySource(fetcher=lambda t: {}),
        )
        criteria = ScreenCriteria(min_turnover_inr=0, min_price_inr=0, exclude_surveillance=False)
        steps: list[str] = []
        summary = await scanner.run(
            criteria=criteria,
            narrate=False,
            on_progress=lambda step, lbl, done, tot: steps.append(step),
        )

        assert summary.outcome == "complete"
        assert summary.eligible_count == 1
        assert summary.entries_count == 1
        assert "screening" in steps and "sectors" in steps and "strategies" in steps

        # Second run appends cleanly
        summary2 = await scanner.run(criteria=criteria, narrate=False)
        assert summary2.run_id > summary.run_id

        # Concurrent run refused if lock held or running row exists
        from app.persistence.models import ScanRun as ScanRunRow
        with sf() as session:
            running = ScanRunRow(trigger="requested", outcome="running", considered_count=1, eligible_count=0)
            session.add(running)
            session.commit()
            running_id = running.id

        with pytest.raises(ScanInProgressError) as exc:
            await scanner.run(criteria=criteria, narrate=False)
        assert exc.value.run_id == running_id
