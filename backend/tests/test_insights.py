"""The insight feed.

What carries this increment: only things that change what a person might do reach the feed,
the same observation does not arrive every morning, and research is quoted rather than asserted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.position import Book, Position, Side, Trade
from app.domain.verdict import Evidence, GateResult, Stance, Verdict
from app.insights import rules
from app.insights.feed import InsightFeed
from app.insights.kinds import SPECS, Kind, Severity, spec
from app.insights.rules import Candidate

T0 = datetime(2026, 8, 17, tzinfo=UTC)


def _position(ticker: str = "RELIANCE", qty: int = 10, cost: float = 1400.0) -> Position:
    return Position(Book.SWING, ticker, qty, cost, 0.0)


def _verdict(
    ticker: str = "RELIANCE",
    strategy: str = "minervini",
    stance: Stance = Stance.AVOID,
    failed_gate: bool = False,
) -> Verdict:
    evidence = (Evidence(id="e1", label="Trend", value=1.0, source_ref="price://x"),)
    gates = (
        (
            GateResult(
                id="trend",
                label="Trend Template",
                passed=False,
                reason="broke",
                evidence_ids=("e1",),
            ),
        )
        if failed_gate
        else ()
    )
    return Verdict(
        strategy_id=strategy,
        ticker=ticker,
        as_of=T0,
        stance=stance,
        conviction=0 if stance is Stance.AVOID else 70,
        evidence=evidence,
        gates=gates,
    )


def _trade(ticker: str, strategy: str | None) -> Trade:
    return Trade(
        book=Book.SWING,
        ticker=ticker,
        side=Side.BUY,
        quantity=10,
        price=1400.0,
        executed_at=T0,
        strategy_id=strategy,
    )


class Finding:
    def __init__(self, tool: str, summary: str, source_ref: str = "tool://x") -> None:
        self.tool = tool
        self.summary = summary
        self.source_ref = source_ref


class TestThesisBroken:
    """The reason the module exists — only noticeable by joining verdicts to positions."""

    def test_held_name_going_avoid_raises(self) -> None:
        candidates = rules.thesis_broken(
            [_position()], [_verdict(failed_gate=True)], {"RELIANCE": ("minervini",)}
        )

        assert len(candidates) == 1
        assert candidates[0].kind is Kind.THESIS_BROKEN
        assert candidates[0].severity is Severity.HIGH
        assert "Trend Template" in candidates[0].body

    def test_unheld_name_going_avoid_raises_nothing(self) -> None:
        """Four AVOIDs on a name nobody holds is a complete, unremarkable result."""
        assert rules.thesis_broken([], [_verdict()], {}) == []

    def test_a_different_strategys_avoid_is_not_a_broken_thesis(self) -> None:
        """A Minervini position is not invalidated by the long-term strategy's opinion."""
        candidates = rules.thesis_broken(
            [_position()],
            [_verdict(strategy="brahma_vishnu_mahesh")],
            {"RELIANCE": ("minervini",)},
        )

        assert candidates == []

    def test_position_with_no_recorded_strategy_is_skipped(self) -> None:
        """There is no thesis on record to have broken."""
        assert rules.thesis_broken([_position()], [_verdict()], {}) == []

    def test_a_buy_verdict_on_a_holding_is_not_a_break(self) -> None:
        candidates = rules.thesis_broken(
            [_position()],
            [_verdict(stance=Stance.BUY)],
            {"RELIANCE": ("minervini",)},
        )

        assert candidates == []

    def test_strategies_are_derived_from_trades(self) -> None:
        mapping = rules.strategies_by_ticker(
            [
                _trade("RELIANCE", "minervini"),
                _trade("RELIANCE", "young_momentum"),
                _trade("TCS", None),
            ]
        )

        assert mapping["RELIANCE"] == ("minervini", "young_momentum")
        assert "TCS" not in mapping


