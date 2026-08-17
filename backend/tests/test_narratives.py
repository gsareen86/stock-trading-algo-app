"""Narrative generation, and the guard that makes it trustworthy.

The invariant under test: a narrative may contain no number the verdict did not establish, and
narrating can never change what a verdict says.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.verdict import Evidence, GateResult, Operator, Stance, Verdict
from app.llm.types import LLMResult, Message
from app.narratives import guard
from app.narratives.generator import Outcome, narrate, narrate_all
from app.narratives.prompts import build_messages, guidance_for

AS_OF = datetime(2026, 8, 17, tzinfo=UTC)


def _verdict(**overrides) -> Verdict:
    base = {
        "strategy_id": "minervini",
        "ticker": "RELIANCE",
        "as_of": AS_OF,
        "stance": Stance.WATCH,
        "conviction": 62,
        "evidence": (
            Evidence(
                id="rs_63d",
                label="Relative strength vs NIFTY 50 over 63 days",
                value=12.437,
                threshold=0.0,
                operator=Operator.GTE,
                passed=True,
                unit="%",
                source_ref="price://RELIANCE?window=63",
            ),
            Evidence(
                id="ma_200",
                label="Close vs 200-day moving average",
                value=1487.5,
                threshold=1402.0,
                operator=Operator.GT,
                passed=True,
                unit="INR",
                source_ref="price://RELIANCE?interval=1d",
            ),
            Evidence(
                id="contractions",
                label="VCP contractions detected",
                value=3,
                source_ref="price://RELIANCE?analysis=vcp",
            ),
        ),
    }
    return Verdict(**{**base, **overrides})


class FakeGateway:
    """Returns scripted text, and records what it was asked."""

    def __init__(self, text: str | None = "ok", trace_id: str | None = "trace-1") -> None:
        self._text = text
        self._trace_id = trace_id
        self.calls: list[list[Message]] = []

    async def complete(self, *, task, messages, schema=None):
        self.calls.append(messages)
        if self._text is None:
            return None
        return LLMResult(
            text=self._text, model="ollama/x", provider="ollama", trace_id=self._trace_id
        )


# ── the guard ─────────────────────────────────────────────────────────────────
class TestNumberExtraction:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("up 12.4%", [12.4]),
            ("closed at ₹1,487.50", [1487.50]),
            ("Rs 1,487.50 today", [1487.50]),
            ("volume was 2.5x average", [2.5]),
            ("1,23,456 shares", [123456.0]),
            ("three contractions", []),
            ("the 1st contraction", []),
            ("-3.2% pullback", [-3.2]),
        ],
    )
    def test_forms_are_extracted(self, text: str, expected: list[float]) -> None:
        """A numeric form this misses is a form that can carry an invented figure through."""
        assert guard.numbers_in(text) == expected


class TestTraceability:
    def test_exact_value_traces(self) -> None:
        assert guard.traces_to(12.437, {12.437})

    def test_rounded_value_traces(self) -> None:
        """Readable prose rounds; that must not be treated as invention."""
        assert guard.traces_to(12.4, {12.437})
        assert guard.traces_to(12.0, {12.437})

    def test_truncated_value_traces(self) -> None:
        """Found live: given 5.2968 the model wrote 5.29, which rounding alone rejects.

        Truncation is what writers actually do, and it stays inside one unit of the stated
        precision, so it cannot express a claim the evidence does not support.
        """
        assert guard.traces_to(5.29, {5.2968})
        assert guard.traces_to(12.4, {12.437})

    def test_near_miss_does_not_trace(self) -> None:
        """A figure that is merely nearby is a different claim."""
        assert not guard.traces_to(12.5, {12.437})
        assert not guard.traces_to(13.0, {12.437})
        assert not guard.traces_to(5.31, {5.2968})


class TestGuard:
    def test_narrative_using_only_evidence_passes(self) -> None:
        text = (
            "Relative strength is 12.4% [rs_63d], and price at 1487.5 sits above its "
            "200-day average [ma_200]. Three contractions [contractions] are present."
        )

        assert guard.check(text, _verdict()).ok

    def test_invented_number_is_caught(self) -> None:
        text = "Relative strength is 12.4% [rs_63d] and the stock is up 47.2% this year."

        result = guard.check(text, _verdict())

        assert not result.ok
        assert 47.2 in result.untraceable

    def test_label_derived_numbers_are_allowed(self) -> None:
        """`200` is in the row's label, not its value — correct prose must not be rejected."""
        text = "Price holds above the 200-day moving average [ma_200]."

        assert guard.check(text, _verdict()).ok

    def test_conviction_may_be_stated(self) -> None:
        assert guard.check("Conviction is 62 within this strategy.", _verdict()).ok

    def test_unknown_citation_is_caught(self) -> None:
        result = guard.check("Momentum is strong [made_up_id].", _verdict())

        assert not result.ok
        assert "made_up_id" in result.unknown_citations

    def test_citation_ids_do_not_leak_digits(self) -> None:
        """`[rs_63d]` must not put 63 on trial as a stated figure."""
        assert guard.check("Strength over the window [rs_63d] is constructive.", _verdict()).ok

    def test_dates_are_not_measurements(self) -> None:
        assert guard.check("As of 2026-08-17 the base is intact.", _verdict()).ok

    def test_small_invented_numbers_are_not_exempt(self) -> None:
        """An exemption for 'structural' small numbers would let 'up 2%' through invented."""
        result = guard.check("The stock is up 2% today.", _verdict())

        assert not result.ok
        assert 2.0 in result.untraceable

    def test_reason_names_the_offending_figure(self) -> None:
        result = guard.check("It gained 47.2% this year.", _verdict())

        assert "47.2" in result.reason


