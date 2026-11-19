"""Phase 2 integration & unit tests: new tools, IdeaScout, discovery/watchlist/stocks APIs, SSE."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from app.agents.scout import IdeaScout
from app.core.clock import now_utc
from app.domain.financials import CompanyFinancials, Metric, PeriodValue, Shareholding, StatementSeries
from app.domain.instrument import Instrument
from app.domain.prices import PriceSeries
from app.persistence.models import ScanEntry, ScanRun, Theme, ThemeCandidate, WatchlistItem
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext


@dataclass
class _StubUniverseSnapshot:
    instruments: list[Instrument]
    index_name: str = "NIFTY TOTAL MARKET"
    origin: str = "stub"


class _StubUniverseSource:
    def __init__(self, instruments: list[Instrument]) -> None:
        self._instruments = instruments

    def snapshot(self) -> _StubUniverseSnapshot:
        return _StubUniverseSnapshot(instruments=self._instruments)


class _StubPriceSource:
    def __init__(self, base_prices: dict[str, float] | None = None) -> None:
        self._base_prices = base_prices or {}

    def history(
        self, instrument: Instrument, interval: str = "1d", lookback_days: int = 365
    ) -> PriceSeries:
        sym = instrument.symbol
        base = self._base_prices.get(sym, 100.0)
        n = min(max(lookback_days // 2, 260), 400)
        end = datetime.now(UTC).date()
        dates = pd.bdate_range(end=end, periods=n)
        slope = 1.0018 if not sym.startswith("^") else 1.0006
        if sym == "^CNXIT":
            slope = 0.9992
        closes = [round(base * (slope ** i), 2) for i in range(n)]
        df = pd.DataFrame(
            {
                "open": [c * 0.995 for c in closes],
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [250_000 + i * 500 for i in range(n)],
            },
            index=dates,
        )
        return PriceSeries(instrument=instrument, interval=interval, frame=df, source="fake")


class _StubFinancialsSource:
    def financials(self, instrument: Instrument) -> CompanyFinancials:
        sym = instrument.symbol
        metrics = {
            "returnonequity": Metric(key="returnonequity", label="ROE %", value=22.5, category="profitability", source="stub"),
            "returnoncapitalemployed": Metric(key="returnoncapitalemployed", label="ROCE %", value=26.0, category="profitability", source="stub"),
            "totaldebttoequity": Metric(key="totaldebttoequity", label="Debt / Equity", value=0.25, category="leverage", source="stub"),
            "revenuegrowthyoy": Metric(key="revenuegrowthyoy", label="Sales YoY %", value=19.2, category="growth", source="stub"),
            "earningsgrowthyoy": Metric(key="earningsgrowthyoy", label="Profit YoY %", value=24.0, category="growth", source="stub"),
            "operatingmargin": Metric(key="operatingmargin", label="OPM %", value=18.5, category="margins", source="stub"),
            "trailingpe": Metric(key="trailingpe", label="P/E", value=28.0, category="valuation", source="stub"),
        }
        statements = {
            "revenue": StatementSeries(
                metric="revenue",
                points=(
                    PeriodValue(period="Q4", value=1200.0),
                    PeriodValue(period="Q3", value=1100.0),
                ),
            )
        }
        shareholding = (
            Shareholding(as_of=datetime.now(UTC).date(), promoter_pct=56.2, fii_pct=None, dii_pct=None, pledge_pct=None, source="stub"),
        )
        return CompanyFinancials(
            symbol=sym,
            metrics=metrics,
            statements=statements,
            shareholding=shareholding,
            industry="Capital Goods",
            company_name=f"{sym} Industries Ltd",
            description="Precision engineering & power equipment.",
            source="stub",
            fetched_at=now_utc(),
        )


def _seed_scan_and_watchlist(session_factory) -> int:
    stamp = now_utc()
    with session_factory() as session:
        run = ScanRun(
            trigger="scheduled",
            universe_origin="stub",
            index_name="NIFTY TOTAL MARKET",
            benchmark="^CRSLDX",
            outcome="complete",
            considered_count=2,
            eligible_count=2,
            unevaluable=[],
            sectors_snapshot=[
                {
                    "sector": "Energy",
                    "key": "energy",
                    "index_symbol": "^CNXENERGY",
                    "rs_pct": 4.2,
                    "rs_momentum_pp": 1.5,
                    "quadrant": "Leading",
                    "return_4w_pct": 6.1,
                    "return_12w_pct": 14.3,
                    "trail": [{"rs_pct": 2.0, "rs_momentum_pp": 0.5}],
                }
            ],
            started_at=stamp - timedelta(minutes=2),
            finished_at=stamp,
        )
        session.add(run)
        session.flush()

        verdict_buy = {
            "strategy_id": "vcp_minervini",
            "ticker": "TRENT",
            "as_of": stamp.isoformat(),
            "stance": "BUY",
            "conviction": 82,
            "gates_passed": True,
            "gates": [],
            "evidence": [],
            "plan": {
                "entry": 520.0,
                "stop": 490.0,
                "target": 590.0,
                "risk_reward": 2.33,
                "entry_kind": "pivot",
                "valid_until": None,
                "note": None,
            },
            "narrative": "Tight VCP base near highs.",
            "trace_id": None,
        }
        verdict_watch = {
            "strategy_id": "stage2_weinstein",
            "ticker": "INFY",
            "as_of": stamp.isoformat(),
            "stance": "WATCH",
            "conviction": 55,
            "gates_passed": False,
            "gates": [],
            "evidence": [],
            "plan": None,
            "narrative": None,
            "trace_id": None,
        }
        session.add(
            ScanEntry(
                run_id=run.id,
                universe_index=0,
                symbol="TRENT",
                name="Trent Ltd",
                sector="Services",
                sector_key="energy",
                ranked_by="vcp_minervini",
                ranked_conviction=82,
                ranked_stance="BUY",
                buy_count=1,
                verdicts=[verdict_buy],
                quality={
                    "symbol": "TRENT",
                    "source": "stub",
                    "facets": [
                        {"key": "roe", "label": "ROE", "status": "pass", "value": 22.5, "threshold": 15.0, "unit": "%"},
                        {"key": "debt_equity", "label": "D/E", "status": "pass", "value": 0.25, "threshold": 1.0, "unit": "x"},
                        {"key": "sales_yoy", "label": "Sales YoY", "status": "pass", "value": 19.2, "threshold": 12.0, "unit": "%"},
                    ],
                    "summary": {"roe_pct": 22.5, "debt_to_equity": 0.25, "sales_yoy_pct": 19.2},
                },
                themes=[{"key": "retail_expansion", "label": "Retail Expansion", "exposure": "direct"}],
            )
        )
        session.add(
            ScanEntry(
                run_id=run.id,
                universe_index=1,
                symbol="INFY",
                name="Infosys Ltd",
                sector="IT",
                sector_key="it",
                ranked_by="stage2_weinstein",
                ranked_conviction=55,
                ranked_stance="WATCH",
                buy_count=0,
                verdicts=[verdict_watch],
                quality={"symbol": "INFY", "source": "stub", "facets": [], "summary": {}},
                themes=[],
            )
        )
        session.add(
            WatchlistItem(
                symbol="TRENT",
                name="Trent Ltd",
                sector="Services",
                book_intent="swing",
                target_strategy_id="vcp_minervini",
                notes="Watch breakout volume",
                added_price=500.0,
                last_known_stances={"vcp_minervini": "WATCH"},
                created_at=stamp - timedelta(days=1),
                updated_at=stamp - timedelta(days=1),
            )
        )
        session.add(
            Theme(
                key="retail_expansion",
                label="Retail Expansion",
                breadth=2,
                persistence=1,
                sector_count=1,
                source_kinds=["commentary"],
                measured_at=stamp,
            )
        )
        session.add(
            ThemeCandidate(
                theme_key="retail_expansion",
                symbol="TRENT",
                tier=1,
                exposure="established",
                exposure_basis="Store expansion",
            )
        )
        session.commit()
        return run.id


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    cur_event = None
    for line in body.splitlines():
        if line.startswith("event: "):
            cur_event = line.removeprefix("event: ").strip()
        elif line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: "))
            events.append({"event": cur_event, "data": payload})
    return events


class TestNewToolsAndScout:
    def test_four_new_tools_execute_with_context(self, session_factory) -> None:
        _seed_scan_and_watchlist(session_factory)
        instruments = [
            Instrument("TRENT", name="Trent Ltd", sector="Services"),
            Instrument("INFY", name="Infosys Ltd", sector="IT"),
        ]
        ctx = ToolContext(
            price_source=_StubPriceSource({"TRENT": 350.0, "INFY": 1400.0}),
            session_factory=session_factory,
            company_financials_source=_StubFinancialsSource(),
            universe_source=_StubUniverseSource(instruments),
        )
        reg = ToolRegistry.discover()

        sec = reg.invoke("sector_rotation", {"benchmark": "^CRSLDX"}, ctx)
        assert sec.ok and len(sec.items) == 14
        for item in sec.items:
            assert "stance" not in item and "conviction" not in item

        scr = reg.invoke("setup_screener", {"sector_key": "energy", "limit": 10}, ctx)
        assert scr.ok and scr.items[0]["symbol"] == "TRENT"
        assert "stance" not in scr.items[0] and "conviction" not in scr.items[0]

        qual = reg.invoke("company_quality", {"symbol": "TRENT"}, ctx)
        assert qual.ok and qual.data["symbol"] == "TRENT"
        assert qual.data["company_name"] == "TRENT Industries Ltd"

        pw = reg.invoke("portfolio_and_watchlist", {"include_watchlist": True}, ctx)
        assert pw.ok and pw.data["watchlist_count"] == 1
        assert pw.items[0]["kind"] == "watchlist" and pw.items[0]["symbol"] == "TRENT"

    def test_idea_scout_prioritizes_watchlist_and_scan_setups(self, session_factory) -> None:
        _seed_scan_and_watchlist(session_factory)
        instruments = [
            Instrument("TRENT", name="Trent Ltd", sector="Services"),
            Instrument("INFY", name="Infosys Ltd", sector="IT"),
            Instrument("RELIANCE", name="Reliance Industries", sector="Energy"),
        ]
        scout = IdeaScout(
            tools=ToolRegistry.discover(),
            session_factory=session_factory,
            universe_source=_StubUniverseSource(instruments),
            price_source=_StubPriceSource({"TRENT": 510.0}),
        )
        plan = scout.plan(limit=5, include_web_discovery=False)
        assert "TRENT" in plan.prioritized_symbols
        assert plan.prioritized_symbols[0] == "TRENT"
        assert any("watchlist" in r or "scan" in r for r in plan.rationale)


class TestPhase2Apis:
    def test_discovery_scan_filter_sectors_movers_and_stream(self, client: TestClient) -> None:
        instruments = [
            Instrument("TRENT", name="Trent Ltd", sector="Services"),
            Instrument("RELIANCE", name="Reliance Industries", sector="Energy"),
            Instrument("TCS", name="Tata Consultancy", sector="IT"),
        ]
        app = client.app
        app.state.universe_source = _StubUniverseSource(instruments)
        app.state.price_source = _StubPriceSource({"TRENT": 400.0, "RELIANCE": 1200.0, "TCS": 3000.0})
        app.state.company_financials_source = _StubFinancialsSource()
        # Reset cached scanner so it picks up stub sources
        app.state.discovery_scanner = None

        sectors_res = client.get("/discovery/sectors")
        assert sectors_res.status_code == 200
        sectors_body = sectors_res.json()
        assert sectors_body["count"] == 14

        movers_res = client.get("/discovery/movers?sector=energy")
        assert movers_res.status_code == 200
        assert movers_res.json()["checked_instruments"] == 1

        scan_res = client.post("/discovery/scan", json={"narrate": False})
        assert scan_res.status_code == 200
        scan_body = scan_res.json()
        assert scan_body["outcome"] == "complete"
        assert scan_body["considered_count"] == 3

        latest_res = client.get("/discovery/runs/latest")
        assert latest_res.status_code == 200
        latest_body = latest_res.json()
        assert latest_body["run"]["id"] == scan_body["run_id"]
        assert "unblended" in latest_body["rank_policy"].lower()
        assert latest_body["total_candidates"] >= 1

        stream_res = client.post("/discovery/scan/stream", json={"narrate": False})
        assert stream_res.status_code == 200
        assert "text/event-stream" in stream_res.headers["content-type"]
        events = _parse_sse(stream_res.text)
        assert any(e["event"] == "progress" for e in events)
        assert events[-1]["event"] == "complete", events[-1]

    def test_watchlist_crud_transitions_and_briefing(self, client: TestClient) -> None:
        sf = client.app.state.session_factory
        run_id = _seed_scan_and_watchlist(sf)
        client.app.state.universe_source = _StubUniverseSource(
            [Instrument("TRENT", name="Trent Ltd", sector="Services"), Instrument("INFY", name="Infosys Ltd", sector="IT")]
        )
        # Near TRENT's 520 pivot (within 1%)
        client.app.state.price_source = _StubPriceSource({"TRENT": 516.0, "INFY": 1400.0})

        lst = client.get("/watchlist").json()
        assert lst["count"] == 1
        assert lst["items"][0]["flipped_buy"] is True
        assert lst["items"][0]["flipped_strategies"] == ["vcp_minervini"]
        assert lst["items"][0]["distance_to_entry_pct"] is not None

        add_res = client.post("/watchlist", json={"symbol": "INFY", "book_intent": "longterm", "notes": "Accumulate"})
        assert add_res.status_code == 201
        assert add_res.json()["symbol"] == "INFY"

        patch_res = client.patch("/watchlist/INFY", json={"notes": "Updated thesis note"})
        assert patch_res.status_code == 200
        assert patch_res.json()["notes"] == "Updated thesis note"

        briefing_before = client.get("/insights/briefing")
        assert briefing_before.status_code == 200
        b_body = briefing_before.json()
        assert "watchlist_pulse" in b_body
        assert b_body["watchlist_pulse"]["total_watched"] == 2
        assert b_body["watchlist_pulse"]["flipped_buy_count"] >= 1

        from app.discovery.briefing import record_scan_transitions

        transitions = record_scan_transitions(sf, run_id=run_id, price_source=client.app.state.price_source)
        assert transitions["written"] >= 1

        del_res = client.delete("/watchlist/INFY")
        assert del_res.status_code == 200

    def test_stocks_chart_quality_research_and_universe_symbols(self, client: TestClient) -> None:
        sf = client.app.state.session_factory
        _seed_scan_and_watchlist(sf)
        client.app.state.universe_source = _StubUniverseSource(
            [Instrument("TRENT", name="Trent Ltd", sector="Services")]
        )
        client.app.state.price_source = _StubPriceSource({"TRENT": 350.0})
        client.app.state.company_financials_source = _StubFinancialsSource()

        u_res = client.get("/universe/symbols?q=TREN")
        assert u_res.status_code == 200
        assert u_res.json()["symbols"][0]["symbol"] == "TRENT"

        c_res = client.get("/stocks/TRENT/chart?range=6M")
        assert c_res.status_code == 200
        c_body = c_res.json()
        assert c_body["available"] is True
        assert len(c_body["bars"]) > 50
        assert "ema20" in c_body["bars"][-1] and "sma200" in c_body["bars"][-1]

        q_res = client.get("/stocks/TRENT/quality")
        assert q_res.status_code == 200
        assert q_res.json()["company_name"] == "TRENT Industries Ltd"

        r_res = client.get("/stocks/TRENT/research")
        assert r_res.status_code == 200
        r_body = r_res.json()
        assert r_body["themes"][0]["theme_key"] == "retail_expansion"

    def test_cycle_stream_and_theme_discover_and_stream(self, client: TestClient) -> None:
        client.app.state.universe_source = _StubUniverseSource(
            [Instrument("TRENT", name="Trent Ltd", sector="Services")]
        )
        client.app.state.price_source = _StubPriceSource({"TRENT": 350.0})

        cyc_res = client.post(
            "/cycles/run/stream",
            json={"symbols": ["TRENT"], "research": False, "narrate": False},
        )
        assert cyc_res.status_code == 200
        assert "text/event-stream" in cyc_res.headers["content-type"]
        cyc_events = _parse_sse(cyc_res.text)
        assert any(e["event"] == "progress" for e in cyc_events)
        assert cyc_events[-1]["event"] == "complete"

        disc_res = client.post("/themes/discover", json={"limit": 3, "include_web_discovery": False})
        assert disc_res.status_code == 200
        assert "prioritized_symbols" in disc_res.json()["scout"]