class TestOtherGenerators:
    def test_concentration_above_cap(self) -> None:
        positions = [_position("BIG", 100, 1000.0), _position("SMALL", 1, 1000.0)]

        candidates = rules.concentration(positions, cap_pct=50.0)

        assert [c.ticker for c in candidates] == ["BIG"]
        assert candidates[0].severity is Severity.HIGH

    def test_concentration_within_cap_is_silent(self) -> None:
        positions = [_position("A", 10, 1000.0), _position("B", 10, 1000.0)]

        assert rules.concentration(positions, cap_pct=60.0) == []

    def test_concentration_key_is_banded(self) -> None:
        """A position drifting 31% to 32% must not re-raise daily."""
        positions = [_position("BIG", 100, 1000.0), _position("SMALL", 40, 1000.0)]

        first = rules.concentration(positions, 50.0)[0]
        nudged = rules.concentration(
            [_position("BIG", 101, 1000.0), _position("SMALL", 40, 1000.0)], 50.0
        )[0]

        assert first.dedupe_key == nudged.dedupe_key

    def test_research_on_a_held_name_is_quoted_not_asserted(self) -> None:
        candidates = rules.position_research(
            [_position()], {"RELIANCE": [Finding("news_research", "Reliance announces buyback")]}
        )

        assert len(candidates) == 1
        assert candidates[0].payload["measured_by_platform"] is False
        assert candidates[0].payload["source_ref"] == "tool://x"
        assert "news_research" in candidates[0].body

    def test_research_on_an_unheld_name_is_ignored(self) -> None:
        assert rules.position_research([], {"TCS": [Finding("news_research", "x")]}) == []

    def test_failed_tool_output_is_not_an_insight(self) -> None:
        candidates = rules.position_research(
            [_position()], {"RELIANCE": [Finding("news_research", "unavailable: feed down")]}
        )

        assert candidates == []

    def test_event_findings_get_their_own_kind(self) -> None:
        candidates = rules.position_research(
            [_position()], {"RELIANCE": [Finding("event_calendar", "Earnings 2026-08-20")]}
        )

        assert candidates[0].kind is Kind.EVENT_DUE

    def test_opportunity_only_from_a_proceed(self) -> None:
        decisions = [
            {"outcome": "proceed", "ticker": "INFY", "strategy_id": "minervini",
             "reason": "10 shares", "quantity": 10, "notional": 15000.0},
            {"outcome": "blocked", "ticker": "TCS", "strategy_id": "minervini", "reason": "held"},
        ]

        candidates = rules.opportunities(decisions)

        assert [c.ticker for c in candidates] == ["INFY"]
        assert "separate, deliberate step" in candidates[0].body

    def test_book_full_only_when_something_was_blocked_by_it(self) -> None:
        positions = [_position(f"S{i}") for i in range(5)]

        assert rules.book_full(positions, 5, blocked=0) == []
        assert len(rules.book_full(positions, 5, blocked=2)) == 1

    def test_regime_change_only_on_an_actual_change(self) -> None:
        regime = {"label": "hostile", "detail": "below average"}

        assert rules.regime_change(regime, previous_label="hostile") == []
        assert len(rules.regime_change(regime, previous_label="constructive")) == 1


class TestSeverityIsAPropertyOfTheKind:
    def test_every_kind_declares_a_spec(self) -> None:
        for kind in Kind:
            assert kind in SPECS
            assert spec(kind).suppress_days >= 0

    def test_no_per_item_score_exists(self) -> None:
        """A score comparable across kinds is a ranking, which is the scorecard."""
        import inspect
        import re

        from app.insights import feed as feed_module
        from app.insights import rules as rules_module

        pattern = re.compile(r"def\s+(score|rank|prioriti[sz]e|importance)\w*", re.I)
        for module in (rules_module, feed_module):
            assert pattern.search(inspect.getsource(module)) is None


