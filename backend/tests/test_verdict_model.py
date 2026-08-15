"""The decision model's invariants.

These are the rules the rebuild exists for. Each one is asserted as a *rejection*, because the
point is that the bad state cannot be constructed — not that it is discouraged.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.verdict import Evidence, GateResult, Operator, Stance, Verdict

AS_OF = datetime(2026, 8, 14, tzinfo=UTC)


def _evidence(id_: str = "e1", **overrides) -> Evidence:
    base = {
        "id": id_,
        "label": "test row",
        "value": 10.0,
        "source_ref": "price://TEST",
        "operator": Operator.GTE,
        "threshold": 5.0,
        "passed": True,
    }
    return Evidence(**{**base, **overrides})


def _verdict(**overrides) -> Verdict:
    base = {
        "strategy_id": "minervini",
        "ticker": "TCS",
        "as_of": AS_OF,
        "stance": Stance.BUY,
        "conviction": 80,
        "evidence": (_evidence(),),
        "gates": (),
    }
    return Verdict(**{**base, **overrides})


class TestGatesAreNotScores:
    def test_failed_gate_forbids_buy(self) -> None:
        """The confluence-scorecard fix, as a type constraint."""
        gate = GateResult(
            id="liquidity",
            label="Liquidity",
            passed=False,
            reason="no volume",
            evidence_ids=("e1",),
        )

        with pytest.raises(ValueError, match="AVOID"):
            _verdict(stance=Stance.BUY, gates=(gate,))

    def test_failed_gate_forbids_watch(self) -> None:
        gate = GateResult(id="liquidity", label="L", passed=False, reason="x")

        with pytest.raises(ValueError, match="AVOID"):
            _verdict(stance=Stance.WATCH, gates=(gate,))

    def test_failed_gate_with_avoid_is_allowed(self) -> None:
        gate = GateResult(id="liquidity", label="L", passed=False, reason="x")

        verdict = _verdict(stance=Stance.AVOID, gates=(gate,))

        assert verdict.stance is Stance.AVOID

    def test_conviction_survives_a_failed_gate(self) -> None:
        """The gate blocks the stance; it does not rewrite the score. They stay separable."""
        gate = GateResult(id="liquidity", label="L", passed=False, reason="x")

        verdict = _verdict(stance=Stance.AVOID, conviction=90, gates=(gate,))

        assert verdict.conviction == 90
        assert verdict.gates_passed is False

    def test_passing_gates_allow_buy(self) -> None:
        gate = GateResult(id="history", label="H", passed=True, reason="ok")

        assert _verdict(gates=(gate,)).stance is Stance.BUY


class TestEvidenceIntegrity:
    def test_verdict_without_evidence_rejected(self) -> None:
        with pytest.raises(ValueError, match="no evidence"):
            _verdict(evidence=())

    def test_duplicate_evidence_ids_rejected(self) -> None:
        """An ambiguous citation is not a citation."""
        with pytest.raises(ValueError, match="duplicate"):
            _verdict(evidence=(_evidence("dup"), _evidence("dup")))

    def test_gate_citing_missing_evidence_rejected(self) -> None:
        gate = GateResult(
            id="g", label="G", passed=True, reason="ok", evidence_ids=("nonexistent",)
        )

        with pytest.raises(ValueError, match="nonexistent"):
            _verdict(gates=(gate,))

    def test_gate_citing_present_evidence_accepted(self) -> None:
        gate = GateResult(id="g", label="G", passed=True, reason="ok", evidence_ids=("e1",))

        assert _verdict(gates=(gate,)).gates_passed is True

    def test_evidence_without_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="source_ref"):
            _evidence(source_ref="   ")

    def test_evidence_without_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="id"):
            _evidence(id_="")

    def test_informational_row_cannot_claim_a_pass(self) -> None:
        """Forcing context into pass/fail would fabricate a test that was never applied."""
        with pytest.raises(ValueError, match="informational"):
            _evidence(operator=Operator.INFO, passed=True, threshold=None)

    def test_informational_row_with_no_pass_state_is_fine(self) -> None:
        row = _evidence(operator=Operator.INFO, passed=None, threshold=None)

        assert row.passed is None


class TestConviction:
    @pytest.mark.parametrize("value", [-1, 101, 500])
    def test_out_of_range_rejected(self, value: int) -> None:
        with pytest.raises(ValueError, match="conviction"):
            _verdict(conviction=value)

    @pytest.mark.parametrize("value", [0, 50, 100])
    def test_in_range_accepted(self, value: int) -> None:
        assert _verdict(stance=Stance.AVOID, conviction=value).conviction == value

    def test_strategy_id_always_present(self) -> None:
        """Conviction is never interpretable without knowing whose scale it is on."""
        assert _verdict().strategy_id == "minervini"


class TestNoBlending:
    def test_module_exposes_no_aggregation(self) -> None:
        """A function combining verdicts would be the confluence scorecard returning."""
        import app.domain.verdict as module

        names = [n.lower() for n in dir(module) if not n.startswith("_")]
        for banned in ("combine", "aggregate", "merge", "blend", "consensus", "composite"):
            assert not any(banned in name for name in names), f"found {banned}"

    def test_two_strategies_disagreeing_both_stand(self) -> None:
        buy = _verdict(strategy_id="minervini", stance=Stance.BUY, conviction=85)
        avoid = _verdict(strategy_id="young_momentum", stance=Stance.AVOID, conviction=20)

        assert buy.stance is not avoid.stance
        assert {buy.strategy_id, avoid.strategy_id} == {"minervini", "young_momentum"}


class TestNarrativeIndependence:
    def test_verdict_is_complete_without_a_narrative(self) -> None:
        verdict = _verdict()

        assert verdict.narrative is None
        assert verdict.stance is Stance.BUY

    def test_numeric_values_expose_every_measured_figure(self) -> None:
        """`verdict-narratives` checks generated prose against exactly this set."""
        verdict = _verdict(
            evidence=(
                _evidence("a", value=12.5, threshold=10.0),
                _evidence("b", value=3.0, threshold=None, operator=Operator.INFO, passed=None),
            )
        )

        assert verdict.numeric_values == {12.5, 10.0, 3.0}

    def test_booleans_are_not_counted_as_numbers(self) -> None:
        verdict = _verdict(
            evidence=(_evidence("a", value=True, threshold=True, operator=Operator.EQ),)
        )

        assert verdict.numeric_values == set()


class TestSerialisation:
    def test_evidence_round_trips(self) -> None:
        original = _evidence("x", unit="%")

        restored = Evidence.from_dict(original.as_dict())

        assert restored == original

    def test_gate_round_trips(self) -> None:
        original = GateResult(id="g", label="G", passed=False, reason="why", evidence_ids=("e1",))

        assert GateResult.from_dict(original.as_dict()) == original

    def test_lookup_by_id(self) -> None:
        verdict = _verdict(evidence=(_evidence("a"), _evidence("b")))

        assert verdict.evidence_by_id("b").id == "b"
        assert verdict.evidence_by_id("missing") is None
