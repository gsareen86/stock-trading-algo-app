"""Tests for deterministic Plan domain model and strategy Plan generation."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.data.fake import StaticPriceSource
from app.data.fundamentals import QuarterPoint, QuarterlyFundamentals, StaticFundamentalsSource
from app.domain.instrument import Instrument
from app.domain.verdict import Evidence, GateResult, Operator, Plan, Stance, Verdict
from app.strategies.brahma_vishnu_mahesh.strategy import BrahmaVishnuMaheshStrategy
from app.strategies.fun_tech_momentum.strategy import FunTechMomentumStrategy
from app.strategies.minervini.strategy import MinerviniStrategy
from app.strategies.protocols import StrategyContext
from app.strategies.registry import StrategyRegistry
from app.strategies.young_momentum.strategy import YoungMomentumStrategy

NOW = datetime(2026, 8, 14, tzinfo=UTC)
TCS = Instrument("TCS", sector="Information Technology")
BENCH = Instrument("NIFTY50")


def _ev(id_: str = "e1", val: float = 100.0) -> Evidence:
    return Evidence(
        id=id_,
        label="test",
        value=val,
        operator=Operator.INFO,
        unit="INR",
        source_ref="price://TCS",
    )


class TestPlanDomainInvariants:
    def test_computes_risk_reward_and_ratio(self) -> None:
        plan = Plan(
            entry=100.0,
            stop=90.0,
            target=130.0,
            holding_horizon="2–8 weeks",
            exit_rule="Weekly close below 50 SMA",
            evidence_ids=("entry_ev", "stop_ev", "target_ev"),
            entry_evidence_id="entry_ev",
            stop_evidence_id="stop_ev",
            target_evidence_id="target_ev",
        )

        assert plan.risk_inr == pytest.approx(10.0)
        assert plan.risk_pct == pytest.approx(10.0)
        assert plan.reward_inr == pytest.approx(30.0)
        assert plan.reward_pct == pytest.approx(30.0)
        assert plan.rr_ratio == pytest.approx(3.0)

    def test_rejects_stop_at_or_above_entry(self) -> None:
        with pytest.raises(ValueError, match="below entry"):
            Plan(
                entry=100.0,
                stop=100.0,
                holding_horizon="swing",
                exit_rule="stop",
                evidence_ids=("e1",),
            )

    def test_rejects_target_at_or_below_entry(self) -> None:
        with pytest.raises(ValueError, match="above entry"):
            Plan(
                entry=100.0,
                stop=95.0,
                target=99.0,
                holding_horizon="swing",
                exit_rule="stop",
                evidence_ids=("e1",),
            )

    def test_avoid_verdict_cannot_carry_plan(self) -> None:
        plan = Plan(
            entry=100.0,
            stop=95.0,
            holding_horizon="swing",
            exit_rule="stop",
            evidence_ids=("e1",),
        )
        with pytest.raises(ValueError, match="AVOID"):
            Verdict(
                strategy_id="minervini",
                ticker="TCS",
                as_of=NOW,
                stance=Stance.AVOID,
                conviction=20,
                evidence=(_ev("e1"),),
                plan=plan,
            )

    def test_plan_citing_missing_evidence_is_rejected(self) -> None:
        plan = Plan(
            entry=100.0,
            stop=95.0,
            holding_horizon="swing",
            exit_rule="stop",
            evidence_ids=("missing_row",),
        )
        with pytest.raises(ValueError, match="missing_row"):
            Verdict(
                strategy_id="minervini",
                ticker="TCS",
                as_of=NOW,
                stance=Stance.BUY,
                conviction=80,
                evidence=(_ev("e1"),),
                plan=plan,
            )

    def test_round_trip_dict(self) -> None:
        plan = Plan(
            entry=200.0,
            stop=180.0,
            target=260.0,
            holding_horizon="2–8 weeks",
            exit_rule="SMA break",
            evidence_ids=("e1", "e2"),
            entry_evidence_id="e1",
            stop_evidence_id="e2",
        )
        restored = Plan.from_dict(plan.as_dict())
        assert restored == plan


def _frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": volumes or [1_000_000.0] * n,
        },
        index=pd.date_range("2023-01-01", periods=n, freq="D"),
    )


class TestStrategyPlans:
    def test_minervini_vcp_produces_evidence_backed_plan(self) -> None:
        # Build uptrend then two tightening VCP contractions
        uptrend = [100.0 * (1.003 ** i) for i in range(240)]
        peak = uptrend[-1]
        c1 = list(np.linspace(peak, peak * 1.1, 10)) + list(np.linspace(peak * 1.1, peak * 0.95, 10))
        c2 = list(np.linspace(peak * 0.95, peak * 1.09, 10)) + list(np.linspace(peak * 1.09, peak * 1.03, 10))
        tail = list(np.linspace(peak * 1.03, peak * 1.08, 8))
        stock_df = _frame([float(x) for x in uptrend + c1 + c2 + tail])
        bench_df = _frame([100.0] * len(stock_df))

        verdict = MinerviniStrategy().evaluate(
            TCS, StrategyContext(price_source=StaticPriceSource({"TCS": stock_df, "NIFTY50": bench_df}), benchmark=BENCH, now=lambda: NOW)
        )

        assert verdict.stance is not Stance.AVOID
        assert verdict.plan is not None
        assert verdict.plan.stop < verdict.plan.entry
        assert set(verdict.plan.evidence_ids) <= {e.id for e in verdict.evidence}

    def test_young_momentum_plan_cites_entry_trigger_and_stop(self) -> None:
        base = [100.0] * 160
        impulse = list(np.linspace(100.0, 130.0, 10))
        pause = list(np.linspace(130.0, 126.0, 4))
        volumes = [1_000_000.0] * 160 + [4_000_000.0] * 10 + [400_000.0] * 4
        df = _frame([float(x) for x in base + impulse + pause], volumes)
        bench_df = _frame([100.0] * len(df))

        verdict = YoungMomentumStrategy().evaluate(
            TCS, StrategyContext(price_source=StaticPriceSource({"TCS": df, "NIFTY50": bench_df}), benchmark=BENCH, now=lambda: NOW)
        )

        assert verdict.stance is not Stance.AVOID
        assert verdict.plan is not None
        assert verdict.plan.entry_evidence_id == "entry_trigger"
        assert verdict.plan.stop_evidence_id == "entry_stop"

    def test_bvm_plan_cites_base_high_and_floor(self) -> None:
        closes = [100.0] * 400 + [100.0 * (1.02 ** i) for i in range(12)]
        volumes = [1_000_000.0] * 400 + [9_000_000.0] * 12
        df = _frame(closes, volumes)
        bench_df = _frame([100.0 * (1.002 ** i) for i in range(len(closes))])

        verdict = BrahmaVishnuMaheshStrategy().evaluate(
            TCS, StrategyContext(price_source=StaticPriceSource({"TCS": df, "NIFTY50": bench_df}), benchmark=BENCH, now=lambda: NOW)
        )

        assert verdict.stance is not Stance.AVOID
        assert verdict.plan is not None
        assert verdict.plan.entry_evidence_id == "plan_entry_breakout"
        assert verdict.plan.stop_evidence_id == "plan_stop_base_floor"

    def test_fun_tech_plan_cites_tight_base(self) -> None:
        from datetime import date

        closes = [100.0] * 280 + [100.0 * (1.004 ** i) for i in range(20)]
        volumes = [1_000_000.0] * 299 + [5_000_000.0]
        df = _frame(closes, volumes)
        from app.strategies.fun_tech_momentum.strategy import YEAR_AGO_INDEX

        eps = tuple(
            QuarterPoint(date(2026 - (i // 4), 12 - (i % 4) * 3, 28), v)
            for i, v in enumerate([30.0, 20.0, 12.0, 11.0, 10.0])
        )
        fundamentals = StaticFundamentalsSource(
            {"TCS": QuarterlyFundamentals(symbol="TCS", eps=eps, source_ref="fundamentals://test/TCS")}
        )
        verdict = FunTechMomentumStrategy().evaluate(
            TCS,
            StrategyContext(
                price_source=StaticPriceSource({"TCS": df, "NIFTY50": _frame([100.0] * 300)}),
                benchmark=BENCH,
                fundamentals_source=fundamentals,
                now=lambda: NOW,
            ),
        )

        assert verdict.stance is not Stance.AVOID
        assert verdict.plan is not None
        assert verdict.plan.entry_evidence_id == "plan_entry_tight_base"
        assert verdict.plan.stop_evidence_id == "plan_stop_tight_base"

    def test_avoid_verdict_from_short_history_has_no_plan(self) -> None:
        registry = StrategyRegistry.discover()
        ctx = StrategyContext(price_source=StaticPriceSource({"TCS": _frame([100.0] * 20)}), benchmark=BENCH, now=lambda: NOW)
        for defn in registry.definitions():
            v = defn.strategy.evaluate(TCS, ctx)
            assert v.stance is Stance.AVOID
            assert v.plan is None
