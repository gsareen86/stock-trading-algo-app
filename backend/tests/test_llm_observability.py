"""The call log and its aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.clock import IST, to_utc
from app.llm.recorder import CallRecord, CallRecorder
from app.llm.types import CallStatus
from app.llm.usage import collect_usage, recent_calls
from app.persistence.models import LlmCall


def _record(**overrides) -> CallRecord:
    base = {
        "task": "narrative",
        "provider": "anthropic",
        "model": "anthropic/claude-sonnet-5",
        "status": CallStatus.OK,
    }
    return CallRecord(**{**base, **overrides})


def _rows(factory) -> list[LlmCall]:
    with factory() as session:
        return list(session.execute(select(LlmCall).order_by(LlmCall.id)).scalars())


class TestRecording:
    def test_success_written(self, session_factory) -> None:
        CallRecorder(session_factory).record(
            _record(prompt_tokens=10, completion_tokens=5, total_tokens=15, cost_usd=0.01)
        )

        (row,) = _rows(session_factory)
        assert row.status == "ok"
        assert row.total_tokens == 15
        assert row.cost_usd == pytest.approx(0.01)

    @pytest.mark.parametrize(
        "status",
        [
            CallStatus.FAILED,
            CallStatus.RATE_LIMITED,
            CallStatus.BREAKER_OPEN,
            CallStatus.BUDGET_EXCEEDED,
            CallStatus.CACHED,
        ],
    )
    def test_every_status_is_recordable(self, session_factory, status: CallStatus) -> None:
        """Failure modes stay distinguishable — collapsing them would lose the diagnosis."""
        CallRecorder(session_factory).record(_record(status=status))

        (row,) = _rows(session_factory)
        assert row.status == status.value

    def test_fallback_is_visible_in_the_row(self, session_factory) -> None:
        CallRecorder(session_factory).record(
            _record(
                model="anthropic/claude-sonnet-5",
                requested_model="ollama/llama3.1",
                used_fallback=True,
                rung_index=1,
            )
        )

        (row,) = _rows(session_factory)
        assert row.used_fallback is True
        assert row.requested_model == "ollama/llama3.1"
        assert row.model == "anthropic/claude-sonnet-5"

    def test_requested_model_defaults_to_serving_model(self, session_factory) -> None:
        CallRecorder(session_factory).record(_record())

        (row,) = _rows(session_factory)
        assert row.requested_model == "anthropic/claude-sonnet-5"

    def test_error_message_truncated(self, session_factory) -> None:
        CallRecorder(session_factory).record(
            _record(status=CallStatus.FAILED, error_msg="x" * 5000)
        )

        (row,) = _rows(session_factory)
        assert len(row.error_msg) == 500

    def test_disabled_recorder_is_a_noop(self, session_factory) -> None:
        CallRecorder(None).record(_record())

        assert _rows(session_factory) == []


class TestRecordingCannotBreakACall:
    def test_write_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An observability layer that can take down what it observes is worse than none."""

        class ExplodingFactory:
            def __call__(self):
                raise RuntimeError("database on fire")

        CallRecorder(ExplodingFactory()).record(_record())  # must not raise


class TestUnpricedCalls:
    def test_local_call_records_null_cost_not_zero(self, session_factory) -> None:
        CallRecorder(session_factory).record(
            _record(provider="lemonade", model="lemonade/qwen3-8b", cost_usd=None)
        )

        (row,) = _rows(session_factory)
        assert row.cost_usd is None

    def test_aggregate_separates_priced_from_unpriced(self, session_factory) -> None:
        recorder = CallRecorder(session_factory)
        recorder.record(_record(cost_usd=0.02))
        recorder.record(_record(provider="lemonade", model="lemonade/q", cost_usd=None))
        recorder.record(_record(provider="lemonade", model="lemonade/q", cost_usd=None))

        totals = collect_usage(session_factory).totals

        assert totals.calls == 3
        assert totals.priced_calls == 1
        assert totals.unpriced_calls == 2
        assert totals.spend_usd == pytest.approx(0.02)

    def test_sum_of_costs_ignores_nulls(self, session_factory) -> None:
        recorder = CallRecorder(session_factory)
        recorder.record(_record(cost_usd=0.02))
        recorder.record(_record(cost_usd=None))

        with session_factory() as session:
            total = session.execute(select(func.sum(LlmCall.cost_usd))).scalar_one()
        assert total == pytest.approx(0.02)