class TestFeed:
    @pytest.fixture
    def feed(self, session_factory) -> InsightFeed:
        return InsightFeed(session_factory)

    def _candidate(self, key: str = "thesis_broken:RELIANCE:minervini") -> Candidate:
        return Candidate(
            kind=Kind.THESIS_BROKEN,
            title="RELIANCE thesis broken",
            body="body",
            dedupe_key=key,
            ticker="RELIANCE",
        )

    def test_records_and_reads_back(self, feed: InsightFeed) -> None:
        report = feed.record([self._candidate()])

        assert report.written == 1
        items = feed.recent()
        assert items[0]["ticker"] == "RELIANCE"
        assert items[0]["severity"] == "high"

    def test_same_key_inside_the_window_is_suppressed(self, feed: InsightFeed) -> None:
        """A daily cycle must not repeat yesterday's insight until it is meaningless."""
        feed.record([self._candidate()])

        report = feed.record([self._candidate()])

        assert report.written == 0
        assert report.suppressed == 1

    def test_suppression_does_not_delete_the_original(self, feed: InsightFeed) -> None:
        """"This has been true for eleven days" must stay visible."""
        feed.record([self._candidate()])
        feed.record([self._candidate()])

        assert len(feed.recent()) == 1

    def test_a_different_key_is_not_suppressed(self, feed: InsightFeed) -> None:
        feed.record([self._candidate()])

        report = feed.record([self._candidate("thesis_broken:TCS:minervini")])

        assert report.written == 1

    def test_cap_applies_high_severity_first(self, feed: InsightFeed) -> None:
        low = Candidate(Kind.REGIME_CHANGE, "regime", "b", "regime_change:hostile")
        high = self._candidate()

        feed.record([low, high], limit=1)

        items = feed.recent()
        assert len(items) == 1
        assert items[0]["severity"] == "high"

    def test_truncation_is_reported(self, feed: InsightFeed) -> None:
        candidates = [self._candidate(f"k{i}") for i in range(5)]

        report = feed.record(candidates, limit=2)

        assert report.written == 2
        assert report.truncated == 3

    def test_unread_count_and_marking(self, feed: InsightFeed) -> None:
        feed.record([self._candidate()])
        assert feed.unread_count() == 1

        item_id = feed.recent()[0]["id"]
        assert feed.mark_read(item_id) is True
        assert feed.unread_count() == 0

    def test_marking_an_unknown_id_is_false_not_an_error(self, feed: InsightFeed) -> None:
        assert feed.mark_read(99999) is False

    def test_unread_only_filter(self, feed: InsightFeed) -> None:
        feed.record([self._candidate()])
        feed.mark_read(feed.recent()[0]["id"])

        assert feed.recent(unread_only=True) == []


class TestNoDeliveryChannel:
    def test_nothing_sends_anything_outbound(self) -> None:
        """`project.md` has said since 0001 that insights are in-app only."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        banned = re.compile(
            r"\b(smtplib|sendgrid|twilio|boto3\.client\(['\"]ses|webhook_url|"
            r"send_email|send_sms|push_notification)\b",
            re.I,
        )
        offenders = [
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if banned.search(p.read_text("utf-8"))
        ]

        assert offenders == []


class TestInsightsApi:
    @staticmethod
    def _client(settings):
        from fastapi.testclient import TestClient

        from app.main import create_app

        return TestClient(create_app(settings))

    def test_empty_feed_reads_cleanly(self, settings) -> None:
        body = self._client(settings).get("/insights").json()

        assert body["count"] == 0
        assert body["unread"] == 0

    def test_kinds_are_published_with_severity(self, settings) -> None:
        body = self._client(settings).get("/insights/kinds").json()

        kinds = {k["kind"]: k for k in body["kinds"]}
        assert kinds["thesis_broken"]["severity"] == "high"
        assert kinds["position_news"]["from_research"] is True

    def test_marking_unknown_id_is_404(self, settings) -> None:
        assert self._client(settings).post("/insights/4242/read").status_code == 404

    def test_unread_count_endpoint(self, settings) -> None:
        assert self._client(settings).get("/insights/unread-count").json() == {"unread": 0}


class TestSuppressionWindows:
    def test_windows_are_declared_per_kind(self) -> None:
        assert spec(Kind.THESIS_BROKEN).suppress_days == 7
        # Not worth restating until the regime changes back, which changes the key.
        assert spec(Kind.REGIME_CHANGE).suppress_days == 30

    def test_an_old_insight_outside_the_window_is_not_suppressed(
        self, session_factory
    ) -> None:
        from app.persistence.models import Insight as InsightRow

        with session_factory() as session:
            session.add(
                InsightRow(
                    kind=Kind.POSITION_NEWS.value,
                    ticker="RELIANCE",
                    title="old",
                    body="b",
                    payload={},
                    dedupe_key="position_news:RELIANCE:news_research",
                    severity="medium",
                    created_at=T0 - timedelta(days=365),
                )
            )
            session.commit()

        report = InsightFeed(session_factory).record(
            [
                Candidate(
                    Kind.POSITION_NEWS,
                    "new",
                    "b",
                    "position_news:RELIANCE:news_research",
                    ticker="RELIANCE",
                )
            ]
        )

        assert report.written == 1