# ── prompt ────────────────────────────────────────────────────────────────────
class TestPrompt:
    def test_evidence_is_included_with_ids(self) -> None:
        user = build_messages(_verdict())[1].content

        assert "[rs_63d]" in user
        assert "12.437" in user

    def test_stance_is_given_as_decided(self) -> None:
        user = build_messages(_verdict())[1].content

        assert "WATCH" in user
        assert "do not revisit" in user

    def test_no_raw_prices_reach_the_model(self) -> None:
        """The guard only works because there is nothing to derive a new number from."""
        joined = " ".join(m.content for m in build_messages(_verdict()))

        assert "price_source" not in joined
        assert "OHLC" not in joined and "candle" not in joined.lower()

    def test_strategy_guidance_is_selected(self) -> None:
        system = build_messages(_verdict())[0].content

        assert "Trend Template" in system
        assert "contraction" in system

    def test_unknown_strategy_still_gets_base_rules(self) -> None:
        """A new strategy must be explainable before someone writes its prose guide."""
        text = guidance_for("not_a_real_strategy")

        assert "only numbers that appear in the evidence" in text


# ── generation ────────────────────────────────────────────────────────────────
class TestNarrate:
    async def test_valid_narrative_is_attached(self) -> None:
        gateway = FakeGateway("Strength is 12.4% [rs_63d]. The base is intact.")

        result = await narrate(_verdict(), gateway)

        assert result.outcome == Outcome.OK
        assert result.verdict.narrative is not None
        assert result.verdict.trace_id == "trace-1"

    async def test_invented_number_discards_the_whole_narrative(self) -> None:
        gateway = FakeGateway("Strength is 12.4% [rs_63d] and revenue grew 31%.")

        result = await narrate(_verdict(), gateway)

        assert result.outcome == Outcome.REJECTED
        assert result.verdict.narrative is None
        assert "31" in (result.detail or "")

    async def test_unavailable_model_leaves_the_verdict_unchanged(self) -> None:
        original = _verdict()

        result = await narrate(original, FakeGateway(text=None))

        assert result.outcome == Outcome.UNAVAILABLE
        assert result.verdict == original

    async def test_empty_response_is_not_a_narrative(self) -> None:
        result = await narrate(_verdict(), FakeGateway("   "))

        assert result.outcome == Outcome.EMPTY
        assert result.verdict.narrative is None


class TestNarrationCannotDecide:
    """Principle 5 held structurally, not by convention."""

    async def test_stance_conviction_gates_and_evidence_are_untouched(self) -> None:
        original = _verdict(
            stance=Stance.AVOID,
            gates=(
                GateResult(
                    id="liquidity",
                    label="Liquidity",
                    passed=False,
                    reason="median turnover below floor",
                    evidence_ids=("rs_63d",),
                ),
            ),
        )
        gateway = FakeGateway("Liquidity fails [rs_63d], so this is not actionable.")

        result = await narrate(original, gateway)

        assert result.verdict.stance is Stance.AVOID
        assert result.verdict.conviction == original.conviction
        assert result.verdict.gates == original.gates
        assert result.verdict.evidence == original.evidence

    async def test_rejected_narrative_still_returns_a_usable_verdict(self) -> None:
        original = _verdict()

        result = await narrate(original, FakeGateway("It rose 91.3% [rs_63d]."))

        assert result.verdict.stance is original.stance
        assert result.verdict.evidence == original.evidence


class TestNarrateAll:
    async def test_each_verdict_reports_its_own_outcome(self) -> None:
        good = _verdict()
        bad = _verdict(strategy_id="young_momentum")

        class Alternating:
            def __init__(self) -> None:
                self.n = 0

            async def complete(self, *, task, messages, schema=None):
                self.n += 1
                text = "Strength 12.4% [rs_63d]." if self.n == 1 else "It doubled to 999.9%."
                return LLMResult(text=text, model="m", provider="p")

        verdicts, report = await narrate_all([good, bad], Alternating())

        assert [r["outcome"] for r in report] == [Outcome.OK, Outcome.REJECTED]
        assert verdicts[0].narrative is not None
        assert verdicts[1].narrative is None