class TestAggregation:
    def test_grouped_by_task_and_provider(self, session_factory) -> None:
        recorder = CallRecorder(session_factory)
        recorder.record(_record(task="narrative", cost_usd=0.01))
        recorder.record(_record(task="research", provider="openai", cost_usd=0.03))

        usage = collect_usage(session_factory).as_dict()

        assert set(usage["by_task"]) == {"narrative", "research"}
        assert set(usage["by_provider"]) == {"anthropic", "openai"}
        assert usage["by_task"]["research"]["spend_usd"] == pytest.approx(0.03)

    def test_failed_calls_counted(self, session_factory) -> None:
        recorder = CallRecorder(session_factory)
        recorder.record(_record(status=CallStatus.OK))
        recorder.record(_record(status=CallStatus.FAILED))
        recorder.record(_record(status=CallStatus.RATE_LIMITED))

        totals = collect_usage(session_factory).totals

        assert totals.calls == 3
        assert totals.failed_calls == 2

    def test_cached_calls_are_not_failures(self, session_factory) -> None:
        CallRecorder(session_factory).record(_record(status=CallStatus.CACHED))

        assert collect_usage(session_factory).totals.failed_calls == 0

    def test_empty_log_yields_zeroes(self, session_factory) -> None:
        usage = collect_usage(session_factory).as_dict()

        assert usage["totals"]["calls"] == 0
        assert usage["totals"]["spend_usd"] == 0.0


class TestIstDayAttribution:
    def test_call_after_ist_midnight_belongs_to_the_later_day(self, session_factory) -> None:
        """18:45 UTC is 00:15 IST the next day — the market day the operator is working."""
        now_ist = datetime.now(IST)
        just_after_midnight = now_ist.replace(hour=0, minute=15, second=0, microsecond=0)

        with session_factory() as session:
            session.add(
                LlmCall(
                    task="narrative",
                    provider="anthropic",
                    model="m",
                    requested_model="m",
                    status="ok",
                    cost_usd=0.01,
                    created_at=to_utc(just_after_midnight),
                )
            )
            session.commit()

        usage = collect_usage(session_factory, days=2).as_dict()

        assert just_after_midnight.date().isoformat() in usage["by_day"]

    def test_old_calls_fall_outside_the_window(self, session_factory) -> None:
        with session_factory() as session:
            session.add(
                LlmCall(
                    task="narrative",
                    provider="anthropic",
                    model="m",
                    requested_model="m",
                    status="ok",
                    cost_usd=9.99,
                    created_at=datetime.now(UTC) - timedelta(days=30),
                )
            )
            session.commit()

        assert collect_usage(session_factory, days=7).totals.calls == 0


class TestRecentCalls:
    def test_newest_first(self, session_factory) -> None:
        recorder = CallRecorder(session_factory)
        recorder.record(_record(task="first"))
        recorder.record(_record(task="second"))

        calls = recent_calls(session_factory)

        assert [c["task"] for c in calls] == ["second", "first"]

    def test_limit_respected(self, session_factory) -> None:
        recorder = CallRecorder(session_factory)
        for _ in range(5):
            recorder.record(_record())

        assert len(recent_calls(session_factory, limit=2)) == 2

    def test_failures_included_with_reason(self, session_factory) -> None:
        CallRecorder(session_factory).record(
            _record(status=CallStatus.FAILED, error_msg="RuntimeError: upstream exploded")
        )

        (call,) = recent_calls(session_factory)

        assert call["status"] == "failed"
        assert "upstream exploded" in call["error_msg"]

    def test_no_prompt_or_completion_fields(self, session_factory) -> None:
        """A ledger, not a transcript."""
        CallRecorder(session_factory).record(_record())

        (call,) = recent_calls(session_factory)

        assert not ({"prompt", "messages", "text", "completion"} & set(call))
